"""Provider-to-ICB mapping: NHS England's "System Mapping File", archived and tidied.

What NHS England publishes (checked 2026-09-10 against the live year pages, Internet
Archive captures of them, and the WordPress upload paths)
------------------------------------------------------------------------------------
* **System Mapping File** (heading "Provider to System Mapping"): one sheet, "ICB Mapping",
  columns Code, Name, ICB Code, ICB Name, Region Name, one row per provider that submits
  the monthly return. Type 3 walk-in centres, community trusts and independent-sector UTCs
  are listed under their own ICB, though each version misses a handful of active codes.
  It first appeared on 8 February 2023, on the 2022-23 page; there is no provider-to-ICB
  file for earlier data. It is *not* republished monthly: 16 uploads up to September 2026 (one
  byte-identical to its predecessor), each under a new URL, and a year page links only its
  latest. Superseded versions stay on the server, but the Internet Archive captured only
  14 of them, so ``--probe`` also tries the upload paths NHS England has used. Versions
  differ mostly by a few Type 3 codes added or dropped.
* **The April 2026 ICB mergers.** The 2026-27 file (``System-Mapping-Apr-26.xls``) has 36
  ICBs, not 42: twelve ICBs became six on 1 April 2026 (ODS legal start date), and
  Hertfordshire and West Essex was split between two of them, so the new structure is not
  a coarsening of the old one. The 2025-26 file still describes the 42.
* **Acute / Type 3 Trust Attribution File** (2017-18 page onwards): sheet "Attribution"
  apportions each Type 3 provider's attendances to acute trusts (fractions for a few);
  sheet "STP Mapping" maps about 270 provider codes to the 44 STPs of 2016-2020. That
  sheet has been frozen since March 2018 apart from a handful of additions, but it is the
  only NHS England geography for codes that vanished before 2023, so it feeds the backfill.

Quirks the parser handles
-------------------------
* A title block sits above the header. The header row is found by its cells, not its
  position, and column A is empty.
* One provider (NNFA7) is listed twice in every version. Exact duplicates are dropped;
  a code listed under two different ICBs raises.
* Codes are not consistently upper-case (``NTV0b`` in the mapping, ``NTV0B`` in the
  monthly files), so every code is upper-cased.
* Region labels read "<region> Commissioning Region". The February and August 2023 files
  still use the old four-region labels for most rows (North of England, Midlands and East
  of England, South of England), which become LEGACY. Later files use the seven current
  regions.
* "Last Updated" is free text ("26th June 2022", "14 May 2026") and is not the publication
  date: the February 2023 file says June 2022. ``published`` is the HTTP Last-Modified
  date. Most such dates are second-Thursday publication days; a few are one to eleven
  days off (early uploads and corrections).

Dates
-----
``period``      the data month the file was published alongside: the month before its
                WordPress upload month.
``published``   HTTP Last-Modified date (second Thursday of the upload month if absent).
``valid_from``  first data month the mapping describes: the start of ``period``'s
                financial year, but never before 2022-07-01, when ICBs became statutory.

Backfill
--------
The current file lists about 200 codes; the monthly data hold about 330 across 2015-2026.
The missing ones are mostly trusts that merged: they account for 15% of 2015 emergency
admissions via A&E, and would put level shifts into ICB series. ``backfill_codes``
assigns such a code to an ICB of the target mapping. It tries three sources, in order:
1. the ICB of its ODS successor (history follows the organisation that now reports it);
2. its ICB in an earlier NHS England mapping, translated to the target structure where
   that ICB was merged away;
3. its STP in the legacy sheet, when every current provider of that STP sits in one
   target ICB.
Ambiguous cases stay unassigned, and ``nhs_ae.features.hierarchy`` puts them in the
UNMAPPED bucket. Against the September 2026 data that leaves 35 codes, nearly all Type 3
or community services: a few sit in the STPs that straddle ICB boundaries (Bristol, West
Yorkshire, Hertfordshire and West Essex), and the rest closed before 2018 without an ODS
successor. They are at most 0.02% of emergency admissions via A&E in any year, and of
attendances 3% in 2015, under 1% from 2017 and nothing after 2021.

Layout
------
::

    data/external/icb_mapping/raw/<upload yyyy-mm>/<file>  immutable copies
    data/external/icb_mapping/manifest.jsonl               one line per fetch
    data/external/icb_mapping/ods_records.json             ODS organisation records
    data/reference/provider_icb_map.csv                    current mapping, one row per provider
    data/reference/provider_icb_map_history.csv            every version
    data/reference/provider_icb_backfill.csv               derived rows for codes absent from it
    data/reference/provider_stp_legacy.csv                 the tidy "STP Mapping" sheet

Usage::

    python -m nhs_ae.ingest.icb_mapping run --probe   # fetch new files (+ old versions), build
    python -m nhs_ae.ingest.icb_mapping build         # rebuild the reference tables offline
    python -m nhs_ae.ingest.icb_mapping check --data data/processed/ae_monthly_latest.parquet
"""

