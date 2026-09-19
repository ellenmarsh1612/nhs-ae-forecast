"""KH03: general & acute beds available and occupied overnight, per trust per quarter.

Source
------
NHS England, *Bed Availability and Occupancy Data – Overnight* (the KH03 collection),
one workbook per quarter on
``statistics/statistical-work-areas/bed-availability-and-occupancy/bed-data-overnight/``.
Trust-level quarterly files exist from 2010-11 Q1; before that KH03 was an annual return
by ward classification (the page's 2000-01 to 2009-10 files, ignored here). Figures are
*average daily* beds: available and occupied bed-days over the quarter divided by the
days in the quarter, so ``ga_occupied / ga_available`` is the quarter's mean occupancy.

The collection was **not** paused for COVID. NHS England's list of statistics paused in
2020 carried KH03 Q4 2019-20 in error and later removed it (footnote to section 5 of
*COVID-19 and the production of statistics*, 7 September 2021 update); the Q4 2019-20
workbook states ``Published: 21st May 2020``. For 2020-21 the page warns that beds were
reorganised to separate COVID and non-COVID patients, so occupancy is not comparable
with earlier years and pressure starts at lower occupancy.

Layouts
-------
One reader handles all of them by locating the header row (the row with ``Org Code`` and
``General & Acute``) and the group row above it (``Available`` / ``Occupied`` /
``% Occupied``), then assigning each ``General & Acute`` column to the group on its left.

* 2010-11 to 2012-13 (``.xls``): title block in column A (``Title:``, ``Source:``,
  ``Status:``), a single status line ``Published 18 November 2010 and revised ...``;
  parent column ``SHA Code``; PCTs appear alongside trusts.
* 2013-14 onward: a blank column A, a title block with separate ``Published:`` and
  ``Revised:`` rows (dates as text, ``20th August 2026``, or as Excel dates), a
  ``Provider Level Data`` row, then the two header rows. Parent column ``AT Code`` (area
  teams, 2013-14 to 2015-16) then ``Region Code``; ``Period`` became ``Period End`` and
  ``Learning Disabilities`` became ``Learning Disability``; from 2023-24 a ``Data
  Quality`` sheet comes first and lists trusts whose return was estimated.
* Occupancy is a fraction; ``-`` where a trust has no beds of that type. Published
  occupancy equals ``ga_occupied / ga_available`` and the England row equals the sum of
  the trust rows, in every file.
* The title is checked: ``Beds-Open-Overnight-Web_File-Q4-2023-24-Final-1.xlsx`` (June
  2024) is a *day-only* table under an overnight name and is rejected, not parsed.
* A missing return is not always a missing row. Five acute trusts appear in 2025-26 Q4
  with zero beds of every kind (James Paget, Dudley, Birmingham Women's and Children's,
  Morecambe Bay, East and North Hertfordshire), and Countess of Chester shows 498 G&A
  beds and none occupied in 2026-27 Q1. The published England row includes these
  zeros. Values are kept as published; treat zero G&A beds, or zero occupancy, at an
  acute trust as missing.

Publication dates and revisions
-------------------------------
Quarters are first published 49 to 58 days after quarter end (Q1 in August, Q2 in
November, Q3 in February, Q4 in May; every quarter since 2012-13) and most are revised
once to three times, at later November or May publications. The page links only the
latest version of each quarter; earlier versions are recovered through
``external.collect`` (Archive page captures and upload-folder index). NHS England still
served every URL the page had ever linked (September 2026), except four 2011-12 links to
the retired ``transparency.dh.gov.uk``. From 2012-13 Q4 the original version of every
quarter was found except 2013-14 Q3, 2016-17 Q3, 2017-18 Q3 and 2023-24 Q4. Each
version is dated by ``external.resolve_published``; ``first_published`` is the quarter's
own ``Published:`` date, the right choice if revisions are ignored. Files for 2010-11 to
2012-13 Q3 were published by the Department of Health and re-hosted by NHS England from
April 2013, so only their re-hosted versions exist here and ``published`` is bounded by
when the Archive first saw them on NHS England's page (2013 to 2018), while
``first_published`` keeps the DH date.

Revisions are small nationally (England G&A occupancy moves by less than 0.3 points, bar
2020-21 Q1 and 2024-25 Q3, which moved 0.4 and 0.8) but can be large for single trusts
(one trust's occupancy moved 58 points in the November 2025 re-issue of 2024-25 Q3). Each
``build`` writes ``kh03_versions.csv`` next to the parquet: one row per version with its
date, rule, lag after quarter end, and the organisations it changed.

Output
------
``data/processed/kh03.parquet``, one row per trust (plus an England row,
``is_total``) per quarter per distinct version::

    quarter_start, quarter_end, fy_quarter      "2023-24 Q3"
    org_code, org_name, parent_code             ODS code as published
    ga_available, ga_occupied, ga_occupancy     G&A average daily beds; occupancy as published
    total_available, total_occupied             all sectors
    dq_flag                                     from the Data Quality sheet, if listed
    published, published_source                 when these values became public, and why
    first_published                             the quarter's first publication
    version, n_versions, is_latest              1 = earliest version of the quarter
    layout, source_file, sha256, url

A later version whose values are identical to the one before is a re-upload, not a
revision, and is dropped. ``as_of(df, when)`` returns the version current on ``when``.

Usage::

    python -m nhs_ae.ingest.kh03 run      # discover, fetch, archive, build
    python -m nhs_ae.ingest.kh03 build    # rebuild the parquet from the archive, offline
"""

