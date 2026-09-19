"""Unit tests for header mapping, period parsing and the tidy-long transform.

The fixture is SYNTHETIC. It copies the column layout of the post-August-2020 monthly
CSV (which is what the mapping rules target) but every number is invented.
"""
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from nhs_ae.config import CANONICAL_METRICS
from nhs_ae.ingest.parse import (
    map_header,
    normalise_header,
    parse_monthly_file,
    parse_period_cell,
    validate_long,
)

FIXTURE = Path(__file__).parent / "fixtures" / "monthly_ae_sample.csv"


@pytest.mark.parametrize("raw,expected", [
    ("Period", "period"),
    ("Org Code", "org_code"),
    ("Parent Org", "parent_org"),
    ("Org name", "org_name"),
    ("A&E attendances Type 1", "att_type1"),
    ("Number of A&E attendances Type 2", "att_type2"),
    ("A&E attendances Other A&E Department", "att_other"),
    ("A&E attendances Booked Appointments Type 1", "att_booked_type1"),
    ("Attendances over 4hrs Type 1", "over4h_type1"),
    ("Attendances over 4hrs Booked Appointments Other Department", "over4h_booked_other"),
    ("Patients who have waited 4-12 hs from DTA to admission", "dta_wait_4_12h"),
    ("Patients who have waited 12+ hrs from DTA to admission", "dta_wait_over_12h"),
    ("Emergency admissions via A&E - Type 1", "adm_via_ae_type1"),
    ("Emergency admissions via A&E - Other A&E department", "adm_via_ae_other"),
    ("Other emergency admissions", "adm_other_emergency"),
    ("Total emergency admissions", "adm_total_emergency"),
    ("Some future column nobody expected", "unmapped__some_future_column_nobody_expected"),
])
def test_map_header(raw, expected):
    assert map_header(raw) == expected


def test_all_canonical_metrics_reachable():
    """Every canonical metric must have at least one rule producing it."""
    from nhs_ae.config import HEADER_RULES
    produced = {c for _, c in HEADER_RULES}
    missing = set(CANONICAL_METRICS) - produced
    assert not missing, f"no header rule can produce: {missing}"


def test_normalise_header_collapses_punctuation():
    assert normalise_header("  A&E attendances - Type 1!! ") == "a e attendances type 1"


@pytest.mark.parametrize("cell,expected", [
    ("MSitAE-JULY-2026", date(2026, 7, 1)),
    ("January 2024", date(2024, 1, 1)),
    ("MSitAE-SEPTEMBER-2015", date(2015, 9, 1)),
    ("garbage", None),
    ("", None),
])
def test_parse_period_cell(cell, expected):
    assert parse_period_cell(cell) == expected


def test_parse_monthly_file_shape_and_values():
    long = parse_monthly_file(FIXTURE, ext="csv", source_file=FIXTURE.name,
                              snapshot=date(2026, 9, 10), revised=False)
    # 4 rows x 19 metrics (dta_wait_over_4h exists only in pre-2018 files)
    expected = set(CANONICAL_METRICS) - {"dta_wait_over_4h"}
    assert len(long) == 4 * len(expected)
    assert set(long["metric"]) == expected
    assert not any(m.startswith("unmapped__") for m in long["metric"])
    assert (long["period"] == pd.Timestamp("2026-07-01")).all()

    rth = long[(long.org_code == "RTH") & (long.metric == "att_type1")]["value"].item()
    assert rth == 13456  # thousands separator stripped
    total = long[long.is_total]
    assert set(total["org_name"]) == {"Total"}
    assert (long[~long.is_total]["org_code"] != "-").all()

    # non-submitting provider -> NaN, not 0
    rxx = long[(long.org_code == "RXX") & (long.metric == "att_type1")]["value"].item()
    assert pd.isna(rxx)

    # provenance columns present
    assert long["snapshot"].iloc[0] == date(2026, 9, 10)
    assert long["revised"].eq(False).all()