from __future__ import annotations

import argparse
import calendar
import email.utils
import io
import json
import logging
import re
import sys
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

from nhs_ae.config import DATA_DIR, FINANCIAL_YEARS, MONTHS, PROCESSED_DIR, year_page_url
from nhs_ae.features.hierarchy import LEGACY, normalise_region
from nhs_ae.ingest.discover import USER_AGENT, fetch_year_page, is_mapping_link
from nhs_ae.ingest.download import _append_manifest, known_hashes, read_manifest, sha256_bytes
from nhs_ae.ingest.lineage import fetch_org, successions_from_record
from nhs_ae.ingest.recover import _UPLOAD_RE, upload_month_estimate

log = logging.getLogger(__name__)

ICB_DIR = DATA_DIR / "external" / "icb_mapping"
RAW_ICB_DIR = ICB_DIR / "raw"
ICB_MANIFEST = ICB_DIR / "manifest.jsonl"
ODS_RECORDS = ICB_DIR / "ods_records.json"
REFERENCE_DIR = DATA_DIR / "reference"
CURRENT_CSV = "provider_icb_map.csv"
HISTORY_CSV = "provider_icb_map_history.csv"
BACKFILL_CSV = "provider_icb_backfill.csv"
STP_CSV = "provider_stp_legacy.csv"

UPLOAD_BASE = "https://www.england.nhs.uk/statistics/wp-content/uploads/sites/2/"
ICB_STATUTORY_START = date(2022, 7, 1)   # ODS: ICB role RO318, legal start
FIRST_UPLOAD_MONTH = date(2022, 7, 1)    # earliest month --probe tries
SYSTEM_MAPPING, TYPE3_ATTRIBUTION = "system_mapping", "type3_attribution"
_VERSION_ORDER = ["valid_from", "published", "source"]
_MONTH_ABBR = {m[:3]: i for m, i in MONTHS.items()}


# --------------------------------------------------------------------------------------
# Links
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class MappingRef:
    """One mapping or attribution workbook, as linked from a year page or found by probing."""

    url: str
    kind: str                  # system_mapping | type3_attribution
    link_text: str = ""
    linked_from: str | None = None   # financial year of the page that linked it
    discovered_via: str = "live_page"  # live_page | url_probe

    @property
    def filename(self) -> str:
        return self.url.rsplit("/", 1)[-1].split("?", 1)[0]


def classify_link(href: str, text: str) -> str | None:
    """``system_mapping``, ``type3_attribution`` or None.

    The 2023 mapping files are named ``Trust-ICB-Attribution-File.xls``, so "ICB" or
    "system mapping" wins over "attribution".
    """
    if not is_mapping_link(href, text):
        return None
    low = (text + " " + href.rsplit("/", 1)[-1]).lower().replace("-", " ")
    if "system mapping" in low or "icb" in low:
        return SYSTEM_MAPPING
    return TYPE3_ATTRIBUTION if "attribution" in low else None


def extract_mapping_refs(html: str, financial_year: str, base_url: str = "") -> list[MappingRef]:
    """Mapping and attribution links on one year page, in page order (pure)."""
    out: dict[str, MappingRef] = {}
    for a in BeautifulSoup(html, "lxml").find_all("a", href=True):
        url = urljoin(base_url, a["href"])
        text = a.get_text(" ", strip=True)
        kind = classify_link(url, text)
        if kind and url not in out:
            out[url] = MappingRef(url, kind, text, financial_year, "live_page")
    return list(out.values())


def probe_candidates(start: date = FIRST_UPLOAD_MONTH, end: date | None = None) -> list[str]:
    """Upload paths NHS England has used for mapping files, for every month in range.

    The names seen so far are ``Trust-ICB-Attribution-File.xls`` (2023),
    ``<Month>-<YYYY>-System-Mapping.xls`` (spring 2024), ``System-Mapping.xls`` and
    ``System-Mapping-<Mon>-<YY>.xls``, with WordPress's ``-1`` suffix on re-uploads.
    """
    end = end or datetime.now(timezone.utc).date()
    urls: list[str] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        names = ["Trust-ICB-Attribution-File.xls", "Trust-ICB-Attribution-File-1.xls",
                 "System-Mapping.xls", "System-Mapping-1.xls"]
        for yy, mm in ((y, m), (y, m - 1) if m > 1 else (y - 1, 12)):
            names += [f"{calendar.month_name[mm]}-{yy}-System-Mapping.xls",
                      f"System-Mapping-{calendar.month_abbr[mm]}-{str(yy)[2:]}.xls"]
        urls += [f"{UPLOAD_BASE}{y}/{m:02d}/{n}" for n in names]
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return sorted(set(urls))


