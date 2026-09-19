"""Recover historical vintages of the monthly A&E files from before this archive existed.

How it works
------------
NHS England does not overwrite a monthly file in place when it revises it (at least
from 2019 onward): the revised file is uploaded under a new URL and the year page's link
is repointed. The original stays on the server. So the vintage history of a period is,
to a first approximation, the set of *URLs that the year page has ever linked to* for
that period. The Internet Archive captures the year pages densely (dozens of distinct
versions per financial year from 2017-18), even though it rarely captures the files
themselves. Recovery therefore runs in three steps per financial year:

1. **Page history.** Ask the Wayback CDX index for every distinct version of the year
   page (``collapse=digest`` so a page is fetched once per change, not once per crawl).
   Fetch each version and extract the monthly file links with the same parser the live
   ingest uses. For every URL we record the first and last capture that showed it and
   every distinct link label (the label carries the stated revision date).

2. **Content history.** Older files (2015-16 to 2018-19) *were* replaced in place: the
   same URL served different bytes before and after a revision. So for every URL we ask
   CDX for its distinct content digests over time, fetch each version from the Wayback
   Machine, and fetch the current bytes from NHS England directly. The live copy is
   preferred whenever its digest matches a Wayback capture (it is the same bytes and
   the NHS server is faster and kinder to the Archive).

3. **Dating.** Each content version gets an ``available_from`` date: the most recent
   known publication event on or before the moment that content was observed. Events
   are, in order of preference, a stated revision date from a link label, the second
   Thursday of the URL's WordPress upload month (NHS England publishes on the second
   Thursday), and the first page capture that showed the link. The manifest records
   which rule fired (``available_from_source``) so nothing is silently precise.

What it cannot do
-----------------
If a file was replaced in place and the Archive never captured the earlier bytes, the
original is gone. ``nhs-ae-ingest coverage`` lists, per forecast origin, the periods
for which no version available at that origin exists; those go in Appendix A of the
pre-registration rather than being filled with revised data.

Everything that touches the network goes through ``Wayback`` (with a disk cache under
``data/cache/wayback``) or the ``nhs_session`` passed in, so the logic is testable with
fakes and re-runs cost nothing.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

from nhs_ae.config import (
    AE_STATS_BASE,
    CACHE_DIR,
    FINANCIAL_YEARS,
    MANIFEST_PATH,
    RAW_DIR,
    year_page_url,
)
from nhs_ae.ingest.discover import USER_AGENT, FileRef, extract_file_refs
from nhs_ae.ingest.download import (
    _append_manifest,
    known_hashes,
    read_manifest,
    sha256_bytes,
)
from nhs_ae.ingest.download import (
    available_from as _rec_available_from,
)

log = logging.getLogger(__name__)

CDX_URL = "https://web.archive.org/cdx/search/cdx"
WAYBACK_RAW_URL = "https://web.archive.org/web/{ts}id_/{url}"  # id_ = original bytes, no toolbar
_PAGE_PREFIX = AE_STATS_BASE.replace("https://", "")
_UPLOAD_RE = re.compile(r"/uploads/sites/2/(?P<y>20\d\d)/(?P<m>\d\d)/")
_UPLOAD_PREFIX = "www.england.nhs.uk/statistics/wp-content/uploads/sites/2/"


def _canon(url: str) -> str:
    """Scheme- and host-case-insensitive URL key (CDX echoes whatever it crawled)."""
    return url.split("://", 1)[-1].lower()
FIRST_PERIOD = date(2015, 6, 1)  # first monthly provider file


# --------------------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------------------
def second_thursday(year: int, month: int) -> date:
    """NHS England's publication day for the monthly A&E collection."""
    first = date(year, month, 1)
    first_thu = first + timedelta(days=(3 - first.weekday()) % 7)
    return first_thu + timedelta(days=7)


def publication_date(period: date) -> date:
    """When a period's file is first published: second Thursday of the following month."""
    y, m = (period.year + 1, 1) if period.month == 12 else (period.year, period.month + 1)
    return second_thursday(y, m)


def wayback_digest(content: bytes) -> str:
    """The CDX ``digest`` field: base32 SHA-1 of the payload."""
    return base64.b32encode(hashlib.sha1(content).digest()).decode()