def test_parse_from_bytes_and_revision_metadata():
    long = parse_monthly_file(FIXTURE.read_bytes(), ext="csv", source_file="x.csv",
                              snapshot=date(2026, 11, 12), revised=True,
                              revised_on=date(2026, 11, 12), sha256="abc")
    assert long["revised"].all()
    assert (long["revised_on"] == pd.Timestamp("2026-11-12")).all()
    assert (long["sha256"] == "abc").all()


def test_validate_long_flags_low_national_total():
    long = parse_monthly_file(FIXTURE, ext="csv", source_file=FIXTURE.name,
                              snapshot=date(2026, 9, 10))
    problems = validate_long(long)
    # the fixture has one real provider so the national sum is tiny -> should warn
    assert any("missing providers" in p for p in problems)
    assert not any("duplicate" in p for p in problems)


LEGACY_XLSX = Path(__file__).parent / "fixtures" / "legacy_ae_sample.xlsx"
SPLIT_ATT = Path(__file__).parent / "fixtures" / "split_att_sample.csv"
SPLIT_ADM = Path(__file__).parent / "fixtures" / "split_adm_sample.csv"


@pytest.mark.parametrize("raw,expected", [
    ("A&E attendances Type 1 Departments - Major A&E", "att_type1"),
    ("A&E attendances Type 3 Departments - Other A&E/Minor Injury Unit", "att_other"),
    ("A&E attendances Total attendances", "__drop__"),
    ("A&E attendances > 4 hours from arrival to admission, transfer or discharge Type 2 Departments - Single Specialty", "over4h_type2"),
    ("A&E attendances greater than 4 hours from arrival to admission, transfer or discharge Type 1 Departments - Major A&E", "over4h_type1"),
    ("A&E attendances less than 4 hours from arrival to admission, transfer or discharge Type 1 Departments - Major A&E", "__drop__"),
    ("Percentage of attendances within 4 hours Percentage in 4 hours or less (type 1)", "__drop__"),
    ("Emergency Admissions Emergency Admissions via Type 1 A&E", "adm_via_ae_type1"),
    ("Emergency Admissions Emergency Admissions via Type 3 and 4 A&E", "adm_via_ae_other"),
    ("Emergency Admissions Total Emergency Admissions via A&E", "__drop__"),
    ("Emergency Admissions Other Emergency admissions (i.e not via A&E)", "adm_other_emergency"),
    ("Emergency Admissions Total Emergency Admissions", "adm_total_emergency"),
    ("Emergency Admissions Number of patients spending >4 hours from decision to admit to admission", "dta_wait_over_4h"),
    ("Emergency Admissions Number of patients spending >12 hours from decision to admit to admission", "dta_wait_over_12h"),
    ("Number of patients spending >4 hours from decision to admit to admission Type 1 Departments - Major A&E", "__drop__"),
    ("Number of patients spending >4 hours from decision to admit to admission Sum", "dta_wait_over_4h"),
    ("Emergency Adm Type 3", "adm_via_ae_other"),
    ("Emergency Adm Other", "adm_other_emergency"),
    ("Provider Org Code", "org_code"),
    ("Provider Parent Name", "parent_org"),
    ("Region", "parent_org"),
])
def test_map_legacy_headers(raw, expected):
    assert map_header(raw) == expected


