"""Parse raw monthly A&E files into one tidy, long-format table.

Output schema (one row per provider x period x metric)::

    period          date      first day of month the data covers
    org_code        str       ODS provider code (e.g. RTH)
    parent_org      str       system / ICB code as published
    org_name        str
    metric          str       canonical metric name (see config.CANONICAL_METRICS)
    value           float     NaN where the provider did not submit
    is_total        bool      True for England / total rows
    source_file     str       filename as published
    snapshot        date      date the vintage was fetched
    revised         bool      file was a revised re-publication
    revised_on      date|NaT  revision date if stated
    sha256          str       content hash of the source file

Header normalisation is rule-based (config.HEADER_RULES). Unmatched columns are kept
with an ``unmapped__`` prefix and logged, never dropped, so schema drift is visible
rather than silent. Columns the rules mark as DROP (totals, percentages) are derivable
and are discarded with a debug log line.

Three physical layouts are handled by ``_read_raw``:

* modern CSV (2018-04 onward): one header row, ``Period, Org Code, Parent Org, ...``;
* workbooks (every XLS/XLSX, and the only format before 2018-04): a title block
  (``Period: June 2015``), a provider sheet (the first sheet in old files; since
  August 2020 the "Non-Booked Data" sheet, which excludes booked appointments like the
  CSV does), a group row with merged cells above a sub-header row starting
  ``Code | Region | Name``;
* the February and March 2018 split CSVs (``*-att-csv``, ``*-adm-csv``): a title
  block, a two-row header whose first three columns are unnamed (attendances) or a
  one-row header (admissions). Each file yields its own metrics; the long format
  lets the two halves simply concatenate.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from datetime import date
from pathlib import Path

import pandas as pd

from nhs_ae.config import (
    CANONICAL_ID_COLUMNS,
    CANONICAL_METRICS,
    DROP,
    HEADER_RULES,
    MONTHS,
    TOTAL_ROW_PATTERNS,
)

log = logging.getLogger(__name__)

_PERIOD_RE = re.compile(r"(?P<month>[a-z]+)[\s\-_/]*(?P<year>20\d\d)", re.IGNORECASE)
_WS_RE = re.compile(r"[^a-z0-9+]+")
_CODE_RE = re.compile(r"^[a-z0-9\-]{1,8}$")  # ODS codes ("RTH", "NLO01", "8J094") or "-"
_HEADER_KEYS = {"org code", "provider org code", "code"}
_SUB_HEADER_HINT = "departments"  # split-CSV attendance header has no Code cell
# Sheet preference for workbooks. Since August 2020 the "Provider Level Data" sheet counts
# booked appointments in the attendance columns; "Non-Booked Data" matches the CSV's
# unplanned definition (verified: identical England totals for February 2025). Using the
# wrong sheet manufactures a +4% "revision" wherever a workbook has no CSV twin.
SHEET_PREFERENCE = ("Non-Booked Data", "Provider Level Data")


def normalise_header(h: str) -> str:
    """Lower-case, spell out comparison signs, collapse punctuation. 'A&E' -> 'a e'."""
    h = str(h).strip().lower().replace("&", " ").replace(">", " over ").replace("<", " under ")
    h = h.replace("greater than", "over").replace("more than", "over").replace("less than", "under")
    h = _WS_RE.sub(" ", h).strip()
    return h


def map_header(h: str) -> str:
    """Map one raw header to a canonical name, DROP, or an ``unmapped__`` fallback."""
    n = normalise_header(h)
    for pattern, canonical in HEADER_RULES:
        if re.search(pattern, n):
            return canonical
    return f"unmapped__{n.replace(' ', '_')}"


def parse_period_cell(value: str) -> date | None:
    """'MSitAE-JANUARY-2024' or 'January 2024' -> date(2024, 1, 1)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (pd.Timestamp, date)):
        ts = pd.Timestamp(value)
        return date(ts.year, ts.month, 1)
    m = _PERIOD_RE.search(str(value))
    if not m or m["month"].lower() not in MONTHS:
        return None
    return date(int(m["year"]), MONTHS[m["month"].lower()], 1)


def _is_total(code: str, name: str) -> bool:
    c, n = str(code).strip().lower(), str(name).strip().lower()
    return any(re.search(p, c) for p in TOTAL_ROW_PATTERNS) or n in {"total", "england"}


def _blank(v) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() in ("", "nan", "None")


def _read_csv_rows(path_or_bytes: Path | bytes) -> list[list[str]]:
    """Ragged-safe CSV read (the 2018 split files have variable row widths)."""
    data = path_or_bytes if isinstance(path_or_bytes, bytes) else Path(path_or_bytes).read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:  # NHS CSVs are occasionally cp1252
        text = data.decode("cp1252")
    rows = list(csv.reader(io.StringIO(text)))
    width = max((len(r) for r in rows), default=0)
    return [r + [""] * (width - len(r)) for r in rows]


