"""Archive machinery shared by the two external NHS England sources (KH03 beds, discharge).

The monthly A&E archive (``download``, ``recover``) is built around year pages and a
second-Thursday publication rule. KH03 and the acute discharge sitrep have neither, but
the same three facts about NHS England's statistics pages drive the design:

**A replaced file usually stays on the server.** A revision is uploaded under a new URL
and the page's link is repointed; the old URL keeps serving the old bytes (checked for
both sources in September 2026: the June and July 2022 discharge originals and the
2020-11 KH03 files are still served). So the versions of a period are, to a first
approximation, the URLs the page has *ever* linked to. ``collect`` gathers them from
three places: the live page(s), every distinct Internet Archive capture of those pages
(``page_history``), and the Archive's index of the WordPress upload folders
(``upload_index``), which finds files the captured pages never showed. Every URL is
fetched from NHS England first and from the Archive only if NHS England no longer
serves it.

**The upload folder is a floor, not a date.** ``/wp-content/uploads/sites/2/YYYY/MM/`` is
the month the file was uploaded, which bounds publication from below. It is not the
publication month: whole histories were re-uploaded (KH03 2019-20 to 2021-22 sit in
``2023/05``; discharge August 2025 to February 2026 in ``2026/04``), and every KH03 file
from 2010-11 to 2015-16 sits in ``2013/04`` whatever its date, because WordPress filed
attachments under the page's creation month at the time.

**The files state their own dates.** Both sources carry a title block (KH03) or cover
sheet (discharge) with ``Published:`` (first publication of that period) and
``Revised:`` (date of the revision these bytes carry). ``resolve_published`` turns those,
the link label, the upload folder and the first Archive sighting into one date per URL:
the day *these bytes* became public, with ``published_source`` saying which rule fired.
The stated date is trusted unless it precedes the upload folder (then the bytes are a
later re-upload and the date is bounded from above instead), so the result errs late,
never early: an as-of lookup can miss a version, but cannot see one before it existed.

Nothing here knows about either source's layout; ``SourceSpec`` carries the callables
that do. Network access goes through ``Fetcher`` (NHS England) and
``nhs_ae.ingest.recover.Wayback`` (Internet Archive, disk-cached under
``data/cache/wayback``), both injectable, so the logic is testable without network.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from nhs_ae.config import CACHE_DIR, MONTHS
from nhs_ae.ingest.discover import USER_AGENT
from nhs_ae.ingest.download import read_manifest, sha256_bytes
from nhs_ae.ingest.recover import PageCapture, Wayback

log = logging.getLogger(__name__)

WAYBACK_CACHE = CACHE_DIR / "wayback" / "external"
_UPLOAD_RE = re.compile(r"/uploads/sites/2/(?P<y>20\d\d)/(?P<m>\d\d)/")
_UPLOAD_PREFIX = "www.england.nhs.uk/statistics/wp-content/uploads/sites/2/"
_ORDINAL_RE = re.compile(r"(\d{1,2})(st|nd|rd|th)\b", re.IGNORECASE)
_NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{2,4})\b")
_ISO_DATE_RE = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")
_WORD_DATE_RE = re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})\b")


# --------------------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------------------
def upload_month(url: str) -> date | None:
    """First day of the WordPress upload-folder month in ``url``, if it has one."""
    m = _UPLOAD_RE.search(url)
    return date(int(m["y"]), int(m["m"]), 1) if m else None


def month_end(d: date) -> date:
    nxt = date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)
    return nxt - timedelta(days=1)


def parse_date(value) -> date | None:
    """A date from a title-block cell: a datetime, '20th August 2026', '21 May 2020',
    '2024-06-19 00:00:00' or '18.11.2021'. Placeholders ('-', '', NaN) give None."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (datetime, pd.Timestamp)):
        return pd.Timestamp(value).date()
    if isinstance(value, date):
        return value
    s = _ORDINAL_RE.sub(r"\1", str(value)).strip()
    if not s or s in {"-", "nan", "NaT", "None"}:
        return None
    m = _ISO_DATE_RE.search(s)
    if m:
        return _safe_date(int(m[1]), int(m[2]), int(m[3]))
    m = _NUMERIC_DATE_RE.search(s)
    if m:
        y = int(m[3]) + (2000 if int(m[3]) < 100 else 0)
        return _safe_date(y, int(m[2]), int(m[1]))
    m = _WORD_DATE_RE.search(s)
    if m:
        month = next((n for name, n in MONTHS.items() if name.startswith(m[2].lower()[:3])),
                     None)
        return _safe_date(int(m[3]), month, int(m[1])) if month else None
    return None