def test_parse_legacy_workbook():
    """Title block, merged group row above the sub-header, England row, footnote."""
    long = parse_monthly_file(LEGACY_XLSX, ext="xlsx", source_file=LEGACY_XLSX.name,
                              snapshot=date(2017, 5, 11), fallback_period=date(2016, 4, 1))
    assert (long["period"] == pd.Timestamp("2016-04-01")).all()
    prov = long[~long.is_total]
    assert set(prov.org_code) == {"RTH", "NXX", "RZZ"}          # footnote row discarded
    assert set(long[long.is_total].org_name) == {"England"}
    assert not any(m.startswith("unmapped__") for m in long.metric)
    assert "__drop__" not in set(long.metric)
    v = lambda org, m: prov[(prov.org_code == org) & (prov.metric == m)]["value"].item()
    assert v("RTH", "att_type1") == 600
    assert v("NXX", "att_other") == 600
    assert v("RTH", "over4h_type1") == 60
    assert v("RTH", "adm_via_ae_type1") == 200 and v("NXX", "adm_via_ae_other") == 5
    assert v("RTH", "adm_other_emergency") == 70 and v("RTH", "adm_total_emergency") == 272
    assert v("RTH", "dta_wait_over_4h") == 15 and v("RTH", "dta_wait_over_12h") == 1
    assert pd.isna(v("RZZ", "att_type1"))                          # '-' -> NaN, never 0
    assert prov[prov.org_code == "RTH"].parent_org.iloc[0] == "South of England Commissioning Region"
    # every provider has exactly one row per metric
    assert not prov.duplicated(["org_code", "metric"]).any()


def test_parse_legacy_workbook_title_period_mismatch_is_flagged(caplog):
    with caplog.at_level("WARNING"):
        long = parse_monthly_file(LEGACY_XLSX, ext="xlsx", source_file="x.xlsx",
                                  snapshot=date(2017, 5, 11), fallback_period=date(2016, 5, 1))
    assert "title block says 2016-04-01" in caplog.text
    assert (long["period"] == pd.Timestamp("2016-05-01")).all()   # manifest wins


def test_parse_split_csvs_concatenate():
    """Feb/Mar 2018: attendances and admissions in separate files with title blocks."""
    att = parse_monthly_file(SPLIT_ATT, ext="csv", source_file=SPLIT_ATT.name,
                             snapshot=date(2018, 4, 12), fallback_period=date(2018, 3, 1))
    adm = parse_monthly_file(SPLIT_ADM, ext="csv", source_file=SPLIT_ADM.name,
                             snapshot=date(2018, 4, 12), fallback_period=date(2018, 3, 1))
    assert set(att[~att.is_total].metric) == {"att_type1", "att_type2", "att_other", "over4h_type1",
                                              "over4h_type2", "over4h_other", "dta_wait_over_4h",
                                              "dta_wait_over_12h"}
    assert set(adm.metric) == {"adm_via_ae_type1", "adm_via_ae_type2", "adm_via_ae_other",
                               "adm_other_emergency"}
    assert set(att[att.is_total].org_code) == {"ENGLAND"}
    both = pd.concat([att, adm])
    rth = both[(both.org_code == "RTH") & ~both.is_total].set_index("metric")["value"]
    assert rth["att_type1"] == 600 and rth["dta_wait_over_4h"] == 10 and rth["adm_via_ae_type1"] == 200
    assert rth["adm_other_emergency"] == 70
    assert not both[~both.is_total].duplicated(["org_code", "metric"]).any()
    assert (both["period"] == pd.Timestamp("2018-03-01")).all()


def test_workbook_prefers_non_booked_sheet(tmp_path):
    """Post-2020 workbooks: the provider sheet includes booked appointments; the
    non-booked sheet matches the CSV definition and must win."""
    from openpyxl import load_workbook
    wb = load_workbook(LEGACY_XLSX)
    ws = wb["A&E Data"]
    ws.title = "Provider Level Data"
    nb = wb.copy_worksheet(ws)
    nb.title = "Non-Booked Data"
    nb["E19"] = 550                     # RTH Type 1 without booked appointments (600 with)
    path = tmp_path / "post2020.xlsx"
    wb.save(path)
    long = parse_monthly_file(path, ext="xlsx", source_file=path.name, snapshot=date(2025, 5, 21),
                              fallback_period=date(2016, 4, 1))
    rth = long[(long.org_code == "RTH") & (long.metric == "att_type1")]["value"].item()
    assert rth == 550