# --------------------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------------------
def _fy_start_year(d: date) -> int:
    return d.year if d.month >= 4 else d.year - 1


def financial_year_of(d: date) -> str:
    y = _fy_start_year(d)
    return f"{y}-{str(y + 1)[-2:]}"


def data_period(url: str, published: date | None = None) -> date | None:
    """The month before the WordPress upload month (or before ``published``)."""
    m = _UPLOAD_RE.search(url)
    if m:
        y, mo = int(m["y"]), int(m["m"])
    elif published:
        y, mo = published.year, published.month
    else:
        return None
    return date(y - 1, 12, 1) if mo == 1 else date(y, mo - 1, 1)


def valid_from(period: date) -> date:
    return max(date(_fy_start_year(period), 4, 1), ICB_STATUTORY_START)


def parse_last_updated(value) -> date | None:
    """'26th June 2022', '14 May 2026', or an Excel date cell."""
    if isinstance(value, datetime):
        return value.date()
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3})[a-z]*\.?\s+(\d{4})", str(value))
    if m and m[2].lower() in _MONTH_ABBR:
        return date(int(m[3]), _MONTH_ABBR[m[2].lower()], int(m[1]))
    return None


def _http_date(value: str | None) -> date | None:
    try:
        return email.utils.parsedate_to_datetime(value).date() if value else None
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------------------
_MAP_COLS = {"code": "org_code", "name": "org_name", "icb code": "icb_code",
             "icb name": "icb_name", "region name": "region_label"}
_STP_COLS = {"org code": "org_code", "region": "region_label", "name": "org_name",
             "stp": "stp_name"}


def _norm(v) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else " ".join(str(v).split())


def _header_row(raw: pd.DataFrame, required: Iterable[str]) -> int:
    need = set(required)
    for i in range(min(len(raw), 50)):
        if need <= {_norm(v).lower() for v in raw.iloc[i]}:
            return i
    raise ValueError(f"no header row with {sorted(need)}")


def _table(raw: pd.DataFrame, cols: dict[str, str]) -> pd.DataFrame:
    """Rows under the header, first column of each wanted name, cells whitespace-collapsed."""
    h = _header_row(raw, cols)
    picked: dict[int, str] = {}
    for j, v in raw.iloc[h].items():
        name = cols.get(_norm(v).lower())
        if name and name not in picked.values():
            picked[j] = name
    df = raw.iloc[h + 1:][list(picked)].rename(columns=picked)
    df = df.apply(lambda s: s.map(_norm))
    df = df[df["org_code"] != ""].copy()
    df["org_code"] = df["org_code"].str.upper()
    return df.reset_index(drop=True)


def mapping_region(label) -> str:
    """'London Commissioning Region' -> 'LONDON'; the pre-2019 labels -> LEGACY."""
    if not _norm(label):
        return LEGACY
    return normalise_region(re.sub(r"commissioning region", "", str(label), flags=re.IGNORECASE))


def parse_system_mapping(content: bytes) -> tuple[pd.DataFrame, dict]:
    """One System Mapping File -> (org_code, org_name, icb_code, icb_name, region_label,
    region) and its title block (title, last_updated_text, last_updated)."""
    raw = pd.read_excel(io.BytesIO(content), sheet_name=0, header=None, dtype=object)
    df = _table(raw, _MAP_COLS)
    df["icb_code"] = df["icb_code"].str.upper()
    df = df.drop_duplicates(["org_code", "icb_code"])
    clash = df["org_code"].duplicated(keep=False)
    if clash.any():
        raise ValueError(f"codes mapped to two ICBs: {sorted(set(df.loc[clash, 'org_code']))}")
    df["region"] = df["region_label"].map(mapping_region)
    meta: dict[str, str] = {}
    for i in range(_header_row(raw, _MAP_COLS)):
        cells = [c for c in raw.iloc[i] if _norm(c)]
        if len(cells) >= 2 and _norm(cells[0]).endswith(":"):
            meta[_norm(cells[0]).rstrip(":").lower()] = cells[1]
    return df.reset_index(drop=True), {
        "title": _norm(meta.get("title")) or None,
        "last_updated_text": _norm(meta.get("last updated")) or None,
        "last_updated": parse_last_updated(meta.get("last updated"))}