def today() -> date:
    return datetime.now(timezone.utc).date()


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def resolve_published(title_published: date | None, title_revised: date | None,
                      link_revised: date | None, upload: date | None,
                      first_seen: date | None) -> tuple[date | None, str]:
    """The day this file version became public, and the rule that fired.

    The stated date is the revision date (the later of the file's ``Revised:`` field and
    a revision date in the link text, which disagree now and then, e.g. 20 and 25
    November 2025 for KH03 Q1 2025-26), else the file's ``Published:`` date. It is used
    as is when it falls on or after the first day of the upload-folder month. A stated
    date *before* the upload month means the bytes were re-uploaded later (a
    re-publication, or a file migrated from an older site), so the version is dated by
    the first Internet Archive capture of a page linking it, else by the last day of the
    upload month: both are upper bounds, which is the safe direction for as-of use. With
    no stated date the same upper bounds apply.
    """
    revised = [(d, w) for d, w in ((title_revised, "title_block_revised"),
                                   (link_revised, "link_text_revised")) if d]
    if revised:
        stated, why = max(revised, key=lambda dw: dw[0])
    elif title_published:
        stated, why = title_published, "title_block_published"
    else:
        stated, why = None, ""
    if stated is not None and (upload is None or stated >= upload):
        return stated, why
    suffix = f" ({why} {stated} precedes upload folder {upload:%Y-%m})" if stated else ""
    if first_seen is not None and (upload is None or first_seen >= upload):
        return first_seen, "first_page_capture" + suffix
    if upload is not None:
        return month_end(upload), "upload_month_end" + suffix
    return None, "unknown"


# --------------------------------------------------------------------------------------
# Links and sightings
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Link:
    """One data file as advertised on a page (or found in the Archive's upload index)."""

    url: str
    filename: str
    period: date  # first day of the quarter or month the file covers
    label: str = ""
    revised_on: date | None = None  # revision date stated in the link text, if any


@dataclass
class Sighting:
    """Everything known about one URL before it is fetched."""

    link: Link
    labels: list[str] = field(default_factory=list)
    on_live_page: bool = False
    first_seen: date | None = None  # first Archive capture of a page linking the URL
    last_seen: date | None = None
    index_capture: str | None = None  # first Archive capture of the file itself

    def note_page(self, when: date, link: Link) -> None:
        self.first_seen = min(self.first_seen or when, when)
        self.last_seen = max(self.last_seen or when, when)
        self.add_label(link)

    def add_label(self, link: Link) -> None:
        if link.label and link.label not in self.labels:
            self.labels.append(link.label)
        if link.revised_on and not self.link.revised_on:
            self.link = Link(self.link.url, self.link.filename, self.link.period,
                             self.link.label or link.label, link.revised_on)


def canonical_url(url: str) -> str:
    """https, no port, query or fragment: old captures link http:// and the Archive's
    index echoes whatever it crawled, but it is one file."""
    rest = url.split("://", 1)[-1].split("#", 1)[0].split("?", 1)[0]
    host, _, path = rest.partition("/")
    return f"https://{host.split(':', 1)[0].lower()}/{path}"


def merge_sighting(out: dict[str, Sighting], link: Link) -> Sighting:
    url = canonical_url(link.url)
    if url != link.url:
        link = Link(url, link.filename, link.period, link.label, link.revised_on)
    s = out.get(url)
    if s is None:
        s = out[url] = Sighting(link=link)
    s.add_label(link)
    return s


