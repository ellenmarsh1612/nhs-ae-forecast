"""Central configuration for the NHS A&E forecasting project.

Everything that is a *fact about the data source* lives here so that the rest of the
codebase never hard-codes URLs, column names or file layouts.
"""

from __future__ import annotations

from pathlib import Path

# --------------------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"  # vintage archive: raw/<snapshot_date>/<filename>
PROCESSED_DIR = DATA_DIR / "processed"  # tidy parquet: processed/vintages/<snapshot_date>.parquet
CACHE_DIR = DATA_DIR / "cache"  # Internet Archive responses (not committed; safe to delete)
MANIFEST_PATH = RAW_DIR / "manifest.jsonl"

# --------------------------------------------------------------------------------------
# NHS England source pages
# --------------------------------------------------------------------------------------
# The monthly collection is published on the second Thursday of each month and covers the
# previous month. Files are re-published *in place* at the twice-yearly revisions (May and
# November), with "(revised dd.mm.yy)" added to the link text and filename. That is why we
# keep dated snapshots rather than a single "latest" copy.
AE_STATS_BASE = (
    "https://www.england.nhs.uk/statistics/statistical-work-areas/"
    "ae-waiting-times-and-activity/"
)

# Financial-year pages. Monthly provider-level CSVs exist from 2015-16 onwards.
# (Weekly data before June 2015 was apportioned to months by NHS England and is
# excluded from modelling; see docs/scope.md.)
FINANCIAL_YEARS: tuple[str, ...] = tuple(
    f"{y}-{str(y + 1)[-2:]}" for y in range(2015, 2027)
)


# The two oldest year pages keep a legacy slug (verified 2026-09-08 against the live site).
_LEGACY_YEAR_PAGE_SLUGS: dict[str, str] = {
    "2015-16": ("statistical-work-areasae-waiting-times-and-activityae-attendances-and-"
                "emergency-admissions-2015-16-monthly-3/"),
    "2016-17": ("statistical-work-areasae-waiting-times-and-activityae-attendances-and-"
                "emergency-admissions-2016-17/"),
}


def year_page_url(financial_year: str) -> str:
    """URL of the NHS England page listing that financial year's monthly files."""
    slug = _LEGACY_YEAR_PAGE_SLUGS.get(
        financial_year, f"ae-attendances-and-emergency-admissions-{financial_year}/")
    return f"{AE_STATS_BASE}{slug}"


# --------------------------------------------------------------------------------------
# Canonical schema for the monthly provider-level return
# --------------------------------------------------------------------------------------
# Column names in the published CSVs drift across years ("A&E attendances Type 1",
# "Number of A&E attendances Type 1", ...). parse.py maps whatever it finds onto these
# canonical names using the regex rules in HEADER_RULES. Anything unmatched is kept
# under its raw name with an "unmapped__" prefix so nothing is silently dropped.
CANONICAL_ID_COLUMNS: tuple[str, ...] = ("period", "org_code", "parent_org", "org_name")

CANONICAL_METRICS: dict[str, str] = {
    # attendances
    "att_type1": "A&E attendances, Type 1 (unplanned)",
    "att_type2": "A&E attendances, Type 2 (unplanned)",
    "att_other": "A&E attendances, Type 3 / other (unplanned)",
    "att_booked_type1": "Booked A&E appointments attended, Type 1",
    "att_booked_type2": "Booked A&E appointments attended, Type 2",
    "att_booked_other": "Booked A&E appointments attended, Type 3 / other",
    # four-hour breaches
    "over4h_type1": "Attendances over 4 hours, Type 1",
    "over4h_type2": "Attendances over 4 hours, Type 2",
    "over4h_other": "Attendances over 4 hours, Type 3 / other",
    "over4h_booked_type1": "Booked appointments over 4 hours, Type 1",
    "over4h_booked_type2": "Booked appointments over 4 hours, Type 2",
    "over4h_booked_other": "Booked appointments over 4 hours, Type 3 / other",
    # decision-to-admit waits
    "dta_wait_4_12h": "Patients waiting 4-12 hours from decision to admit to admission",
    "dta_wait_over_12h": "Patients waiting 12+ hours from decision to admit to admission",
    # Only the workbooks carry this column (the CSVs report 4-12h instead). Before 2018-04
    # it is the sole DTA measure and includes the 12h+ cases; treat it as its own series.
    "dta_wait_over_4h": "Patients waiting 4+ hours from decision to admit (workbook column)",
    # admissions
    "adm_via_ae_type1": "Emergency admissions via A&E, Type 1",
    "adm_via_ae_type2": "Emergency admissions via A&E, Type 2",
    "adm_via_ae_other": "Emergency admissions via A&E, Type 3 / other",
    "adm_other_emergency": "Other emergency admissions (not via A&E)",
    "adm_total_emergency": "Total emergency admissions",
}