def ts_to_date(ts: str) -> date:
    return date(int(ts[:4]), int(ts[4:6]), int(ts[6:8]))


def upload_month_estimate(url: str) -> date | None:
    m = _UPLOAD_RE.search(url)
    return second_thursday(int(m["y"]), int(m["m"])) if m else None


@dataclass(frozen=True)
class PageCapture:
    financial_year: str
    timestamp: str  # 14-digit Wayback timestamp
    url: str
    digest: str

    @property
    def captured_on(self) -> date:
        return ts_to_date(self.timestamp)


@dataclass
class Sighting:
    """One file URL as seen across the year page's captures."""

    ref: FileRef  # as parsed from the earliest capture that showed it
    first_seen: date
    last_seen: date
    labels: list[str] = field(default_factory=list)
    revised_dates: list[date] = field(default_factory=list)

    def note(self, cap_date: date, ref: FileRef) -> None:
        self.last_seen = max(self.last_seen, cap_date)
        if ref.link_text not in self.labels:
            self.labels.append(ref.link_text)
        if ref.revised_on and ref.revised_on not in self.revised_dates:
            self.revised_dates.append(ref.revised_on)
            self.revised_dates.sort()


def collect_sightings(pages: Iterable[tuple[PageCapture, str]], financial_year: str
                      ) -> dict[str, Sighting]:
    """Union of monthly file links across page captures, keyed by URL (pure)."""
    out: dict[str, Sighting] = {}
    for cap, html in sorted(pages, key=lambda p: p[0].timestamp):
        for ref in extract_file_refs(html, financial_year, base_url=cap.url):
            s = out.get(ref.url)
            if s is None:
                s = out[ref.url] = Sighting(ref=ref, first_seen=cap.captured_on,
                                            last_seen=cap.captured_on)
            s.note(cap.captured_on, ref)
    return out


def assign_available_from(sighting: Sighting, observed: list[date]) -> list[tuple[date, str]]:
    """Date each content version of a URL.

    ``observed`` holds, per content version in chronological order, the date the bytes
    were observed (Wayback capture date, or today for the live copy). Each version is
    dated by the most recent *precise* publication event on or before its observation:
    a stated revision date from a link label, or the second Thursday of the URL's
    upload month. The first version is additionally capped at the first page capture
    that showed the link (the file certainly existed by then). With no usable event the
    observation date itself is used and labelled as an upper bound; the same happens if
    a version would otherwise not be dated later than its predecessor.
    """
    events: list[tuple[date, str]] = []
    up = upload_month_estimate(sighting.ref.url)
    if up:
        events.append((up, "upload_month_second_thursday"))
    events.extend((d, "stated_revision_date") for d in sighting.revised_dates)
    events.sort()

    out: list[tuple[date, str]] = []
    prev: date | None = None
    for i, obs in enumerate(observed):
        eligible = [e for e in events if e[0] <= obs]
        if eligible:
            chosen = max(eligible, key=lambda e: (e[0], e[1] == "stated_revision_date"))
        elif sighting.first_seen <= obs:
            chosen = (sighting.first_seen, "first_page_capture")
        else:
            chosen = (obs, "observed_upper_bound")
        if i == 0 and chosen[0] > sighting.first_seen:
            chosen = (sighting.first_seen, "first_page_capture")
        if prev is not None and chosen[0] <= prev:
            chosen = (obs, "observed_upper_bound")
        out.append(chosen)
        prev = chosen[0]
    return out