def _read_workbook_rows(path_or_bytes: Path | bytes) -> list[list]:
    """First sheet, or the provider sheet when the workbook leads with system totals."""
    src = io.BytesIO(path_or_bytes) if isinstance(path_or_bytes, bytes) else path_or_bytes
    book = pd.ExcelFile(src)
    sheet = next((s for s in SHEET_PREFERENCE if s in book.sheet_names), book.sheet_names[0])
    return book.parse(sheet, header=None, dtype=str).values.tolist()


def _find_header(rows: list[list]) -> int:
    for i, row in enumerate(rows[:40]):
        cells = [normalise_header(v) for v in row if not _blank(v)]
        if any(c in _HEADER_KEYS for c in cells):
            return i
        if sum(_SUB_HEADER_HINT in c for c in cells) >= 2:
            return i
    raise ValueError("Could not locate header row (expected 'Org Code' / 'Code' / typed sub-headers)")


def _title_period(rows: list[list], header_idx: int) -> date | None:
    """'Period:' | 'June 2015' in a workbook title block, or 'Period Name:MARCH' + 'Year:2017-18'."""
    year = None
    for row in rows[:header_idx]:
        cells = [str(v).strip() for v in row if not _blank(v)]
        for j, c in enumerate(cells):
            low = c.lower()
            if low.startswith("year:"):
                year = low.split(":", 1)[1].strip()[:4]
            if low.rstrip(":") == "period" and j + 1 < len(cells):
                return parse_period_cell(cells[j + 1])
            if low.startswith("period name:") and year:
                month = low.split(":", 1)[1].strip()
                if month in MONTHS:
                    y = int(year) + (1 if MONTHS[month] <= 3 else 0)  # financial year
                    return date(y, MONTHS[month], 1)
    return None


def _read_raw(path_or_bytes: Path | bytes, ext: str) -> tuple[pd.DataFrame, date | None]:
    """Read CSV/XLS(X) into a DataFrame with raw (joined) header strings.

    Returns the frame and the period stated in the title block, if any. Handles a
    single header row (modern CSV) or a group row above a sub-header row (workbooks
    and the 2018 split CSVs): group labels are forward-filled across the merged span
    and joined to each sub-header. Unnamed leading columns are taken to be
    Code / Region / Name, which is how the split attendance CSV presents them.
    """
    rows = _read_csv_rows(path_or_bytes) if ext == "csv" else _read_workbook_rows(path_or_bytes)
    h = _find_header(rows)
    sub = [("" if _blank(v) else str(v).strip()) for v in rows[h]]
    group = [""] * len(sub)
    if h > 0 and sum(not _blank(v) for v in rows[h - 1]) >= 2:
        last = ""
        for j, v in enumerate(rows[h - 1]):
            last = "" if j == 0 and _blank(v) else (last if _blank(v) else str(v).strip())
            group[j] = last
    # A group label with no sub-header is a merged-cell artefact, not a column. Leading
    # unnamed columns are Code / Region / Name only when the header names no code column.
    names = [f"{g} {s_}".strip() if s_ else "" for g, s_ in zip(group, sub)]
    if not any(normalise_header(n) in _HEADER_KEYS for n in names):
        for j, fallback in enumerate(("Code", "Region", "Name")):
            if j < len(names) and not names[j]:
                names[j] = fallback
    keep = [j for j, n in enumerate(names) if n]
    body = [[r[j] for j in keep] for r in rows[h + 1:]]
    df = pd.DataFrame(body, columns=[names[j] for j in keep])
    return df.reset_index(drop=True), _title_period(rows, h)


def _to_number(s: pd.Series) -> pd.Series:
    """'12,345' -> 12345; '', '-', '*' -> NaN (suppressed or not submitted)."""
    cleaned = (
        s.astype(str).str.strip().str.replace(",", "", regex=False)
        .replace({"": None, "-": None, "*": None, "nan": None, "None": None})
    )
    return pd.to_numeric(cleaned, errors="coerce")


