"""Acute discharge situation report: patients no longer meeting the criteria to reside.

Source
------
NHS England, *Acute discharge situation report* (under *Discharge Delays*), one workbook
per month:
``statistics/statistical-work-areas/discharge-delays/acute-discharge-situation-report/``.
Until late 2024 the same files were listed on a page titled *Discharge delays (Acute)*,
``statistics/statistical-work-areas/discharge-delays-acute-data/``, which is still live
but frozen and links some versions the new page does not; both are read. Provider-level
files start with **April 2022** data (first published 11 May 2022, per the file's cover
sheet). The national-only time series goes back to April 2021, but there is no
trust-level file before April 2022. Scope: acute trusts with a type 1 A&E department,
adult inpatients (18+, including critical care; excluding paediatrics, maternity and
deceased patients). Mental health and specialist trusts (children's, women's) are out.

What is measured
----------------
Table 2 of each workbook gives, per trust and per day, the number of patients who no
longer meet the criteria to reside (NCtR), how many of those were discharged that day,
and how many remained in hospital at the end of the day. This module averages each over
the days of the month::

    nctr_avg        mean daily number of patients no longer meeting the criteria to reside
    remaining_avg   mean daily number of those not discharged by the end of the day
    discharged_avg  mean daily number of those discharged
    days_reported   days with a non-missing NCtR value ('-' in the file = not submitted)

The published England row is kept as an ``is_total`` row. Trusts sum to it exactly in
months when every trust reported every day. Otherwise two things separate them: England
counts a trust's missing day as zero while the trust averages here skip it (the larger
effect: up to 5% of NCtR in April to June 2022, when 20 to 120 trusts had gaps), and
trust-level figures exclude patients discharged to a hospice, a disclosure rule stated
in each file (about 12 patients a day nationally in 2022 to 2024, none by 2026). On 19
June 2022 England shows 0 where every trust shows '-' (a collection failure); zeros on
the England row are treated as missing, which reproduces NHS England's own time series.
The latest England rows match that series in 52 of 53 months (February 2024 is 0.1% low).
The workbooks carry no bed-occupancy figure; KH03 (``kh03.py``) is the source for that.

Definitional breaks (``collection``, ``spec_change_in_month``)
--------------------------------------------------------------
The collection has had three technical specifications. ``collection`` names the one in
force on the first day of the month; ``spec_change_in_month`` marks May 2022 and May
2024, whose last five days were collected under the next one.

======================================  ===========  ==========================================
collection                              in force     source of the date
======================================  ===========  ==========================================
``covid_eprr_discharge_sitrep``         2020-04-08   COVID-19 EPRR acute daily discharge sitrep
                                                     "commenced on 8 April 2020" (ADSR page)
``adsr_spec_2022``                      2022-05-27   "technical specification that was
                                                     introduced on 27 May 2022" (spec page)
``adsr_spec_2024``                      2024-05-27   "Data definitions ... on discharge
                                                     pathways and delay reasons changed from
                                                     27th May 2024" (ADSR page)
======================================  ===========  ==========================================

The 2024 change is stated for discharge pathways and delay reasons, not the NCtR count,
and NHS England's two national time series (labelled pre- and post-May 2024 change) carry
identical daily NCtR, discharged and remaining counts over their overlap (checked on the
April 2021 to August 2025 file against the April 2021 to August 2026 file), so the three
metrics here are treated as continuous; the column is there so a user can decide
otherwise.

Layouts and versions
--------------------
* The first publications (April 2022 to May 2023 as first issued) split discharges into
  "by 17:00" and "between 17:01 and 23:59", four columns per day, which are summed; they
  put data-item codes and repeated dates between the date row and the measure names,
  and label the national row "ENGLAND (All Acute Trusts)".
* The re-issued 2022-23 files (uploaded October 2023, on the page by 6 November; April
  to June 2022 again on 14 December 2023) and every file since have
  three columns per day, an ICB section above the trust section, and "ENGLAND (Type 1
  Trusts)"; the workbook grew from three tables to five, then seven (from September
  2025; April 2025 had nine). October 2024 has no cover sheet at all. Table 2's shape is
  the same throughout: a row of dates, a row of measure names, then ``Region | Org Code |
  Org Name`` rows. Columns are assigned by (date on the left, measure name), so the
  number of columns per day does not matter.
* Months are first published 8 to 16 days after month end: the second Thursday of the
  following month in 47 of 52 dated months, the third Thursday in four, and a Wednesday
  for the very first (11 May 2022). Many were re-issued, some several times (``v2``,
  ``v3``, ``-revised``, and a bulk re-upload of August 2025 to February 2026 in April
  2026, identical in values and so dropped). The cover sheet states ``Published:``
  (first publication of the month) and ``Revised:``; dating follows
  ``external.resolve_published``. The autumn 2023 re-issue changed NCtR for nearly every
  trust in April to June 2022 and for up to 13 trusts a month from July 2022 to May 2023
  (national NCtR moved by up to 2.2%, March 2023), and changed the discharged and
  remaining counts of about 70 trusts a month; later revisions are small. The original versions of April and May 2022, June to
  August 2023 and June 2024 were not found, and October 2024 has no stated date, so
  those months become visible later in strict as-of use than they really did. Each
  ``build`` writes ``discharge_versions.csv`` next to the parquet.
* A CSV twin (long format, ~9 MB a month) exists from April 2024. It carries the same
  numbers as the workbook and is not archived.

Output
------
``data/processed/discharge.parquet``, one row per trust (plus England, ``is_total``) per
month per distinct version: ``period, org_code, org_name, region, is_total, nctr_avg,
remaining_avg, discharged_avg, days_reported, days_in_period, collection,
spec_change_in_month, published, published_source, first_published, version,
n_versions, is_latest, layout, source_file, sha256, url``. ``as_of(df, when)`` gives the
version current on a date.

Usage::

    python -m nhs_ae.ingest.discharge run      # discover, fetch, archive, build
    python -m nhs_ae.ingest.discharge build    # rebuild the parquet from the archive
"""