# --------------------------------------------------------------------------------------
# Network: Wayback client with disk cache
# --------------------------------------------------------------------------------------
class Wayback:
    """Minimal CDX + raw-capture client. Every response is cached on disk."""

    RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

    def __init__(self, session: requests.Session | None = None,
                 cache_dir: Path = CACHE_DIR / "wayback",
                 delay: float = 0.5, retries: int = 5, timeout: int = 120):
        self.session = session or requests.Session()
        self.cache_dir = Path(cache_dir)
        self.delay, self.retries, self.timeout = delay, retries, timeout

    def _get(self, url: str, params: dict | None = None, cache_path: Path | None = None) -> bytes:
        if cache_path and cache_path.exists():
            return cache_path.read_bytes()
        last_exc: Exception | None = None
        for attempt in range(self.retries):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout,
                                        headers={"User-Agent": USER_AGENT})
                if resp.status_code in self.RETRY_STATUSES:
                    raise requests.HTTPError(f"{resp.status_code} from {url}", response=resp)
                resp.raise_for_status()
                content = resp.content
                break
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code not in self.RETRY_STATUSES:
                    raise
                last_exc = e
            except requests.RequestException as e:
                last_exc = e
            wait = 2 ** attempt
            log.warning("Wayback %s: %s – retrying in %ds", url, last_exc, wait)
            time.sleep(wait)
        else:
            raise RuntimeError(f"Wayback gave up on {url}: {last_exc}")
        if self.delay:
            time.sleep(self.delay)
        if cache_path:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(content)
        return content

    def cdx(self, params: dict) -> list[list[str]]:
        key = hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()[:16]
        raw = self._get(CDX_URL, params=params, cache_path=self.cache_dir / "cdx" / f"{key}.txt")
        return [line.split(" ") for line in raw.decode("utf-8", "replace").splitlines() if line.strip()]

    def page_captures(self, financial_year: str) -> list[PageCapture]:
        """Every distinct version of the year page, whatever slug it lived under."""
        rows = self.cdx({
            "url": _PAGE_PREFIX, "matchType": "prefix",
            "filter": [f"original:.*emergency-admissions-{financial_year}.*", "statuscode:200"],
            "collapse": "digest", "fl": "timestamp,original,digest", "limit": "5000",
        })
        caps = {}
        for ts, url, dg in (r for r in rows if len(r) == 3):
            if "?" in url:
                continue
            tail = url.split(_PAGE_PREFIX.split("/", 1)[1], 1)[-1].strip("/")
            if "/" in tail:  # a sub-page, not the year page
                continue
            caps[ts + url] = PageCapture(financial_year, ts, url, dg)
        uniq = caps
        return sorted(uniq.values(), key=lambda c: c.timestamp)

    def fetch_capture(self, cap: PageCapture) -> str:
        path = self.cache_dir / "pages" / cap.financial_year / f"{cap.timestamp}.html"
        return self._get(WAYBACK_RAW_URL.format(ts=cap.timestamp, url=cap.url),
                         cache_path=path).decode("utf-8", "replace")

    def file_versions(self, url: str) -> list[tuple[str, str]]:
        """(timestamp, digest) for each distinct content version of ``url`` in the Archive."""
        rows = self.cdx({"url": url, "filter": "statuscode:200", "collapse": "digest",
                         "fl": "timestamp,digest", "limit": "200"})
        return [(r[0], r[1]) for r in rows if len(r) >= 2]

    def file_versions_map(self, urls: Iterable[str]) -> dict[str, list[tuple[str, str]]]:
        """Bulk form of ``file_versions``: one CDX query per WordPress upload year.

        Single-URL CDX lookups take tens of seconds each; a prefix query over
        ``uploads/sites/2/<year>/`` returns every spreadsheet capture for the year in a
        couple of seconds. URLs outside that layout fall back to single lookups.
        """
        out: dict[str, list[tuple[str, str]]] = {}
        by_year: dict[str, list[str]] = {}
        for u in urls:
            m = _UPLOAD_RE.search(u)
            if m:
                by_year.setdefault(m["y"], []).append(u)
            else:
                out[u] = self.file_versions(u)
        for year, group in sorted(by_year.items()):
            prefix = _UPLOAD_PREFIX + year + "/"
            rows = self.cdx({"url": prefix, "matchType": "prefix",
                             "filter": ["statuscode:200", r"original:.*\.(csv|xls|xlsx)$"],
                             "collapse": "digest", "fl": "timestamp,original,digest",
                             "limit": "50000"})
            wanted = {_canon(u): u for u in group}
            for r in rows:
                if len(r) == 3 and _canon(r[1]) in wanted:
                    out.setdefault(wanted[_canon(r[1])], []).append((r[0], r[2]))
            for u in group:
                out.setdefault(u, []).sort()
        return out

    def fetch_file(self, url: str, ts: str) -> bytes:
        name = url.rsplit("/", 1)[-1]
        return self._get(WAYBACK_RAW_URL.format(ts=ts, url=url),
                         cache_path=self.cache_dir / "files" / f"{ts}_{name}")