def parse_stp_sheet(content: bytes) -> pd.DataFrame:
    """The legacy "STP Mapping" sheet of an attribution file -> org_code, org_name,
    stp_name, region_label. The side table of STP names and ONS codes is ignored."""
    xl = pd.ExcelFile(io.BytesIO(content))
    sheet = next((s for s in xl.sheet_names if "stp" in s.lower()), None)
    if sheet is None:
        return pd.DataFrame(columns=["org_code", "org_name", "stp_name", "region_label"])
    df = _table(xl.parse(sheet, header=None, dtype=object), _STP_COLS)
    df = df[df["stp_name"] != ""].drop_duplicates("org_code")
    return df[["org_code", "org_name", "stp_name", "region_label"]].reset_index(drop=True)


# --------------------------------------------------------------------------------------
# Fetching and the raw archive
# --------------------------------------------------------------------------------------
def discover_refs(financial_years: Iterable[str], session: requests.Session) -> list[MappingRef]:
    refs: list[MappingRef] = []
    for fy in financial_years:
        try:
            html = fetch_year_page(fy, session)
        except requests.HTTPError as e:
            log.warning("skipping %s: %s", fy, e)
            continue
        found = extract_mapping_refs(html, fy, base_url=year_page_url(fy))
        log.info("%s: %s", fy, ", ".join(r.filename for r in found) or "no mapping links")
        refs.extend(found)
    return refs


def probe_refs(session: requests.Session, candidates: Iterable[str] | None = None,
               delay: float = 0.1) -> list[MappingRef]:
    """Mapping files that exist on the server, whether or not a page links them."""
    found = []
    for url in candidates if candidates is not None else probe_candidates():
        try:
            resp = session.head(url, headers={"User-Agent": USER_AGENT}, timeout=30,
                                allow_redirects=False)
        except requests.RequestException as e:
            log.warning("probe %s: %s", url, e)
            continue
        if resp.status_code == 200:
            found.append(MappingRef(url, SYSTEM_MAPPING, discovered_via="url_probe"))
        time.sleep(delay)
    log.info("probe: %d mapping files on the server", len(found))
    return found


def _raw_relpath(url: str) -> str:
    m = _UPLOAD_RE.search(url)
    folder = f"{m['y']}-{m['m']}" if m else "other"
    return f"{folder}/{url.rsplit('/', 1)[-1].split('?', 1)[0]}"