# Ordered (regex, canonical) rules applied to a *normalised* header string
# (lower-cased, '>' -> 'over', '<' -> 'under', punctuation collapsed to single spaces).
# First match wins, so the more specific patterns must come first. A canonical value of
# DROP means "known, derivable or out of scope, do not keep" (totals and percentages);
# it is logged at debug level, unlike an unmapped column which is kept and warned about.
#
# Legacy workbooks (2015-06 to 2018-03, and every XLS since) carry a two-row header: a
# group ("A&E attendances", "Emergency Admissions", ...) above sub-columns ("Type 1
# Departments - Major A&E", ...). parse.py joins them as "<group> <sub>" before matching,
# so the rules below see strings like "a e attendances type 1 departments major a e".
DROP = "__drop__"
HEADER_RULES: tuple[tuple[str, str], ...] = (
    # identifiers
    (r"^period$", "period"),
    (r"^(provider )?org(anisation)? code$", "org_code"),
    (r"^code$", "org_code"),
    (r"^parent org(anisation)?( code)?$", "parent_org"),
    (r"^(region|system|stp|provider parent name)$", "parent_org"),
    (r"^org(anisation)? name$", "org_name"),
    (r"^name$", "org_name"),
    # derived or out-of-scope columns
    (r"percentage", DROP),
    (r"total attendances", DROP),          # also "total attendances over/under 4 hours"
    (r"under 4 ?h(ou)?rs?", DROP),         # "< 4 hours" = attendances - over 4 hours
    (r"decision to admit.*type [123]", DROP),   # per-type DTA splits (Feb/Mar 2018 only)
    (r"total emergency admissions via a ?e", DROP),
    # decision-to-admit waits (before the over-4h attendance rules: both say "over 4")
    (r"(4 ?12|4 to 12).*(dta|decision to admit)", "dta_wait_4_12h"),
    (r"(12 ?\+|over 12 ?h).*(dta|decision to admit)", "dta_wait_over_12h"),
    (r"over 4 ?h(ou)?rs? .*decision to admit", "dta_wait_over_4h"),
    # booked appointments over 4h (must precede plain over-4h and plain booked rules)
    (r"over 4 ?h(ou)?rs? .*booked .*type 1", "over4h_booked_type1"),
    (r"over 4 ?h(ou)?rs? .*booked .*type 2", "over4h_booked_type2"),
    (r"over 4 ?h(ou)?rs? .*booked .*(other|type 3)", "over4h_booked_other"),
    # over 4h
    (r"over 4 ?h(ou)?rs? .*type 1", "over4h_type1"),
    (r"over 4 ?h(ou)?rs? .*type 2", "over4h_type2"),
    (r"over 4 ?h(ou)?rs? .*(other|type 3)", "over4h_other"),
    # booked appointments attended
    (r"booked .*type 1", "att_booked_type1"),
    (r"booked .*type 2", "att_booked_type2"),
    (r"booked .*(other|type 3)", "att_booked_other"),
    # attendances
    (r"attendances .*type 1", "att_type1"),
    (r"attendances .*type 2", "att_type2"),
    (r"attendances .*(other|type 3)", "att_other"),
    # admissions (modern "via A&E - Type 1", legacy "via Type 1 A&E", split-CSV "Adm Type 1")
    (r"other emergency admissions", "adm_other_emergency"),
    (r"^emergency adm other$", "adm_other_emergency"),
    (r"^emergency adm type 1$", "adm_via_ae_type1"),
    (r"^emergency adm type 2$", "adm_via_ae_type2"),
    (r"^emergency adm type 3$", "adm_via_ae_other"),
    (r"emergency admissions via( a ?e)? ?.*type 1", "adm_via_ae_type1"),
    (r"emergency admissions via( a ?e)? ?.*type 2", "adm_via_ae_type2"),
    (r"emergency admissions via( a ?e)? ?.*(other|type 3)", "adm_via_ae_other"),
    (r"total emergency admissions", "adm_total_emergency"),
)

# Rows that are national/regional totals rather than providers. Matched against org_code
# and org_name after normalisation.
TOTAL_ROW_PATTERNS: tuple[str, ...] = (r"^total$", r"^england$", r"^-$", r"^$")

MONTHS: dict[str, int] = {
    m: i
    for i, m in enumerate(
        ["january", "february", "march", "april", "may", "june", "july", "august",
         "september", "october", "november", "december"],
        start=1,
    )
}