def fetch_live(url: str, session: requests.Session, timeout: int = 120) -> bytes | None:
    """Current bytes from NHS England, or None if the URL is gone."""
    try:
        resp = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.content
    except requests.RequestException as e:
        log.warning("live fetch failed %s: %s", url, e)
        return None


# --------------------------------------------------------------------------------------
# Recovery
# --------------------------------------------------------------------------------------
def _store(content: bytes, ref: FileRef, avail: date, raw_dir: Path, seen: dict[str, dict]
           ) -> dict:
    """Write content under raw/<available_from>/ unless its hash is already archived."""
    digest = sha256_bytes(content)
    rec: dict = {"sha256": digest, "bytes": len(content)}
    if digest in seen:
        rec.update(stored=False, identical_to=seen[digest]["path"])
        return rec
    snap_dir = raw_dir / avail.isoformat()
    snap_dir.mkdir(parents=True, exist_ok=True)
    out = snap_dir / ref.filename
    if out.exists():  # same name, different bytes, same day: disambiguate
        out = snap_dir / f"{out.stem}-{digest[:8]}{out.suffix}"
    out.write_bytes(content)
    rec.update(stored=True, path=str(out.relative_to(raw_dir.parent.parent)))
    seen[digest] = rec
    return rec


def recover_url(sighting: Sighting, wayback: Wayback, nhs_session: requests.Session,
                raw_dir: Path, manifest_path: Path, seen: dict[str, dict],
                history: list[tuple[str, str]] | None = None,
                today: date | None = None) -> list[dict]:
    """Recover every content version of one URL. Returns the manifest records written.

    ``history`` is the URL's (timestamp, digest) list from the Archive (see
    ``Wayback.file_versions_map``); ``None`` means "look it up"; ``[]`` means skip.
    """
    today = today or date.today()
    ref = sighting.ref
    live = fetch_live(ref.url, nhs_session)
    live_digest = wayback_digest(live) if live is not None else None

    versions: list[tuple[str | None, str, bytes | None, str]] = []  # ts, digest, content, from
    if history is None:
        try:
            history = wayback.file_versions(ref.url)
        except (requests.RequestException, RuntimeError) as e:  # CDX hiccup: live copy only
            log.warning("file history unavailable for %s: %s", ref.url, e)
            history = []
    versions.extend((ts, dg, None, "wayback") for ts, dg in history)
    if live is not None and live_digest not in {v[1] for v in versions}:
        versions.append((None, live_digest, live, "nhs"))
    versions.sort(key=lambda v: v[0] or "99999999999999")

    base = {**asdict(ref), "recovered": True, "first_seen": sighting.first_seen,
            "last_seen": sighting.last_seen, "labels": sighting.labels,
            "revised_dates": sighting.revised_dates,
            "fetched_at": datetime.now(timezone.utc).isoformat()}
    if not versions:
        rec = {**base, "stored": False, "error": "no live copy and no Wayback capture",
               "snapshot": None, "available_from": None}
        _append_manifest(rec, manifest_path)
        return [rec]

    observed = [ts_to_date(ts) if ts else today for ts, *_ in versions]
    dated = assign_available_from(sighting, observed)
    written: list[dict] = []
    for (ts, dg, content, src), (avail, why) in zip(versions, dated):
        if content is None:
            if live is not None and dg == live_digest:
                content, src = live, "nhs"
            else:
                try:
                    content = wayback.fetch_file(ref.url, ts)
                except (requests.RequestException, RuntimeError) as e:
                    rec = {**base, "stored": False, "error": f"wayback fetch failed: {e}",
                           "wayback_timestamp": ts, "snapshot": avail, "available_from": avail,
                           "available_from_source": why}
                    _append_manifest(rec, manifest_path)
                    written.append(rec)
                    continue
        rec = {**base, "snapshot": avail, "available_from": avail, "available_from_source": why,
               "fetched_from": src, "wayback_timestamp": ts, "wayback_digest": dg,
               **_store(content, ref, avail, raw_dir, seen)}
        _append_manifest(rec, manifest_path)
        written.append(rec)
        log.info("%s %s available_from=%s (%s) %s", ref.period_label, ref.filename, avail, why,
                 "stored" if rec["stored"] else "duplicate")
    return written