def fetch_and_store(ref: MappingRef, session: requests.Session, raw_dir: Path = RAW_ICB_DIR,
                    manifest_path: Path = ICB_MANIFEST, seen: dict | None = None,
                    timeout: int = 60) -> dict:
    """Download one file into the immutable archive and append a manifest line.

    ``seen`` maps sha256 -> stored record; identical bytes are recorded, not stored twice.
    """
    seen = known_hashes(read_manifest(manifest_path)) if seen is None else seen
    rec: dict = {**asdict(ref), "filename": ref.filename,
                 "fetched_at": datetime.now(timezone.utc).isoformat()}
    try:
        resp = session.get(ref.url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as e:
        rec.update(stored=False, error=str(e))
        _append_manifest(rec, manifest_path)
        return rec
    content = resp.content
    lm = resp.headers.get("Last-Modified")
    published, why = _http_date(lm), "http_last_modified"
    if published is None:
        published, why = upload_month_estimate(ref.url), "upload_month_second_thursday"
    period = data_period(ref.url, published)
    digest = sha256_bytes(content)
    rec.update(period=period.strftime("%Y-%m") if period else None,
               financial_year=financial_year_of(period) if period else ref.linked_from,
               published=published, published_source=why, http_last_modified=lm,
               sha256=digest, bytes=len(content))
    if digest in seen:
        rec.update(stored=False, identical_to=seen[digest]["path"])
    else:
        out = raw_dir / _raw_relpath(ref.url)
        if out.exists():  # same URL, new bytes: never overwrite
            out = out.with_name(f"{out.stem}-{digest[:8]}{out.suffix}")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(content)
        rec.update(stored=True, path=out.relative_to(raw_dir).as_posix())
        seen[digest] = rec
    _append_manifest(rec, manifest_path)
    log.info("%s %s (%s)", ref.filename, "stored" if rec["stored"] else "duplicate", published)
    return rec


def load_ods_records(path: Path = ODS_RECORDS) -> dict[str, dict]:
    return json.loads(path.read_text()) if path.exists() else {}


_ODS_KEEP = ("Name", "OrgId", "Status", "LastChangeDate", "Date", "Succs")


def fetch_ods_records(codes: Iterable[str], records: dict[str, dict], session: requests.Session,
                      stop: set[str] = frozenset(), depth: int = 3,
                      delay: float = 0.2) -> dict[str, dict]:
    """ODS records for ``codes`` and, up to ``depth`` hops, their successors (unless in
    ``stop``). Only the fields the backfill reads are kept (name, status, dates,
    successions); a failed lookup is stored as ``{"_error": ...}`` so it is not retried."""
    todo = sorted({c for c in codes if c not in records})
    for _ in range(depth):
        nxt: set[str] = set()
        for code in todo:
            fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            try:
                org = fetch_org(code, session).get("Organisation", {})
            except requests.RequestException as e:
                records[code] = {"_error": str(e)[:200], "_fetched_at": fetched_at}
                continue
            finally:
                time.sleep(delay)
            records[code] = {"Organisation": {k: org[k] for k in _ODS_KEEP if k in org},
                             "_fetched_at": fetched_at}
            nxt |= {s.successor for s in successions_from_record(code, records[code])
                    if s.predecessor == code}
        todo = sorted(nxt - set(records) - set(stop))
        if not todo:
            break
    return records


def ods_successors(records: dict[str, dict]) -> dict[str, set[str]]:
    """predecessor -> successors, from both sides of every cached ODS record."""
    out: dict[str, set[str]] = {}
    for code, rec in records.items():
        if "_error" in rec:
            continue
        for s in successions_from_record(code, rec):
            out.setdefault(s.predecessor.upper(), set()).add(s.successor.upper())
    return out


# --------------------------------------------------------------------------------------
# Reference tables
# --------------------------------------------------------------------------------------
def load_versions(manifest: list[dict], raw_dir: Path = RAW_ICB_DIR) -> pd.DataFrame:
    """Every archived System Mapping File, one row per (version, provider)."""
    frames = []
    for rec in manifest:
        if rec.get("kind") != SYSTEM_MAPPING or not rec.get("stored"):
            continue
        df, meta = parse_system_mapping((raw_dir / rec["path"]).read_bytes())
        period = date.fromisoformat(rec["period"] + "-01")
        frames.append(df.assign(
            source=rec["path"], financial_year=rec["financial_year"], period=rec["period"],
            valid_from=valid_from(period).isoformat(), published=str(rec["published"]),
            last_updated=meta["last_updated"].isoformat() if meta["last_updated"] else None))
    if not frames:
        raise FileNotFoundError(f"no archived System Mapping File under {raw_dir}")
    cols = ["source", "financial_year", "period", "valid_from", "published", "last_updated",
            "org_code", "org_name", "icb_code", "icb_name", "region", "region_label"]
    return (pd.concat(frames, ignore_index=True)[cols]
              .sort_values([*_VERSION_ORDER, "org_code"]).reset_index(drop=True))


def select_version(history: pd.DataFrame, financial_year: str | None = None) -> pd.DataFrame:
    """The latest version overall, or the latest for one financial year's data."""
    h = history if financial_year is None else history[history["financial_year"] == financial_year]
    if h.empty:
        raise ValueError(f"no mapping version for {financial_year!r}")
    last = h.sort_values(_VERSION_ORDER)["source"].iloc[-1]
    return h[h["source"] == last].reset_index(drop=True)


def load_stp_legacy(manifest: list[dict], raw_dir: Path = RAW_ICB_DIR) -> pd.DataFrame:
    """The "STP Mapping" sheet of the most recently published attribution file."""
    recs = [r for r in manifest if r.get("kind") == TYPE3_ATTRIBUTION and r.get("stored")]
    if not recs:
        return pd.DataFrame(columns=["org_code", "org_name", "stp_name", "region_label", "source"])
    rec = max(recs, key=lambda r: (str(r["published"]), r["path"]))
    return parse_stp_sheet((raw_dir / rec["path"]).read_bytes()).assign(source=rec["path"])


def icb_crosswalk(history: pd.DataFrame, target: pd.DataFrame) -> dict[str, str | None]:
    """Any ICB code in ``history`` -> an ICB code of ``target``.

    An ICB still in the target maps to itself (ODS codes are stable). One merged away maps
    to the single target ICB holding all of its providers that are in both, or to None when
    they are split, as Hertfordshire and West Essex was in April 2026.
    """
    tgt = target.set_index("org_code")["icb_code"]
    out: dict[str, str | None] = {}
    for icb, grp in history.groupby("icb_code"):
        dest = {icb} if icb in set(tgt) else set(tgt.reindex(grp["org_code"].unique()).dropna())
        out[icb] = next(iter(dest)) if len(dest) == 1 else None
    return out


def stp_crosswalk(stp: pd.DataFrame, target: pd.DataFrame) -> dict[str, str | None]:
    """Legacy STP name -> the single target ICB holding every one of its providers that is
    in the target, else None (e.g. West Yorkshire: Harrogate went to Humber and North
    Yorkshire)."""
    tgt = target.set_index("org_code")["icb_code"]
    out: dict[str, str | None] = {}
    for name, grp in stp.groupby("stp_name"):
        dest = set(tgt.reindex(grp["org_code"]).dropna())
        out[name] = next(iter(dest)) if len(dest) == 1 else None
    return out


def backfill_codes(target: pd.DataFrame, history: pd.DataFrame, stp: pd.DataFrame,
                   ods_records: dict[str, dict] | None = None,
                   codes: Iterable[str] | None = None) -> pd.DataFrame:
    """Assign codes absent from ``target`` to one of its ICBs: ODS successor, else earlier
    NHS England mapping, else legacy STP (see the module docstring).

    ``codes`` defaults to every code in ``history``, ``stp`` and ``ods_records`` (the codes
    looked up there, not every predecessor ODS mentions: most predate the A&E data).
    Returns org_code, org_name, icb_code, icb_name, region, method, evidence, source for
    the codes that could be assigned unambiguously; the rest are left out.
    """
    ods = {k.upper(): v for k, v in (ods_records or {}).items() if "_error" not in v}
    successors = ods_successors(ods)
    tgt = target.drop_duplicates("org_code").set_index("org_code")
    icbs = tgt.drop_duplicates("icb_code").set_index("icb_code")[["icb_name", "region"]]
    xw, sx = icb_crosswalk(history, target), stp_crosswalk(stp, target)
    last = history.sort_values(_VERSION_ORDER).drop_duplicates("org_code", keep="last")
    last = last.set_index("org_code")
    stp_by = stp.set_index("org_code")
    names = {**{k: v.get("Organisation", {}).get("Name", "") for k, v in ods.items()},
             **stp_by["org_name"].to_dict(), **last["org_name"].to_dict()}
    universe = set(codes) if codes is not None else set(last.index) | set(stp_by.index) | set(ods)

    def direct(code: str) -> tuple[str, str, str, str] | None:
        if code in tgt.index:
            return tgt.at[code, "icb_code"], "current_mapping", code, ""
        if code in last.index and xw.get(last.at[code, "icb_code"]):
            old, src = last.at[code, "icb_code"], last.at[code, "source"]
            return xw[old], "earlier_mapping", f"ICB {old} in {src}", src
        if code in stp_by.index and sx.get(stp_by.at[code, "stp_name"]):
            s = stp_by.at[code, "stp_name"]
            return sx[s], "legacy_stp", f"STP {s}", stp_by.at[code, "source"]
        return None

    def via_successors(code: str) -> tuple[str, str, str, str] | None:
        frontier, seen = {code}, {code}
        for _ in range(5):
            frontier = {s for c in frontier for s in successors.get(c, ())} - seen
            seen |= frontier
            hits = {s: direct(s) for s in sorted(frontier)}
            hits = {s: h for s, h in hits.items() if h}
            if len({h[0] for h in hits.values()}) == 1:
                return (next(iter(hits.values()))[0], "ods_successor",
                        f"ODS successor {', '.join(hits)}", "ods_records.json")
            if hits or not frontier:  # disagreeing successors, or chain ended
                return None
        return None

    rows = []
    for code in sorted(universe - set(tgt.index)):
        # Successor first: after a merger the activity is reported under the successor's
        # code, so the predecessor's history must sit in the successor's ICB for the ICB
        # series to stay continuous (Burton, RJF: Staffordshire STP, merged into Derby).
        hit = via_successors(code) or direct(code)
        if hit:
            icb, method, evidence, source = hit
            rows.append({"org_code": code, "org_name": names.get(code, ""), "icb_code": icb,
                         "icb_name": icbs.at[icb, "icb_name"], "region": icbs.at[icb, "region"],
                         "method": method, "evidence": evidence, "source": source})
    cols = ["org_code", "org_name", "icb_code", "icb_name", "region", "method", "evidence",
            "source"]
    return pd.DataFrame(rows, columns=cols)


def _current_table(version: pd.DataFrame) -> pd.DataFrame:
    return version[["org_code", "org_name", "icb_code", "icb_name", "region", "source",
                    "valid_from", "published", "last_updated"]].sort_values("org_code")


def build(manifest_path: Path = ICB_MANIFEST, raw_dir: Path = RAW_ICB_DIR,
          reference_dir: Path = REFERENCE_DIR, ods_path: Path = ODS_RECORDS) -> dict:
    """Rebuild every reference table from the archive (no network)."""
    manifest = read_manifest(manifest_path)
    history = load_versions(manifest, raw_dir)
    current = select_version(history)
    stp = load_stp_legacy(manifest, raw_dir)
    fill = backfill_codes(current, history, stp, load_ods_records(ods_path))
    reference_dir.mkdir(parents=True, exist_ok=True)
    _current_table(current).to_csv(reference_dir / CURRENT_CSV, index=False)
    history.to_csv(reference_dir / HISTORY_CSV, index=False)
    fill.to_csv(reference_dir / BACKFILL_CSV, index=False)
    stp.to_csv(reference_dir / STP_CSV, index=False)
    summary = {"versions": history["source"].nunique(), "current": current["source"].iloc[0],
               "providers": len(current), "icbs": current["icb_code"].nunique(),
               "backfilled": len(fill), **fill["method"].value_counts().to_dict()}
    log.info("build: %s", summary)
    return summary


def load_reference(financial_year: str | None = None, backfill: bool = True,
                   reference_dir: Path = REFERENCE_DIR, ods_path: Path = ODS_RECORDS
                   ) -> pd.DataFrame:
    """org_code, org_name, icb_code, icb_name, region, method for one mapping version.

    ``financial_year=None`` reads the committed current mapping (and its backfill). A year
    such as ``"2025-26"`` selects the latest version for that year's data from the history
    table, the way to get the 42-ICB structure, and derives its backfill on the fly.
    """
    read = {"dtype": str, "keep_default_na": False}
    if financial_year is None:
        m = pd.read_csv(reference_dir / CURRENT_CSV, **read).assign(method="nhs_england_mapping")
        fill = pd.read_csv(reference_dir / BACKFILL_CSV, **read) if backfill else None
    else:
        history = pd.read_csv(reference_dir / HISTORY_CSV, **read)
        m = select_version(history, financial_year).assign(method="nhs_england_mapping")
        fill = backfill_codes(m, history, pd.read_csv(reference_dir / STP_CSV, **read),
                              load_ods_records(ods_path)) if backfill else None
    cols = ["org_code", "org_name", "icb_code", "icb_name", "region", "method"]
    return pd.concat([m[cols], fill[cols]] if fill is not None else [m[cols]], ignore_index=True)


# --------------------------------------------------------------------------------------
# Checks against the monthly data
# --------------------------------------------------------------------------------------
def check(data_path: Path, reference_dir: Path = REFERENCE_DIR) -> dict[str, pd.DataFrame]:
    """Coverage, per-ICB counts, region agreement and the adm_via_ae ICB panel."""
    from nhs_ae.evaluate.asof import load_truth, load_vintages  # diagnostic only
    from nhs_ae.features.hierarchy import UNMAPPED, current_icb_map, current_region_map

    d = pd.read_parquet(data_path, columns=["period", "org_code", "parent_org", "org_name",
                                            "metric", "value", "is_total"])
    d = d[~d["is_total"] & d["period"].notna()].copy()
    d["period"] = pd.to_datetime(d["period"])
    ref = load_reference(reference_dir=reference_dir)
    nhs = ref[ref["method"] == "nhs_england_mapping"]
    last = d["period"].max()
    recent = d[d["period"] > last - pd.DateOffset(months=12)]
    att = recent[recent["metric"].isin(["att_type1", "att_type2", "att_other"])]
    by_org = att.pivot_table(index="org_code", columns="metric", values="value", aggfunc="sum")
    active = by_org[by_org.sum(axis=1) > 0].fillna(0.0)
    names = d.sort_values("period").drop_duplicates("org_code", keep="last")
    names = names.set_index("org_code")["org_name"]
    icb, icb_nhs = current_icb_map(d, mapping=ref), current_icb_map(d, mapping=nhs)
    out: dict[str, pd.DataFrame] = {}
    method = ref.drop_duplicates("org_code").set_index("org_code")["method"]
    a = active.assign(icb=icb.reindex(active.index), icb_nhs=icb_nhs.reindex(active.index),
                      name=names.reindex(active.index),
                      method=method.reindex(active.index.str.upper()).to_numpy())
    out["active"] = a
    out["unmapped_active"] = a[a["icb_nhs"] == UNMAPPED][["name", "icb", "method", "att_type1",
                                                          "att_type2", "att_other"]]
    per = a[a["icb"] != UNMAPPED].groupby("icb").agg(
        providers=("name", "size"), type1=("att_type1", lambda s: int((s > 0).sum())))
    out["providers_per_icb"] = per
    rm = current_region_map(d)
    reg = nhs.set_index("org_code")["region"]
    both = rm.index.intersection(reg.index)
    dis = pd.DataFrame({"data_region": rm[both], "mapping_region": reg[both]})
    dis = dis[dis["data_region"] != dis["mapping_region"]]
    out["region_disagreements"] = dis.assign(name=names.reindex(dis.index).to_numpy())
    v = load_vintages(data_path)
    panel = load_truth(v, icb_map=icb).panel("adm_via_ae", "icb")
    out["icb_panel"] = panel
    no_bf = load_truth(v, icb_map=icb_nhs).panel("adm_via_ae", "icb")
    tot = no_bf.sum(axis=1)
    out["unmapped_share"] = pd.DataFrame({
        "without_backfill": no_bf.get(UNMAPPED, 0.0) / tot,
        "with_backfill": panel.get(UNMAPPED, 0.0) / panel.sum(axis=1)}).groupby(
        lambda p: p.year).mean()
    return out


def _print_check(out: dict[str, pd.DataFrame]) -> None:
    per, ua, a = out["providers_per_icb"], out["unmapped_active"], out["active"]
    print(f"providers with attendances in the last 12 months: {len(a)}; in the NHS England "
          f"file: {len(a) - len(ua)}; after backfill: {int((a['icb'] != 'UNMAPPED').sum())}; "
          f"ICBs covered: {len(per)}")
    print(ua.to_string(), "\n")
    print("providers per ICB: min/median/max =",
          per["providers"].min(), per["providers"].median(), per["providers"].max())
    print("ICBs with no Type 1 department:", list(per.index[per["type1"] == 0]) or "none", "\n")
    print("region disagreements (data parent_org vs mapping):")
    print(out["region_disagreements"].to_string() or "none", "\n")
    p = out["icb_panel"]
    real = p.drop(columns="UNMAPPED", errors="ignore")
    small = (real < 0.5 * real.rolling(12, min_periods=6).median().shift(1))
    print(f"ICB panel adm_via_ae: {real.shape[1]} ICB series (+UNMAPPED: "
          f"{'UNMAPPED' in p.columns}), {p.index.min():%Y-%m}..{p.index.max():%Y-%m}, "
          f"{int(real.isna().sum().sum())} NaN ICB-months, "
          f"{int(small.sum().sum())} below half the prior-12-month median")
    print(small.stack().loc[lambda s: s].index.tolist()[:40])
    print("\nshare of adm_via_ae in the UNMAPPED bucket, by year:")
    print(out["unmapped_share"].round(4).to_string())


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------
def _data_codes(path: Path) -> set[str]:
    if not path.exists():
        log.warning("%s not found: ODS lookups limited to codes in the mapping files", path)
        return set()
    d = pd.read_parquet(path, columns=["org_code", "is_total"])
    return set(d.loc[~d["is_total"], "org_code"].dropna().str.strip().str.upper())


def cmd_run(args: argparse.Namespace) -> int:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    refs = discover_refs(args.years, session)
    if args.probe:
        refs += probe_refs(session)
    manifest = read_manifest(ICB_MANIFEST)
    done = {r["url"] for r in manifest if not r.get("error")}
    seen = known_hashes(manifest)
    queued: set[str] = set()
    for ref in refs:
        if ref.url in queued or (ref.url in done and not args.refetch):
            continue
        queued.add(ref.url)
        fetch_and_store(ref, session, seen=seen)
    if not args.no_ods:
        manifest = read_manifest(ICB_MANIFEST)
        history = load_versions(manifest)
        current = select_version(history)
        stp = load_stp_legacy(manifest)
        codes = (_data_codes(Path(args.codes_from)) | set(history["org_code"])
                 | set(stp["org_code"])) - set(current["org_code"])
        records = fetch_ods_records(codes, load_ods_records(), session,
                                    stop=set(current["org_code"]))
        ODS_RECORDS.write_text(json.dumps(dict(sorted(records.items())), indent=1))
        log.info("ODS: %d records cached", len(records))
    return cmd_build(args)


def cmd_build(args: argparse.Namespace) -> int:
    print(json.dumps(build(), default=str))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    pd.set_option("display.width", 200)
    pd.set_option("display.max_rows", 200)
    _print_check(check(Path(args.data)))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m nhs_ae.ingest.icb_mapping",
                                     description=__doc__.split("\n\n")[0])
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run", help="fetch new mapping/attribution files, ODS records; build")
    p.add_argument("--years", nargs="+", default=list(FINANCIAL_YEARS))
    p.add_argument("--probe", action="store_true",
                   help="also HEAD-probe upload paths for superseded mapping versions")
    p.add_argument("--refetch", action="store_true", help="re-download URLs already archived")
    p.add_argument("--no-ods", action="store_true", help="skip ODS successor lookups")
    p.add_argument("--codes-from", default=str(PROCESSED_DIR / "ae_monthly_latest.parquet"),
                   help="parquet whose provider codes need an ICB (default: latest view)")
    p.set_defaults(func=cmd_run)
    p = sub.add_parser("build", help="rebuild data/reference tables from the archive")
    p.set_defaults(func=cmd_build)
    p = sub.add_parser("check", help="coverage and ICB-panel checks against monthly data")
    p.add_argument("--data", default=str(PROCESSED_DIR / "ae_monthly_latest.parquet"))
    p.set_defaults(func=cmd_check)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