from __future__ import annotations

import argparse
import io
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urljoin

import numpy as np
import pandas as pd
from bs4 import BeautifulSoup

from nhs_ae.config import DATA_DIR, PROCESSED_DIR, PROJECT_ROOT
from nhs_ae.ingest import external
from nhs_ae.ingest.download import read_manifest
from nhs_ae.ingest.external import Link, as_date, parse_date

log = logging.getLogger(__name__)

PAGE_URL = ("https://www.england.nhs.uk/statistics/statistical-work-areas/"
            "bed-availability-and-occupancy/bed-data-overnight/")
LEGACY_PAGE_URL = "https://www.england.nhs.uk/statistics/bed-availability-and-occupancy/bed-data-overnight/"
RAW_DIR = DATA_DIR / "external" / "kh03" / "raw"
MANIFEST_PATH = RAW_DIR / "manifest.jsonl"
OUT_PATH = PROCESSED_DIR / "kh03.parquet"
FIRST_QUARTER = date(2010, 4, 1)  # first quarterly trust-level file
INDEX_REGEX = r".*[Oo]vernight.*\.xlsx?$"  # day-only files never say "overnight"
ODS_RE = re.compile(r"^[A-Z0-9]{3,5}$")

_EXT_RE = re.compile(r"\.xlsx?$", re.IGNORECASE)
_LABEL_RE = re.compile(r"quarter\s*(?P<q>[1-4])\s*,?\s*(?P<y>20\d\d)\s*[-/–]\s*(?P<y2>\d\d)",
                       re.IGNORECASE)
_FILE_Q_RE = re.compile(r"(?:^|[-_])q(?:uarter)?[-_]?(?P<q>[1-4])(?=[-_.]|$)", re.IGNORECASE)
_FILE_FY_RE = re.compile(r"(?<!\d)(?P<y>20\d\d)[-_]?(?P<y2>\d\d)(?!\d)")
_FILE_FY_SHORT_RE = re.compile(r"(?<!\d)(?P<a>\d\d)(?P<b>\d\d)-q[1-4]", re.IGNORECASE)
_REVISED_RE = re.compile(r"revised\s*(?P<d>\d{1,2}[./]\d{1,2}[./]\d{2,4})", re.IGNORECASE)
_EXCLUDE = ("day only", "day-only", "dayonly", "time series", "timeseries", "time-series")
_QUARTER_END_MONTH = {"june": 1, "september": 2, "december": 3, "march": 4}


# --------------------------------------------------------------------------------------
# Quarters
# --------------------------------------------------------------------------------------
def quarter_start(fy_start: int, q: int) -> date:
    """Financial year starting April ``fy_start``: Q1 April, Q2 July, Q3 October, Q4 January."""
    return date(fy_start + (q == 4), (3 * q + 1) if q < 4 else 1, 1)