# --------------------------------------------------------------------------------------
# Network
# --------------------------------------------------------------------------------------
class Fetcher:
    """Polite GET against NHS England: a User-Agent, a pause between requests, retries."""

    RETRY = frozenset({429, 500, 502, 503, 504})

    def __init__(self, session: requests.Session | None = None, delay: float = 1.0,
                 retries: int = 3, timeout: int = 120):
        self.session = session or requests.Session()
        self.delay, self.retries, self.timeout = delay, retries, timeout

    def get(self, url: str) -> bytes | None:
        """The response body, or None for a 404/410. Other failures raise."""
        last: Exception | None = None
        for attempt in range(self.retries):
            try:
                resp = self.session.get(url, headers={"User-Agent": USER_AGENT},
                                        timeout=self.timeout)
                if resp.status_code in (404, 410):
                    return None
                if resp.status_code in self.RETRY:
                    raise requests.HTTPError(f"{resp.status_code} from {url}", response=resp)
                resp.raise_for_status()
                return resp.content
            except requests.RequestException as e:
                last = e
                time.sleep(2 ** attempt)
            finally:
                if self.delay:
                    time.sleep(self.delay)
        raise RuntimeError(f"gave up on {url}: {last}")


def page_captures(wayback: Wayback, page_url: str, tag: str) -> list[PageCapture]:
    """Every distinct Archive capture of one page (``collapse=digest``), oldest first."""
    bare = page_url.split("://", 1)[-1]
    rows = wayback.cdx({"url": bare, "filter": "statuscode:200", "collapse": "digest",
                        "fl": "timestamp,original,digest", "limit": "5000"})
    caps = [PageCapture(tag, r[0], r[1], r[2]) for r in rows if len(r) == 3 and "?" not in r[1]]
    return sorted(caps, key=lambda c: c.timestamp)


def page_history(wayback: Wayback, page_urls: Iterable[str],
                 extract: Callable[[str, str], list[Link]], tag: str,
                 out: dict[str, Sighting] | None = None) -> dict[str, Sighting]:
    """Union of the data-file links on every Archive capture of the given pages."""
    out = {} if out is None else out
    for i, page in enumerate(page_urls):
        try:
            caps = page_captures(wayback, page, f"{tag}-{i}")
        except (requests.RequestException, RuntimeError) as e:
            log.warning("no page history for %s: %s", page, e)
            continue
        log.info("%s: %d distinct captures of %s", tag, len(caps), page)
        for cap in caps:
            try:
                html = wayback.fetch_capture(cap)
            except (requests.RequestException, RuntimeError) as e:
                log.warning("capture %s of %s failed: %s", cap.timestamp, page, e)
                continue
            for link in extract(html, cap.url):
                merge_sighting(out, link).note_page(cap.captured_on, link)
    return out


def upload_index(wayback: Wayback, years: Iterable[int], name_regex: str) -> dict[str, str]:
    """Files under the WordPress upload folders the Archive has captured, keyed by URL,
    with the timestamp of their first capture. ``name_regex`` filters the URL."""
    out: dict[str, str] = {}
    for y in years:
        try:
            rows = wayback.cdx({"url": f"{_UPLOAD_PREFIX}{y}/", "matchType": "prefix",
                                "filter": ["statuscode:200", f"original:{name_regex}"],
                                "fl": "timestamp,original", "limit": "20000"})
        except (requests.RequestException, RuntimeError) as e:
            log.warning("upload index %d unavailable: %s", y, e)
            continue
        for r in rows:
            if len(r) >= 2:
                url = canonical_url(r[1])
                if url not in out or r[0] < out[url]:
                    out[url] = r[0]
    return out


# --------------------------------------------------------------------------------------
# Raw store
# --------------------------------------------------------------------------------------
def append_jsonl(record: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record, default=str) + "\n")