from __future__ import annotations

import argparse
import io
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from urllib.parse import unquote, urljoin

import numpy as np
import pandas as pd
from bs4 import BeautifulSoup

from nhs_ae.config import DATA_DIR, MONTHS, PROCESSED_DIR, PROJECT_ROOT
from nhs_ae.ingest import external
from nhs_ae.ingest.download import read_manifest
from nhs_ae.ingest.external import Link, as_date, parse_date

log = logging.getLogger(__name__)

PAGE_URL = ("https://www.england.nhs.uk/statistics/statistical-work-areas/discharge-delays/"
            "acute-discharge-situation-report/")
OLD_PAGE_URL = ("https://www.england.nhs.uk/statistics/statistical-work-areas/"
                "discharge-delays-acute-data/")
RAW_DIR = DATA_DIR / "external" / "discharge" / "raw"
MANIFEST_PATH = RAW_DIR / "manifest.jsonl"
OUT_PATH = PROCESSED_DIR / "discharge.parquet"
FIRST_PERIOD = date(2022, 4, 1)  # first provider-level monthly file
INDEX_REGEX = r".*[Dd]ischarge-sitrep-monthly.*\.xlsx$"
ODS_RE = re.compile(r"^[A-Z0-9]{3,5}$")

# (first day in force, collection name) — see the module docstring for sources.
SPECIFICATIONS: tuple[tuple[date, str], ...] = (
    (date(2020, 4, 8), "covid_eprr_discharge_sitrep"),
    (date(2022, 5, 27), "adsr_spec_2022"),
    (date(2024, 5, 27), "adsr_spec_2024"),
)

_MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))
_FILE_MONTH_RE = re.compile(rf"(?P<month>{_MONTH_ALT})[-_ ]?(?P<year>20\d\d)", re.IGNORECASE)
_EXCLUDE = ("csv", "timeseries", "time-series", "community", "ready-date", "ready date")
VALUE_COLS = ("nctr_avg", "remaining_avg", "discharged_avg", "days_reported")


def collection_for(period: date) -> tuple[str, bool]:
    """(specification in force on the month's first day, whether another began mid-month)."""
    name = ""
    for start, spec in SPECIFICATIONS:
        if start <= period:
            name = spec
    nxt = external.month_end(period)
    changed = any(period < start <= nxt for start, _ in SPECIFICATIONS)
    return name, changed


# --------------------------------------------------------------------------------------
# Links
# --------------------------------------------------------------------------------------
def parse_link(href: str, text: str = "", base_url: str = "") -> Link | None:
    """A ``Link`` if the anchor is a monthly provider-level discharge workbook (.xlsx)."""
    if not href:
        return None
    url = urljoin(base_url or PAGE_URL, href.strip())
    filename = unquote(url.rsplit("/", 1)[-1].split("?", 1)[0])
    low = filename.lower()
    if not low.endswith(".xlsx") or "discharge-sitrep-monthly" not in low:
        return None
    if any(k in low for k in _EXCLUDE):
        return None
    m = _FILE_MONTH_RE.search(filename) or _FILE_MONTH_RE.search(text)
    if not m:
        return None
    period = date(int(m["year"]), MONTHS[m["month"].lower()], 1)
    if period < FIRST_PERIOD:
        return None
    return Link(url=url, filename=filename, period=period, label=" ".join(text.split()))


def extract_links(html: str, base_url: str = PAGE_URL) -> list[Link]:
    soup = BeautifulSoup(html, "lxml")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        link = parse_link(a["href"], a.get_text(" ", strip=True), base_url)
        if link and link.url not in seen:
            seen.add(link.url)
            out.append(link)
    return out


def link_from_url(url: str) -> Link | None:
    return parse_link(url, "", url)


# --------------------------------------------------------------------------------------
# Workbook reader
# --------------------------------------------------------------------------------------
@dataclass
class DischargeFile:
    period_start: date | None = None
    period_end: date | None = None
    published: date | None = None
    revised: date | None = None
    status: str = ""
    layout: str = ""
    rows: pd.DataFrame = field(default_factory=pd.DataFrame)
    unmapped: list[str] = field(default_factory=list)