def quarter_end(start: date) -> date:
    """Quarters never straddle a calendar year (Apr–Jun, Jul–Sep, Oct–Dec, Jan–Mar)."""
    return external.month_end(date(start.year, start.month + 2, 1))


def fy_quarter(start: date) -> str:
    fy = start.year - (start.month < 4)
    q = {4: 1, 7: 2, 10: 3, 1: 4}[start.month]
    return f"{fy}-{str(fy + 1)[-2:]} Q{q}"


def _fy_from_filename(name: str) -> int | None:
    for m in _FILE_FY_RE.finditer(name):
        if int(m["y2"]) == (int(m["y"]) + 1) % 100:
            return int(m["y"])
    m = _FILE_FY_SHORT_RE.search(name)
    if m and int(m["b"]) == (int(m["a"]) + 1) % 100:
        return 2000 + int(m["a"])
    return None


# --------------------------------------------------------------------------------------
# Links
# --------------------------------------------------------------------------------------
def parse_link(href: str, text: str = "", base_url: str = "") -> Link | None:
    """A ``Link`` if the anchor is a quarterly trust-level overnight KH03 workbook."""
    if not href:
        return None
    url = urljoin(base_url or PAGE_URL, href.strip())
    filename = unquote(url.rsplit("/", 1)[-1].split("?", 1)[0])
    if not _EXT_RE.search(filename):
        return None
    low = f"{text} {filename}".lower()
    if any(k in low for k in _EXCLUDE):
        return None
    if not ("overnight" in filename.lower() or "nhs organisations in england" in text.lower()
            or "nhs-organisations-in-england-quarter" in filename.lower()):
        return None
    m = _LABEL_RE.search(text)
    if m and int(m["y2"]) == (int(m["y"]) + 1) % 100:
        fy, q = int(m["y"]), int(m["q"])
    else:
        qm, fy = _FILE_Q_RE.search(filename), _fy_from_filename(filename)
        if not qm or fy is None:
            return None
        q = int(qm["q"])
    period = quarter_start(fy, q)
    if period < FIRST_QUARTER:
        return None
    rm = _REVISED_RE.search(text)
    return Link(url=url, filename=filename, period=period, label=" ".join(text.split()),
                revised_on=parse_date(rm["d"]) if rm else None)


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
class Kh03File:
    """One parsed workbook: title-block metadata and the trust table."""

    title: str = ""
    published: date | None = None
    revised: date | None = None
    status: str = ""
    period_text: str = ""
    layout: str = ""
    quarter: date | None = None
    rows: pd.DataFrame = field(default_factory=pd.DataFrame)
    dq: dict[str, str] = field(default_factory=dict)