def store_bytes(content: bytes, filename: str, raw_dir: Path, seen: dict[str, dict],
                project_root: Path) -> dict:
    """Write ``content`` once. Identical bytes already stored are not written again."""
    digest = sha256_bytes(content)
    rec: dict = {"sha256": digest, "bytes": len(content)}
    if digest in seen:
        rec.update(stored=False, identical_to=seen[digest]["path"])
        return rec
    raw_dir.mkdir(parents=True, exist_ok=True)
    out = raw_dir / filename
    if out.exists():  # same name, different bytes (a file replaced in place)
        out = raw_dir / f"{out.stem}__{digest[:8]}{out.suffix}"
    out.write_bytes(content)
    rec.update(stored=True, path=str(out.relative_to(project_root)))
    seen[digest] = rec
    return rec


def stored_by_hash(manifest: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for rec in manifest:
        if rec.get("stored") and rec.get("sha256") not in out:
            out[rec["sha256"]] = rec
    return out


# --------------------------------------------------------------------------------------
# Collection
# --------------------------------------------------------------------------------------
@dataclass
class SourceSpec:
    """What ``collect`` needs to know about one source."""

    name: str
    pages: tuple[str, ...]  # live page(s); the first is the current one
    raw_dir: Path
    manifest_path: Path
    project_root: Path
    extract_links: Callable[[str, str], list[Link]]  # (html, base_url) -> links
    link_from_url: Callable[[str], Link | None]  # for URLs found only in the upload index
    read_dates: Callable[[bytes], tuple[date | None, date | None]]  # -> (published, revised)
    index_years: tuple[int, ...] = ()
    index_regex: str = ""
    history_pages: tuple[str, ...] = ()  # extra page URLs whose captures to read


def collect(spec: SourceSpec, fetcher: Fetcher | None = None, wayback: Wayback | None = None,
            history: bool = True, refetch_live: bool = True) -> dict[str, int]:
    """Discover, fetch and archive every version of every file. Idempotent: URLs already
    in the manifest are not fetched again, except those on the live page when
    ``refetch_live`` (so a file replaced in place under the same URL is caught)."""
    fetcher = fetcher or Fetcher()
    manifest = read_manifest(spec.manifest_path)
    seen = stored_by_hash(manifest)
    done = {r["url"] for r in manifest if not r.get("error")}
    sightings: dict[str, Sighting] = {}

    for page in spec.pages:
        html = fetcher.get(page)
        if html is None:
            log.warning("%s: page %s is gone", spec.name, page)
            continue
        links = spec.extract_links(html.decode("utf-8", "replace"), page)
        log.info("%s: %d file links on %s", spec.name, len(links), page)
        for link in links:
            merge_sighting(sightings, link).on_live_page = True

    if history:
        wayback = wayback or Wayback(cache_dir=WAYBACK_CACHE, delay=1.0)
        page_history(wayback, spec.pages + spec.history_pages, spec.extract_links,
                     spec.name, sightings)
        if spec.index_years:
            for url, ts in upload_index(wayback, spec.index_years, spec.index_regex).items():
                link = spec.link_from_url(url)
                if link is None:
                    continue
                s = merge_sighting(sightings, link)
                s.index_capture = min(s.index_capture or ts, ts)

    summary = {"urls": len(sightings), "fetched": 0, "stored": 0, "duplicates": 0,
               "skipped": 0, "failed": 0}
    for url, s in sorted(sightings.items(), key=lambda kv: (kv[1].link.period, kv[0])):
        if url in done and not (refetch_live and s.on_live_page):
            summary["skipped"] += 1
            continue
        rec = _fetch_one(spec, s, fetcher, wayback if history else None, seen)
        append_jsonl(rec, spec.manifest_path)
        summary["fetched"] += 1
        if rec.get("error"):
            summary["failed"] += 1
        elif rec.get("stored"):
            summary["stored"] += 1
        else:
            summary["duplicates"] += 1
    return summary


def _fetch_one(spec: SourceSpec, s: Sighting, fetcher: Fetcher, wayback: Wayback | None,
               seen: dict[str, dict]) -> dict:
    link = s.link
    base = {
        "url": link.url, "filename": link.filename, "period": link.period,
        "labels": s.labels, "on_live_page": s.on_live_page, "first_seen": s.first_seen,
        "last_seen": s.last_seen, "index_capture": s.index_capture,
        "upload_month": upload_month(link.url), "link_revised": link.revised_on,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    content, source, err = None, None, None
    try:
        content, source = fetcher.get(link.url), "nhs_live"
    except RuntimeError as e:
        err = str(e)
    if content is None and wayback is not None:
        ts = s.index_capture or _first_capture(wayback, link.url)
        if ts:
            try:
                content, source = wayback.fetch_file(link.url, ts), f"wayback:{ts}"
            except (requests.RequestException, RuntimeError) as e:
                err = f"wayback: {e}"
    if content is None:
        return {**base, "stored": False, "error": err or "gone from NHS England, not archived"}
    try:
        title_pub, title_rev = spec.read_dates(content)
    except Exception as e:  # noqa: BLE001 – an unreadable file is still archived
        log.warning("%s: no title-block dates in %s: %s", spec.name, link.filename, e)
        title_pub, title_rev = None, None
    published, why = resolve_published(title_pub, title_rev, link.revised_on,
                                        base["upload_month"], s.first_seen)
    rec = {**base, "fetched_from": source, "title_published": title_pub,
           "title_revised": title_rev, "published": published, "published_source": why,
           **store_bytes(content, link.filename, spec.raw_dir, seen, spec.project_root)}
    log.info("%s %s %s published=%s (%s) %s", spec.name, link.period, link.filename, published,
             why, "stored" if rec["stored"] else "duplicate")
    return rec


def _first_capture(wayback: Wayback, url: str) -> str | None:
    try:
        rows = wayback.cdx({"url": url.split("://", 1)[-1], "filter": "statuscode:200",
                            "fl": "timestamp", "limit": "1"})
    except (requests.RequestException, RuntimeError):
        return None
    return rows[0][0] if rows and rows[0] else None


def redate(rec: dict) -> dict:
    """Re-apply ``resolve_published`` to a manifest record's recorded inputs, so a rule
    change takes effect on an offline rebuild. Records without the inputs keep theirs."""
    if "title_published" not in rec and "upload_month" not in rec:
        return rec
    pub, why = resolve_published(as_date(rec.get("title_published")),
                                 as_date(rec.get("title_revised")),
                                 as_date(rec.get("link_revised")),
                                 as_date(rec.get("upload_month")),
                                 as_date(rec.get("first_seen")))
    return {**rec, "published": pub.isoformat() if pub else None, "published_source": why}


def manifest_versions(manifest: list[dict]) -> list[dict]:
    """One record per distinct content (sha256), dated by the earliest URL carrying it.

    The same bytes are often linked under two URLs (a re-upload); the content was public
    from the earlier of their dates. Failed records are dropped.
    """
    by_hash: dict[str, list[dict]] = {}
    for rec in manifest:
        if rec.get("error") or not rec.get("sha256"):
            continue
        by_hash.setdefault(rec["sha256"], []).append(redate(rec))
    out = []
    for digest, recs in by_hash.items():
        stored = [r for r in recs if r.get("stored")]
        if not stored:
            continue
        dated = [r for r in recs if r.get("published")]
        first = min(dated, key=lambda r: str(r["published"])) if dated else stored[0]
        out.append({**first, "path": stored[0]["path"], "sha256": digest,
                    "urls": sorted({r["url"] for r in recs}),
                    "on_live_page": any(r.get("on_live_page") for r in recs)})
    return out


def as_date(v) -> date | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


# --------------------------------------------------------------------------------------
# Versions of one period
# --------------------------------------------------------------------------------------
def same_values(a: pd.DataFrame, b: pd.DataFrame, value_cols: Iterable[str]) -> bool:
    """True if two parsed versions carry the same organisations and values."""
    cols = list(value_cols)
    ka = a.set_index("org_code")[cols].sort_index()
    kb = b.set_index("org_code")[cols].sort_index()
    if not ka.index.equals(kb.index):
        return False
    return bool(np.allclose(ka.to_numpy(float), kb.to_numpy(float), equal_nan=True,
                            rtol=0, atol=1e-9))


def drop_reuploads(group: list[tuple[dict, pd.DataFrame]], value_cols: Iterable[str],
                   label: str = "") -> list[tuple[dict, pd.DataFrame]]:
    """Order one period's versions by publication and drop any whose values repeat the
    version before it: a re-upload is not a revision, and the earlier copy was visible
    first."""
    group = sorted(group, key=lambda vr: (str(vr[0].get("published") or "9999"),
                                          vr[0].get("filename", "")))
    kept: list[tuple[dict, pd.DataFrame]] = []
    for v, rows in group:
        if kept and same_values(kept[-1][1], rows, value_cols):
            log.info("%s: %s repeats %s; dropped as a re-upload", label, v.get("filename"),
                     kept[-1][0].get("filename"))
            continue
        kept.append((v, rows))
    return kept


def versions_table(df: pd.DataFrame, key: str, period_end: pd.Series,
                   value_cols: Iterable[str], national_col: str) -> pd.DataFrame:
    """One row per version: when it was published and by which rule, the lag after the
    period's end, and what changed against the version before it (organisations added,
    dropped or with any changed value; the England figure ``national_col`` before and
    after)."""
    cols = list(value_cols)
    df = df.assign(_end=period_end)
    rows = []
    for period, g in df.groupby(key, sort=True):
        prev = None
        for ver, v in g.groupby("version", sort=True):
            first = v.iloc[0]
            trusts = v[~v["is_total"]].set_index("org_code")
            nat = v.loc[v["is_total"], national_col]
            rec = {key: period, "version": ver, "n_versions": first["n_versions"],
                   "is_latest": first["is_latest"], "source_file": first["source_file"],
                   "published": first["published"],
                   "published_source": first["published_source"],
                   "first_published": first["first_published"],
                   "lag_days": (first["published"] - first["_end"]).days,
                   "first_lag_days": (first["first_published"] - first["_end"]).days,
                   "n_orgs": len(trusts), "layout": first["layout"],
                   "national": float(nat.iloc[0]) if len(nat) else np.nan,
                   "orgs_added": np.nan, "orgs_dropped": np.nan, "orgs_changed": np.nan,
                   "national_change": np.nan, "url": first["url"]}
            if prev is not None:
                p_trusts, p_nat = prev
                common = trusts.index.intersection(p_trusts.index)
                a = trusts.loc[common, cols].to_numpy(float)
                b = p_trusts.loc[common, cols].to_numpy(float)
                same = np.isclose(a, b, rtol=0, atol=1e-9, equal_nan=True).all(axis=1)
                rec.update(orgs_added=len(trusts.index.difference(p_trusts.index)),
                           orgs_dropped=len(p_trusts.index.difference(trusts.index)),
                           orgs_changed=int((~same).sum()),
                           national_change=rec["national"] - p_nat)
            prev = (trusts, rec["national"])
            rows.append(rec)
    return pd.DataFrame(rows)


def first_publication(stated: Iterable[date | None], published: Iterable) -> date | None:
    """A period's first publication: the earliest ``Published:`` date any of its versions
    states, else (no version states one, e.g. the October 2024 discharge file, which has
    no cover sheet) the earliest version date."""
    dates = [d for d in stated if d]
    if dates:
        return min(dates)
    dated = [as_date(p) for p in published if p]
    return min(dated) if dated else None


def as_of(df: pd.DataFrame, when, key: str, use_first_published: bool = False
          ) -> pd.DataFrame:
    """For every period (``key``), the rows of the version current on ``when``.

    Strict mode takes the latest version with ``published <= when``. With
    ``use_first_published`` a period becomes visible on its first publication and shows
    its latest values: revisions leak, which is the usual shortcut, made explicit.
    """
    when = pd.Timestamp(when)
    if use_first_published:
        return df[df["is_latest"] & (df["first_published"] <= when)].reset_index(drop=True)
    vis = df[df["published"] <= when]
    if vis.empty:
        return vis.reset_index(drop=True)
    cur = vis.groupby(key)["version"].transform("max")
    return vis[vis["version"] == cur].reset_index(drop=True)