def recover(financial_years: Iterable[str] = FINANCIAL_YEARS,
            wayback: Wayback | None = None,
            nhs_session: requests.Session | None = None,
            raw_dir: Path = RAW_DIR,
            manifest_path: Path = MANIFEST_PATH,
            file_history: bool = True,
            redo: bool = False,
            today: date | None = None) -> dict[str, int]:
    """Recover vintages for the given financial years. Idempotent: URLs already in the
    manifest are skipped unless ``redo``. Returns a small summary."""
    wayback = wayback or Wayback()
    nhs_session = nhs_session or requests.Session()
    manifest = read_manifest(manifest_path)
    seen = known_hashes(manifest)
    done_urls = {r["url"] for r in manifest if r.get("recovered") and not r.get("error")}
    summary = {"captures": 0, "urls": 0, "skipped": 0, "stored": 0, "duplicates": 0, "failed": 0}

    for fy in financial_years:
        caps = wayback.page_captures(fy)
        log.info("%s: %d distinct page versions", fy, len(caps))
        summary["captures"] += len(caps)
        pages = [(c, wayback.fetch_capture(c)) for c in caps]
        # The live page is the final "capture": it dates this month's files by their
        # upload month rather than by today's fetch, and covers months the Archive has
        # not crawled yet.
        live_html = fetch_live(year_page_url(fy), nhs_session)
        if live_html is not None:
            now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            pages.append((PageCapture(fy, now, year_page_url(fy), "live"),
                          live_html.decode("utf-8", "replace")))
        if not pages:
            log.warning("%s: no page captures and no live page", fy)
            continue
        sightings = collect_sightings(pages, fy)
        log.info("%s: %d distinct file URLs", fy, len(sightings))
        todo = {u: s for u, s in sightings.items() if redo or u not in done_urls}
        summary["skipped"] += len(sightings) - len(todo)
        history: dict[str, list[tuple[str, str]]] = (
            wayback.file_versions_map(todo) if file_history else {u: [] for u in todo})
        for url, s in sorted(todo.items(), key=lambda kv: (kv[1].ref.period, kv[1].first_seen)):
            summary["urls"] += 1
            for rec in recover_url(s, wayback, nhs_session, raw_dir, manifest_path, seen,
                                   history=history.get(url, []), today=today):
                if rec.get("error"):
                    summary["failed"] += 1
                elif rec.get("stored"):
                    summary["stored"] += 1
                else:
                    summary["duplicates"] += 1
    return summary


# --------------------------------------------------------------------------------------
# Coverage report (Appendix A of the pre-registration)
# --------------------------------------------------------------------------------------
def month_range(start: date, end: date) -> list[date]:
    out, cur = [], date(start.year, start.month, 1)
    while cur <= end:
        out.append(cur)
        cur = date(cur.year + 1, 1, 1) if cur.month == 12 else date(cur.year, cur.month + 1, 1)
    return out


def coverage(manifest: list[dict], origins: list[date], first_period: date = FIRST_PERIOD
             ) -> list[dict]:
    """For each origin, which already-published periods have no version available then.

    A period counts as published at origin ``t`` if its first publication date (second
    Thursday of the following month) is on or before ``t``. Pass each origin's as-of date,
    its second Thursday, as ``nhs-ae-ingest coverage`` does: that is the date the loader
    reads the archive at (``evaluate.asof.as_of_date``).
    """
    by_period: dict[str, list[date]] = {}
    for rec in manifest:
        if rec.get("stored"):
            by_period.setdefault(str(rec["period"])[:7], []).append(_rec_available_from(rec))
    rows = []
    for t in origins:
        expected = [p for p in month_range(first_period, t) if publication_date(p) <= t]
        missing = [p.strftime("%Y-%m") for p in expected
                   if not any(a <= t for a in by_period.get(p.strftime("%Y-%m"), []))]
        rows.append({"origin": t.strftime("%Y-%m"), "periods_expected": len(expected),
                     "periods_missing": len(missing), "missing": missing})
    return rows