def _norm(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip().lower().replace("&", " ")
    return re.sub(r"[^a-z0-9%]+", " ", s).strip()


def _cell_text(v) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()


def _title_block(grid: pd.DataFrame, stop: int) -> dict:
    """``Label:`` cells in the rows above the table and the first value to their right."""
    out: dict = {}
    for i in range(stop):
        row = grid.iloc[i].tolist()
        for j, v in enumerate(row):
            key = _norm(v)
            if key in {"title", "published", "revised", "status", "period"} and \
                    str(v).strip().endswith(":"):
                vals = [x for x in row[j + 1:] if _cell_text(x)]
                out.setdefault(key, vals[0] if vals else None)
                break
    return out


def _status_dates(status: str) -> tuple[date | None, date | None]:
    """'Published 18 November 2010 and revised 24 November 2011' (2010-11 to 2012-13)."""
    s = status.lower()
    pub = rev = None
    if "published" in s:
        pub = parse_date(s.split("published", 1)[1].split("revised", 1)[0])
    if "revised" in s:
        rev = parse_date(s.split("revised", 1)[1])
    return pub, rev


def _pick_sheet(xl: pd.ExcelFile) -> str:
    for name in xl.sheet_names:
        if "trust" in name.lower():
            return name
    return xl.sheet_names[0]


def _find_header(grid: pd.DataFrame) -> int:
    for i in range(min(len(grid), 40)):
        cells = {_norm(v) for v in grid.iloc[i].tolist()}
        if "org code" in cells and "general acute" in cells:
            return i
    raise ValueError("no header row with 'Org Code' and 'General & Acute'")


def _group_of(group_row: list, j: int) -> str:
    for k in range(j, -1, -1):
        g = _norm(group_row[k])
        if g:
            return g
    return ""


def _quarter_from_rows(year: str, month: str, period_text: str) -> date | None:
    m = re.match(r"(20\d\d)\s*-\s*(\d\d)", year or "")
    q = _QUARTER_END_MONTH.get((month or "").strip().lower())
    if m and q:
        return quarter_start(int(m[1]), q)
    pm = re.search(r"([a-z]+)\s+to\s+([a-z]+)\s+(20\d\d)", (period_text or "").lower())
    if pm and pm[2] in _QUARTER_END_MONTH:
        q = _QUARTER_END_MONTH[pm[2]]
        return quarter_start(int(pm[3]) - (q == 4), q)
    return None


def read_kh03(src: Path | bytes) -> Kh03File:
    """Parse one KH03 overnight workbook, any layout since 2010-11."""
    data = src if isinstance(src, bytes) else Path(src).read_bytes()
    xl = pd.ExcelFile(io.BytesIO(data))
    sheet = _pick_sheet(xl)
    grid = xl.parse(sheet, header=None, dtype=object)
    h = _find_header(grid)
    g = next((i for i in (h - 1, h - 2) if i >= 0 and
              {"available", "occupied"} <= {_norm(v) for v in grid.iloc[i].tolist()}), None)
    if g is None:
        raise ValueError("no group row with 'Available' and 'Occupied' above the header")
    header, groups = grid.iloc[h].tolist(), grid.iloc[g].tolist()

    cols: dict[str, int] = {}
    parent_label = ""
    for j, v in enumerate(header):
        n = _norm(v)
        if n == "org code":
            cols["org_code"] = j
        elif n == "org name":
            cols["org_name"] = j
        elif n == "year":
            cols["year"] = j
        elif n in ("period", "period end"):
            cols["month"] = j
        elif n.endswith(" code") and "parent_code" not in cols:
            cols["parent_code"], parent_label = j, _cell_text(v)
        elif n in ("general acute", "total"):
            grp = _group_of(groups, j)
            kind = {"available": "available", "occupied": "occupied",
                    "% occupied": "occupancy"}.get(grp)
            if kind:
                cols.setdefault(f"{'ga' if n == 'general acute' else 'total'}_{kind}", j)
    missing = {"org_code", "org_name", "ga_available", "ga_occupied"} - cols.keys()
    if missing:
        raise ValueError(f"columns not found: {sorted(missing)}")

    tb = _title_block(grid, g)
    f = Kh03File(title=_cell_text(tb.get("title")), status=_cell_text(tb.get("status")),
                 period_text=_cell_text(tb.get("period")))
    if "published" in tb:
        f.published, f.revised = parse_date(tb.get("published")), parse_date(tb.get("revised"))
        style = "published_field"
    else:
        f.published, f.revised = _status_dates(f.status)
        style = "status_line"
    if f.title and "overnight" not in f.title.lower():
        raise ValueError(f"not an overnight beds table: {f.title!r}")

    records = []
    for i in range(h + 1, len(grid)):
        row = grid.iloc[i].tolist()
        code = _cell_text(row[cols["org_code"]]).upper()
        name = _cell_text(row[cols["org_name"]])
        is_total = not code and name.lower() == "england"
        if not (is_total or ODS_RE.match(code)):
            continue
        rec = {"org_code": "ENG" if is_total else code, "org_name": name, "is_total": is_total,
               "parent_code": _cell_text(row[cols["parent_code"]]) if "parent_code" in cols
               else "",
               "_year": _cell_text(row[cols["year"]]) if "year" in cols else "",
               "_month": _cell_text(row[cols["month"]]) if "month" in cols else ""}
        for k in ("ga_available", "ga_occupied", "ga_occupancy", "total_available",
                  "total_occupied"):
            rec[k] = pd.to_numeric(row[cols[k]], errors="coerce") if k in cols else np.nan
        if pd.isna(rec["ga_available"]) and pd.isna(rec["total_available"]):
            continue
        records.append(rec)
    rows = pd.DataFrame.from_records(records)
    if rows.empty or (~rows["is_total"]).sum() == 0:
        raise ValueError("no trust rows")
    occ = rows["ga_occupancy"].dropna()
    if len(occ) and occ.median() > 1.5:  # a percentage, not a fraction
        rows["ga_occupancy"] = rows["ga_occupancy"] / 100.0
    first = rows[~rows["is_total"]].iloc[0]
    f.quarter = _quarter_from_rows(first["_year"], first["_month"], f.period_text)
    f.rows = rows.drop(columns=["_year", "_month"])
    ext = "xls" if data[:4] == b"\xd0\xcf\x11\xe0" else "xlsx"
    month_col = _norm(header[cols["month"]]) if "month" in cols else "none"
    f.layout = f"{ext}|{style}|{_norm(parent_label) or 'no parent'}|{month_col}"
    f.dq = _data_quality(xl)
    return f


def _data_quality(xl: pd.ExcelFile) -> dict[str, str]:
    """Trusts named on the Data Quality sheet, by the heading they sit under."""
    sheet = next((s for s in xl.sheet_names if "quality" in s.lower()), None)
    if sheet is None:
        return {}
    grid = xl.parse(sheet, header=None, dtype=object)
    out, heading = {}, ""
    for i in range(len(grid)):
        cells = [_cell_text(v) for v in grid.iloc[i].tolist() if _cell_text(v)]
        if not cells:
            continue
        codes = [c.upper() for c in cells if ODS_RE.match(c.upper())]
        if codes:
            for c in codes:
                out[c] = _dq_flag(heading)
        elif len(cells[0]) > 25:
            heading = cells[0].lower()
    return {k: v for k, v in out.items() if v}


def _dq_flag(heading: str) -> str:
    if "estimate" in heading and ("did not submit" in heading or "behalf" in heading):
        return "estimate_on_behalf"
    if "estimat" in heading:
        return "estimated_return"
    if "revised" in heading:
        return "revised_return"
    if "did not" in heading or "not supplied" in heading or "not submit" in heading:
        return "not_submitted"
    return ""


def read_dates(content: bytes) -> tuple[date | None, date | None]:
    f = read_kh03(content)
    return f.published, f.revised


# --------------------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------------------
VALUE_COLS = ("ga_available", "ga_occupied", "ga_occupancy", "total_available",
              "total_occupied")


def build(manifest_path: Path = MANIFEST_PATH, project_root: Path = PROJECT_ROOT,
          out_path: Path | None = OUT_PATH) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Parse every archived version into the tidy table. Returns (table, failures)."""
    archived = external.manifest_versions(read_manifest(manifest_path))
    parsed: list[tuple[dict, Kh03File]] = []
    failures = []
    for v in archived:
        try:
            f = read_kh03(project_root / v["path"])
        except Exception as e:  # noqa: BLE001 – recorded, never silently dropped
            failures.append({"source_file": Path(v["path"]).name, "url": v["url"],
                             "error": f"{type(e).__name__}: {e}"})
            continue
        q = f.quarter or as_date(v["period"])
        if f.quarter and as_date(v["period"]) and f.quarter != as_date(v["period"]):
            log.warning("%s: link says %s, file says %s; using the file", v["filename"],
                        v["period"], f.quarter)
        v = {**v, "quarter": q}
        parsed.append((v, f))
    failures = pd.DataFrame(failures, columns=["source_file", "url", "error"])
    if not parsed:
        return pd.DataFrame(), failures

    frames = []
    by_quarter: dict[date, list[tuple[dict, Kh03File]]] = {}
    for v, f in parsed:
        by_quarter.setdefault(v["quarter"], []).append((v, f))
    for q, group in sorted(by_quarter.items()):
        first_pub = external.first_publication([f.published for _, f in group],
                                               [v.get("published") for v, _ in group])
        kept = external.drop_reuploads([({**v, "_file": f}, f.rows) for v, f in group],
                                       VALUE_COLS, fy_quarter(q))
        for n, (v, rows) in enumerate(kept, start=1):
            f = v["_file"]
            rows = rows.copy()
            rows["dq_flag"] = rows["org_code"].map(f.dq).fillna("")
            rows = rows.assign(
                quarter_start=pd.Timestamp(q), quarter_end=pd.Timestamp(quarter_end(q)),
                fy_quarter=fy_quarter(q),
                published=pd.Timestamp(v["published"]) if v.get("published") else pd.NaT,
                published_source=v.get("published_source", ""),
                first_published=pd.Timestamp(first_pub) if first_pub else pd.NaT,
                version=n, n_versions=len(kept), is_latest=n == len(kept), layout=f.layout,
                source_file=Path(v["path"]).name, sha256=v["sha256"], url=v["url"])
            frames.append(rows)
    df = pd.concat(frames, ignore_index=True)
    order = ["quarter_start", "quarter_end", "fy_quarter", "org_code", "org_name",
             "parent_code", "is_total", "ga_available", "ga_occupied", "ga_occupancy",
             "total_available", "total_occupied", "dq_flag", "published", "published_source",
             "first_published", "version", "n_versions", "is_latest", "layout", "source_file",
             "sha256", "url"]
    df = df[order].sort_values(["quarter_start", "version", "is_total", "org_code"],
                               ascending=[True, True, False, True]).reset_index(drop=True)
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(out_path, index=False)
        failures.to_csv(out_path.with_name("kh03_parse_failures.csv"), index=False)
        versions(df).to_csv(out_path.with_name("kh03_versions.csv"), index=False)
        log.info("wrote %d rows, %d quarters, %d versions to %s (%d files failed)", len(df),
                 df["quarter_start"].nunique(), df["source_file"].nunique(), out_path,
                 len(failures))
    return df, failures


def as_of(df: pd.DataFrame, when: date | str | pd.Timestamp,
          use_first_published: bool = False) -> pd.DataFrame:
    """The version of every quarter that was current on ``when`` (see ``external.as_of``)."""
    return external.as_of(df, when, "quarter_start", use_first_published)


def versions(df: pd.DataFrame) -> pd.DataFrame:
    """Per-version publication dates, lags and revisions (``national`` = England G&A
    occupancy), written next to the parquet as ``kh03_versions.csv``."""
    out = external.versions_table(df, "quarter_start", df["quarter_end"], VALUE_COLS,
                                  "ga_occupancy")
    out.insert(1, "fy_quarter", out["quarter_start"].map(lambda d: fy_quarter(d.date())))
    return out.rename(columns={"national": "england_ga_occupancy",
                               "national_change": "england_ga_occupancy_change"})


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------
def source_spec() -> external.SourceSpec:
    return external.SourceSpec(
        name="kh03", pages=(PAGE_URL,), history_pages=(LEGACY_PAGE_URL,),
        raw_dir=RAW_DIR, manifest_path=MANIFEST_PATH, project_root=PROJECT_ROOT,
        extract_links=extract_links, link_from_url=link_from_url, read_dates=read_dates,
        index_years=tuple(range(2013, external.today().year + 1)), index_regex=INDEX_REGEX)


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-v", "--verbose", action="store_true")
    ap = argparse.ArgumentParser(prog="python -m nhs_ae.ingest.kh03",
                                 description="KH03 overnight beds: archive and tidy table.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", parents=[common],
                         help="discover, fetch and archive every version, then build")
    run.add_argument("--no-history", action="store_true",
                     help="live page only; skip the Internet Archive")
    sub.add_parser("build", parents=[common],
                   help="rebuild the parquet from the archive, no network")
    args = ap.parse_args(argv)
    level = logging.INFO if args.verbose or args.cmd == "run" else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")
    if args.cmd == "run":
        summary = external.collect(source_spec(), history=not args.no_history)
        log.info("kh03 collect: %s", summary)
    df, failures = build()
    if df.empty:
        log.error("nothing parsed; is %s populated?", MANIFEST_PATH)
        return 1
    print(f"kh03: {df['quarter_start'].nunique()} quarters, {df['source_file'].nunique()} "
          f"versions, {len(failures)} unparsed files -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