def _norm(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return re.sub(r"[^a-z0-9]+", " ", str(v).strip().lower()).strip()


def _as_day(v) -> date | None:
    if isinstance(v, (datetime, pd.Timestamp)) and not pd.isna(v):
        return pd.Timestamp(v).date()
    return None


def classify_measure(header: str) -> str | None:
    """Table 2 sub-header -> measure. Order matters: 'remaining ... no longer meet' is
    the remaining count, not NCtR."""
    n = _norm(header)
    if not n:
        return None
    if "remaining in hospital" in n:
        return "remaining"
    if "no longer meet" in n:
        return "nctr"
    if "discharged by 17" in n:
        return "discharged_by_17"
    if "discharged between 17" in n or "17 01" in n:
        return "discharged_after_17"
    if "discharged" in n:
        return "discharged"
    return None


def _sheet(xl: pd.ExcelFile, pattern: str) -> str | None:
    rx = re.compile(pattern, re.IGNORECASE)
    return next((s for s in xl.sheet_names if rx.match(s.strip())), None)


def _cover(xl: pd.ExcelFile) -> dict:
    name = _sheet(xl, r"cover")
    if name is None:
        return {}
    grid = xl.parse(name, header=None, dtype=object)
    out: dict = {}
    for i in range(min(len(grid), 20)):
        row = grid.iloc[i].tolist()
        for j, v in enumerate(row):
            key = _norm(v)
            if key in {"period", "published", "revised", "status"} and str(v).strip().endswith(":"):
                vals = [x for x in row[j + 1:] if not (x is None or (isinstance(x, float)
                                                                        and pd.isna(x)))]
                out[key] = vals
                break
    return out


def read_discharge(src: Path | bytes) -> DischargeFile:
    """Parse one monthly workbook into per-trust monthly averages (any layout)."""
    data = src if isinstance(src, bytes) else Path(src).read_bytes()
    xl = pd.ExcelFile(io.BytesIO(data))
    f = DischargeFile()
    cov = _cover(xl)
    dates = [d for d in (parse_date(x) for x in cov.get("period", [])) if d]
    if dates:
        f.period_start, f.period_end = min(dates), max(dates)
    f.published = parse_date((cov.get("published") or [None])[0])
    f.revised = parse_date((cov.get("revised") or [None])[0])
    f.status = str((cov.get("status") or [""])[0])

    t2 = _sheet(xl, r"table\s*2$")
    if t2 is None:
        raise ValueError("no 'Table 2' sheet")
    grid = xl.parse(t2, header=None, dtype=object)
    hdr = next((i for i in range(len(grid))
                if "org code" in {_norm(v) for v in grid.iloc[i].tolist()}), None)
    if hdr is None:
        raise ValueError("Table 2 has no 'Org Code' header row")
    n_dates = [sum(_as_day(v) is not None for v in grid.iloc[i].tolist()) for i in range(hdr)]
    if not n_dates or max(n_dates) == 0:
        raise ValueError("Table 2 has no row of dates")
    date_row = n_dates.index(max(n_dates))  # the first 2022 files repeat dates on every column
    # The measure names are on the row below the dates with the most recognisable cells;
    # the first 2022 files put data-item codes (DIS002_TOTAL) and repeated dates between.
    meas_row = max(range(date_row + 1, hdr), key=lambda i: sum(
        classify_measure(v) is not None for v in grid.iloc[i].tolist()), default=date_row + 1)
    header = [_norm(v) for v in grid.iloc[hdr].tolist()]
    c_code, c_name = header.index("org code"), header.index("org name")
    c_region = header.index("region") if "region" in header else None

    day_of_col: dict[int, date] = {}
    current: date | None = None
    for j, v in enumerate(grid.iloc[date_row].tolist()):
        d = _as_day(v)
        current = d or current
        if current is not None:
            day_of_col[j] = current
    colmap: dict[int, tuple[date, str]] = {}
    for j, v in enumerate(grid.iloc[meas_row].tolist()):
        if j not in day_of_col:
            continue
        m = classify_measure(v)
        if m:
            colmap[j] = (day_of_col[j], m)
        elif _norm(v) and _norm(v) not in f.unmapped:
            f.unmapped.append(_norm(v))
    measures = sorted({m for _, m in colmap.values()})
    if "nctr" not in measures:
        raise ValueError(f"Table 2 has no NCtR columns (found {measures})")
    days = sorted({d for d, _ in colmap.values()})

    records = []
    for i in range(meas_row + 1, len(grid)):
        if i == hdr:
            continue
        row = grid.iloc[i].tolist()
        code = row[c_code].strip().upper() if isinstance(row[c_code], str) else ""
        name_cells = [str(x).strip() for x in row[:c_name + 1] if isinstance(x, str)]
        is_total = i < hdr and any(c.upper().startswith("ENGLAND") for c in name_cells)
        if i > hdr and not ODS_RE.match(code):
            continue
        if i < hdr and not is_total:
            continue
        per: dict[str, dict[date, float]] = {}
        for j, (d, m) in colmap.items():
            val = pd.to_numeric(row[j], errors="coerce")
            per.setdefault(m, {})[d] = float(val) if pd.notna(val) else np.nan
        records.append(_summarise(per, days, {
            "org_code": "ENG" if is_total else code,
            "org_name": next((c for c in name_cells if c.upper().startswith("ENGLAND")),
                             "ENGLAND") if is_total else str(row[c_name]).strip(),
            "region": "" if is_total or c_region is None else str(row[c_region]).strip(),
            "is_total": is_total}))
    rows = pd.DataFrame.from_records(records)
    if rows.empty or (~rows["is_total"]).sum() == 0:
        raise ValueError("no trust rows in Table 2")
    f.rows = rows
    n_tables = sum(bool(re.match(r"table", s.strip(), re.IGNORECASE)) for s in xl.sheet_names)
    split = "split_discharges" if "discharged_by_17" in measures else "single_discharges"
    f.layout = f"t2_{len(measures)}col|{split}|{n_tables}tables"
    if f.period_start is None and days:
        f.period_start, f.period_end = days[0], days[-1]
    return f


def _summarise(per: dict[str, dict[date, float]], days: list[date], ids: dict) -> dict:
    def series(m: str) -> np.ndarray:
        return np.array([per.get(m, {}).get(d, np.nan) for d in days], dtype=float)

    nctr, remaining = series("nctr"), series("remaining")
    if "discharged" in per:
        disch = series("discharged")
    else:
        early, late = series("discharged_by_17"), series("discharged_after_17")
        both_nan = np.isnan(early) & np.isnan(late)
        disch = np.where(both_nan, np.nan, np.nan_to_num(early) + np.nan_to_num(late))

    if ids["is_total"]:
        # A national count of zero is a lost day, not a quiet one: England shows 0 on
        # 19 June 2022 (a collection failure; trusts show '-' and NHS England's own time
        # series has no value), so zeros on the England row are treated as missing.
        nctr, remaining, disch = (np.where(a == 0, np.nan, a) for a in (nctr, remaining, disch))

    def mean(a: np.ndarray) -> float:
        return float(np.nanmean(a)) if np.isfinite(a).any() else np.nan

    return {**ids, "nctr_avg": mean(nctr), "remaining_avg": mean(remaining),
            "discharged_avg": mean(disch), "days_reported": int(np.isfinite(nctr).sum()),
            "days_in_period": len(days)}


def read_dates(content: bytes) -> tuple[date | None, date | None]:
    xl = pd.ExcelFile(io.BytesIO(content))
    cov = _cover(xl)
    return (parse_date((cov.get("published") or [None])[0]),
            parse_date((cov.get("revised") or [None])[0]))


# --------------------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------------------
def build(manifest_path: Path = MANIFEST_PATH, project_root: Path = PROJECT_ROOT,
          out_path: Path | None = OUT_PATH) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Parse every archived version into the tidy table. Returns (table, failures)."""
    archived = external.manifest_versions(read_manifest(manifest_path))
    by_period: dict[date, list[tuple[dict, pd.DataFrame]]] = {}
    failures = []
    for v in archived:
        try:
            f = read_discharge(project_root / v["path"])
        except Exception as e:  # noqa: BLE001 – recorded, never silently dropped
            failures.append({"source_file": Path(v["path"]).name, "url": v["url"],
                             "error": f"{type(e).__name__}: {e}"})
            continue
        period = date(f.period_start.year, f.period_start.month, 1) if f.period_start \
            else as_date(v["period"])
        if as_date(v["period"]) and period != as_date(v["period"]):
            log.warning("%s: link says %s, file says %s; using the file", v["filename"],
                        v["period"], period)
        if f.unmapped:
            log.info("%s: Table 2 columns not used: %s", v["filename"], f.unmapped)
        by_period.setdefault(period, []).append(({**v, "_file": f}, f.rows))
    failures = pd.DataFrame(failures, columns=["source_file", "url", "error"])
    if not by_period:
        return pd.DataFrame(), failures

    frames = []
    for period, group in sorted(by_period.items()):
        first_pub = external.first_publication(
            [v["_file"].published for v, _ in group], [v.get("published") for v, _ in group])
        kept = external.drop_reuploads(group, VALUE_COLS, period.strftime("%Y-%m"))
        coll, changed = collection_for(period)
        for n, (v, rows) in enumerate(kept, start=1):
            frames.append(rows.assign(
                period=pd.Timestamp(period), collection=coll, spec_change_in_month=changed,
                published=pd.Timestamp(v["published"]) if v.get("published") else pd.NaT,
                published_source=v.get("published_source", ""),
                first_published=pd.Timestamp(first_pub) if first_pub else pd.NaT,
                version=n, n_versions=len(kept), is_latest=n == len(kept),
                layout=v["_file"].layout, source_file=Path(v["path"]).name,
                sha256=v["sha256"], url=v["url"]))
    df = pd.concat(frames, ignore_index=True)
    order = ["period", "org_code", "org_name", "region", "is_total", "nctr_avg",
             "remaining_avg", "discharged_avg", "days_reported", "days_in_period",
             "collection", "spec_change_in_month", "published", "published_source",
             "first_published", "version", "n_versions", "is_latest", "layout",
             "source_file", "sha256", "url"]
    df = df[order].sort_values(["period", "version", "is_total", "org_code"],
                               ascending=[True, True, False, True]).reset_index(drop=True)
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(out_path, index=False)
        failures.to_csv(out_path.with_name("discharge_parse_failures.csv"), index=False)
        versions(df).to_csv(out_path.with_name("discharge_versions.csv"), index=False)
        log.info("wrote %d rows, %d months, %d versions to %s (%d files failed)", len(df),
                 df["period"].nunique(), df["source_file"].nunique(), out_path, len(failures))
    return df, failures


def as_of(df: pd.DataFrame, when, use_first_published: bool = False) -> pd.DataFrame:
    """The version of every month that was current on ``when`` (see ``external.as_of``)."""
    return external.as_of(df, when, "period", use_first_published)


def versions(df: pd.DataFrame) -> pd.DataFrame:
    """Per-version publication dates, lags and revisions (``national`` = England mean
    daily NCtR), written next to the parquet as ``discharge_versions.csv``."""
    out = external.versions_table(df, "period", df["period"] + pd.offsets.MonthEnd(0),
                                  VALUE_COLS, "nctr_avg")
    return out.rename(columns={"national": "england_nctr_avg",
                               "national_change": "england_nctr_avg_change"})


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------
def source_spec() -> external.SourceSpec:
    return external.SourceSpec(
        name="discharge", pages=(PAGE_URL, OLD_PAGE_URL), raw_dir=RAW_DIR,
        manifest_path=MANIFEST_PATH, project_root=PROJECT_ROOT, extract_links=extract_links,
        link_from_url=link_from_url, read_dates=read_dates,
        index_years=tuple(range(2022, external.today().year + 1)), index_regex=INDEX_REGEX)


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-v", "--verbose", action="store_true")
    ap = argparse.ArgumentParser(prog="python -m nhs_ae.ingest.discharge",
                                 description="Acute discharge sitrep: archive and tidy table.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", parents=[common],
                         help="discover, fetch and archive every version, then build")
    run.add_argument("--no-history", action="store_true",
                     help="live pages only; skip the Internet Archive")
    sub.add_parser("build", parents=[common],
                   help="rebuild the parquet from the archive, no network")
    args = ap.parse_args(argv)
    level = logging.INFO if args.verbose or args.cmd == "run" else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")
    if args.cmd == "run":
        summary = external.collect(source_spec(), history=not args.no_history)
        log.info("discharge collect: %s", summary)
    df, failures = build()
    if df.empty:
        log.error("nothing parsed; is %s populated?", MANIFEST_PATH)
        return 1
    print(f"discharge: {df['period'].nunique()} months, {df['source_file'].nunique()} "
          f"versions, {len(failures)} unparsed files -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