def parse_monthly_file(path_or_bytes: Path | bytes,
                       *,
                       ext: str,
                       source_file: str,
                       snapshot: date,
                       revised: bool = False,
                       revised_on: date | None = None,
                       sha256: str | None = None,
                       fallback_period: date | None = None) -> pd.DataFrame:
    """Parse one monthly file to the tidy long schema described in the module docstring."""
    raw, title_period = _read_raw(path_or_bytes, ext)
    mapping = {c: map_header(c) for c in raw.columns}
    if not any(m in CANONICAL_METRICS for m in mapping.values()):
        raise ValueError(f"{source_file}: no recognised metric columns; not a monthly A&E "
                         f"provider file? headers: {list(raw.columns)[:8]}")
    # an unmapped column with no values at all is a stray header cell, not schema drift
    empty = [c for c, m in mapping.items() if m.startswith("unmapped__") and raw[c].map(_blank).all()]
    if empty:
        log.debug("%s: ignoring empty columns %s", source_file, empty)
        raw = raw.loc[:, [c for c in raw.columns if c not in empty]]
        mapping = {c: mapping[c] for c in raw.columns}
    unmapped = [c for c, m in mapping.items() if m.startswith("unmapped__")]
    if unmapped:
        log.warning("%s: %d unmapped columns: %s", source_file, len(unmapped), unmapped)
    dropped = [c for c, m in mapping.items() if m == DROP]
    if dropped:
        log.debug("%s: dropping %d derivable columns: %s", source_file, len(dropped), dropped)
    raw = raw.loc[:, [c for c in raw.columns if mapping[c] != DROP]]
    if len({mapping[c] for c in raw.columns}) != len(raw.columns):
        dup = [c for c in raw.columns if [mapping[x] for x in raw.columns].count(mapping[c]) > 1]
        raise ValueError(f"{source_file}: several columns map to the same metric: {dup}")
    df = raw.rename(columns=mapping)

    # Identifiers
    for col in CANONICAL_ID_COLUMNS:
        if col not in df.columns:
            df[col] = None
    df["period"] = df["period"].map(parse_period_cell)
    if df["period"].isna().all():
        stated = title_period or fallback_period
        if stated is None:
            raise ValueError(f"{source_file}: no parseable period column and no fallback given")
        if title_period and fallback_period and title_period != fallback_period:
            log.warning("%s: title block says %s but manifest says %s; using manifest",
                        source_file, title_period, fallback_period)
            stated = fallback_period
        df["period"] = stated
    df["org_code"] = df["org_code"].map(lambda v: "" if _blank(v) else str(v).strip().upper())
    df["org_name"] = df["org_name"].map(lambda v: "" if _blank(v) else str(v).strip())
    df["parent_org"] = df["parent_org"].map(lambda v: "" if _blank(v) else str(v).strip())
    # keep rows that look like an organisation (or a total); this discards footnotes
    looks_like_org = df["org_code"].str.lower().str.match(_CODE_RE) | df["org_name"].str.lower().isin(
        {"england", "total"}) | df["org_code"].str.lower().isin({"england", "total"})
    df = df[looks_like_org]
    df["is_total"] = [_is_total(c, n) for c, n in zip(df["org_code"], df["org_name"])]

    metric_cols = [c for c in df.columns if c in CANONICAL_METRICS or c.startswith("unmapped__")]
    for c in metric_cols:
        df[c] = _to_number(df[c])

    long = df.melt(
        id_vars=list(CANONICAL_ID_COLUMNS) + ["is_total"],
        value_vars=metric_cols,
        var_name="metric",
        value_name="value",
    )
    long["source_file"] = source_file
    long["snapshot"] = snapshot
    long["revised"] = bool(revised)
    long["revised_on"] = pd.to_datetime(revised_on) if revised_on else pd.NaT
    long["sha256"] = sha256
    long["period"] = pd.to_datetime(long["period"])
    return long[
        ["period", "org_code", "parent_org", "org_name", "metric", "value", "is_total",
         "source_file", "snapshot", "revised", "revised_on", "sha256"]
    ].reset_index(drop=True)


def parse_manifest_records(records: list[dict], raw_root: Path
                           ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Parse every *stored* manifest record into one long table (all vintages).

    Returns ``(long, failures)``. ``failures`` has one row per archived file that could
    not be parsed (path, period, snapshot, sha256, error); the as-of loader must treat
    those versions as unavailable and fall back to the previous parseable one rather
    than silently using the latest revised data.
    """
    frames, failures = [], []
    for rec in records:
        if not rec.get("stored"):
            continue
        path = raw_root / rec["path"]
        snap = rec["snapshot"] if isinstance(rec["snapshot"], date) else date.fromisoformat(str(rec["snapshot"]))
        rev_on = rec.get("revised_on")
        rev_on = date.fromisoformat(str(rev_on)) if rev_on else None
        try:
            frames.append(parse_monthly_file(
                path, ext=rec["ext"], source_file=rec["filename"], snapshot=snap,
                revised=bool(rec.get("revised")), revised_on=rev_on, sha256=rec.get("sha256"),
                fallback_period=date.fromisoformat(str(rec["period"])),
            ))
        except Exception as e:  # noqa: BLE001 – one bad file must not kill the archive build
            log.error("Failed to parse %s: %s", path, str(e)[:200] or type(e).__name__)
            failures.append({"path": rec["path"], "period": str(rec["period"])[:10],
                             "snapshot": snap, "sha256": rec.get("sha256"),
                             "error": (str(e).splitlines() or [type(e).__name__])[0][:200]})
    long = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return long, pd.DataFrame(failures, columns=["path", "period", "snapshot", "sha256", "error"])


def validate_long(df: pd.DataFrame) -> list[str]:
    """Cheap sanity checks. Returns a list of human-readable problems (empty = fine)."""
    problems: list[str] = []
    if df.empty:
        return ["empty table"]
    dup = df.duplicated(["period", "org_code", "metric", "snapshot"]).sum()
    if dup:
        problems.append(f"{dup} duplicate (period, org_code, metric, snapshot) rows")
    neg = (df["value"] < 0).sum()
    if neg:
        problems.append(f"{neg} negative values")
    prov = df[~df["is_total"]]
    att = prov[prov["metric"] == "att_type1"].groupby("period")["value"].sum()
    if not att.empty and (att < 500_000).any():
        problems.append("national Type 1 attendances below 500k in some months – missing providers?")
    return problems
