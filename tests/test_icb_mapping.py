"""Provider-to-ICB mapping ingest, all on synthetic workbooks (no real NHS numbers).

The synthetic files copy the real layout: a title block, an empty column A, the header
on row 8, one exact duplicate row, a lower-case code and, in the older version, a
pre-2019 region label. The two versions mimic the April 2026 change: two ICBs merge and
a third is split between two successors.
"""
import io
import json
from datetime import date

import pandas as pd
import pytest
import requests
from openpyxl import Workbook

from nhs_ae.features.hierarchy import LEGACY, UNMAPPED, current_icb_map, icb_region_map
from nhs_ae.ingest import icb_mapping as im

UP = im.UPLOAD_BASE
V1_URL = UP + "2025/06/System-Mapping.xls"             # FY 2025-26, "42-ICB" structure
V2_URL = UP + "2026/05/System-Mapping-Apr-26.xls"      # FY 2026-27, after the mergers
ATT_URL = UP + "2026/08/Acute-Trust-Attribution-File.xls"
LON, SE = "London Commissioning Region", "South East Commissioning Region"


# ---- synthetic workbooks ---------------------------------------------------------------
def mapping_xlsx(rows, last_updated="26th June 2022", title="Mapping A&E Providers to ICBs"):
    wb = Workbook()
    ws = wb.active
    ws.title = "ICB Mapping"
    ws["B2"], ws["C2"] = "Title:", title
    ws["B4"], ws["C4"] = "Last Updated:", last_updated
    ws["B6"] = "Contact:"
    for j, h in enumerate(["Code", "Name", "ICB Code", "ICB Name", "Region Name"]):
        ws.cell(row=8, column=2 + j, value=h)
    for i, r in enumerate(rows):
        for j, v in enumerate(r):
            ws.cell(row=9 + i, column=2 + j, value=v)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def attribution_xlsx(stp_rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "STP Mapping"
    for j, h in enumerate(["Org code", "Region", "Name", "STP"]):
        ws.cell(row=3, column=1 + j, value=h)
    ws.cell(row=3, column=8, value="STP Code")          # side table the parser must ignore
    ws.cell(row=4, column=7, value="Alpha STP")
    ws.cell(row=4, column=8, value="E54999001")
    for i, r in enumerate(stp_rows):
        for j, v in enumerate(r):
            ws.cell(row=4 + i, column=1 + j, value=v)
    wb.create_sheet("Attribution")["B2"] = "Title:"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def icb(code, name):
    return code, f"NHS {name} Integrated Care Board"


V1_ROWS = [
    ("RAA", "Synthetic Trust A", *icb("QAA", "Alpha"), LON),
    ("RBB", "Synthetic Trust B", *icb("QBB", "Beta"), LON),
    ("RCC", "Synthetic Trust C", *icb("QCC", "Gamma"), LON),
    ("RDD", "Synthetic Trust D", *icb("QCC", "Gamma"), LON),   # gone by v2
    ("REE", "Synthetic UTC E", *icb("QSP", "Split"), LON),
    ("RFF", "Synthetic UTC F", *icb("QSP", "Split"), LON),
    ("RHH", "Synthetic WIC H", *icb("QSP", "Split"), LON),     # gone by v2, ICB split
    ("RGG", "Synthetic Trust G", *icb("QDD", "Delta"), SE),
]
V2_ROWS = [
    ("RAA", "Synthetic Trust A", *icb("QAA", "Alpha"), LON),
    ("RBB", "Synthetic Trust B", *icb("QNW", "New"), LON),     # QBB + QCC merged
    ("RCC", "Synthetic Trust C", *icb("QNW", "New"), LON),
    ("REE", "Synthetic UTC E", *icb("QAA", "Alpha"), LON),     # QSP split
    ("RFF", "Synthetic UTC F", *icb("QNW", "New"), LON),
    ("rgg", "Synthetic Trust G", *icb("QDD", "Delta"), SE),     # lower-case code
    ("rgg", "Synthetic Trust G", *icb("QDD", "Delta"), SE),     # exact duplicate row
]
STP_ROWS = [
    ("RAA", "LONDON COMMISSIONING REGION", "SYNTHETIC TRUST A", "Alpha STP"),
    ("ROLD1", "LONDON COMMISSIONING REGION", "SYNTHETIC OLD WIC 1", "Alpha STP "),
    ("RBB", "LONDON COMMISSIONING REGION", "SYNTHETIC TRUST B", "Mixed STP"),
    ("REE", "LONDON COMMISSIONING REGION", "SYNTHETIC UTC E", "Mixed STP"),
    ("ROLD2", "LONDON COMMISSIONING REGION", "SYNTHETIC OLD WIC 2", "Mixed STP"),
    ("RMERGED", "LONDON COMMISSIONING REGION", "SYNTHETIC MERGED TRUST", "Mixed STP"),
    ("RBURTON", "LONDON COMMISSIONING REGION", "SYNTHETIC CROSS-BORDER TRUST", "Alpha STP"),
]


def succ(*targets):
    return {"Organisation": {"Succs": {"Succ": [
        {"Type": "Successor", "Target": {"OrgId": {"extension": t}},
         "Date": [{"Type": "Legal", "Start": "2020-04-01"}]} for t in targets]}}}


ODS = {"RMERGED": succ("RGG"),     # STP ambiguous, successor decides
       "RBURTON": succ("RCC"),     # STP says Alpha, successor says New: successor wins
       "ROLD3": succ("RDD"),       # chain through a defunct code in an earlier version
       "RSPLIT": succ("RAA", "RGG"),   # successors disagree: unassigned
       "RGONE": {"_error": "404 Client Error"}}


# ---- fakes -----------------------------------------------------------------------------
class FakeResp:
    def __init__(self, content=b"", status=200, headers=None, js=None):
        self.content, self.status_code, self.headers, self._js = content, status, headers or {}, js

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)

    def json(self):
        return self._js


class FakeSession:
    def __init__(self, routes):
        self.routes, self.headers, self.calls = routes, {}, []

    def get(self, url, headers=None, timeout=None, params=None):
        self.calls.append(url)
        return self.routes.get(url, FakeResp(status=404))

    def head(self, url, headers=None, timeout=None, allow_redirects=False):
        return FakeResp(status=200 if url in self.routes else 404)


def lm(d):  # an HTTP Last-Modified header for a date
    return {"Last-Modified": f"{d:%a, %d %b %Y} 08:00:00 GMT"}


@pytest.fixture()
def archive(tmp_path):
    """Fetch the synthetic files through fetch_and_store and build the reference tables."""
    raw, manifest, ref, ods = (tmp_path / "raw", tmp_path / "manifest.jsonl", tmp_path / "ref",
                               tmp_path / "ods.json")
    routes = {
        V1_URL: FakeResp(mapping_xlsx(V1_ROWS, "12th June 2025"), headers=lm(date(2025, 6, 12))),
        V2_URL: FakeResp(mapping_xlsx(V2_ROWS, "14 May 2026"), headers=lm(date(2026, 5, 14))),
        ATT_URL: FakeResp(attribution_xlsx(STP_ROWS), headers=lm(date(2026, 8, 13)))}
    s = FakeSession(routes)
    seen: dict = {}
    for url, kind in ((V1_URL, im.SYSTEM_MAPPING), (V2_URL, im.SYSTEM_MAPPING),
                      (ATT_URL, im.TYPE3_ATTRIBUTION)):
        im.fetch_and_store(im.MappingRef(url, kind), s, raw, manifest, seen)
    ods.write_text(json.dumps(ODS))
    summary = im.build(manifest, raw, ref, ods)
    return {"raw": raw, "manifest": manifest, "ref": ref, "ods": ods, "summary": summary}


# ---- links and dates -------------------------------------------------------------------
def test_classify_and_extract_links():
    rel = "/statistics/wp-content/uploads/sites/2/2026/06/System-Mapping-Apr-26.xls"
    html = f"""<ul>
      <li><a href="{UP}2023/02/Trust-ICB-Attribution-File.xls">System Mapping File (XLS)</a></li>
      <li><a href="{rel}">System Mapping File</a></li>
      <li><a href="{ATT_URL}">Type 3 Trust Attribution File (XLS, 135KB)</a></li>
      <li><a href="{UP}2026/08/Monthly-AE-July-2026.csv">Monthly A&amp;E July 2026 (CSV)</a></li>
      <li><a href="{UP}2026/08/Statistical-commentary.pdf">Mapping commentary (PDF)</a></li></ul>"""
    base = "https://www.england.nhs.uk/statistics/x/"
    refs = im.extract_mapping_refs(html, "2026-27", base_url=base)
    assert [(r.filename, r.kind) for r in refs] == [
        ("Trust-ICB-Attribution-File.xls", im.SYSTEM_MAPPING),   # "ICB" beats "Attribution"
        ("System-Mapping-Apr-26.xls", im.SYSTEM_MAPPING),
        ("Acute-Trust-Attribution-File.xls", im.TYPE3_ATTRIBUTION)]
    assert refs[1].url == UP + "2026/06/System-Mapping-Apr-26.xls"     # relative href resolved
    assert refs[0].linked_from == "2026-27" and refs[0].discovered_via == "live_page"


def test_dates_and_probe_candidates():
    assert im.data_period(V2_URL) == date(2026, 4, 1)                   # month before upload
    assert im.data_period(UP + "2024/01/System-Mapping.xls") == date(2023, 12, 1)
    assert im.financial_year_of(date(2026, 3, 1)) == "2025-26"
    assert im.valid_from(date(2026, 4, 1)) == date(2026, 4, 1)
    assert im.valid_from(date(2023, 1, 1)) == date(2022, 7, 1)          # ICBs exist from July 2022
    assert im.parse_last_updated("26th June 2022") == date(2022, 6, 26)
    assert im.parse_last_updated("14 May 2026") == date(2026, 5, 14)
    assert im.parse_last_updated("soon") is None
    cands = im.probe_candidates(date(2026, 5, 1), date(2026, 6, 30))
    assert UP + "2026/05/System-Mapping-Apr-26.xls" in cands
    assert UP + "2026/06/System-Mapping.xls" in cands
    assert all(c.startswith(UP + "2026/0") for c in cands)
    found = im.probe_refs(FakeSession({UP + "2026/05/System-Mapping-Apr-26.xls": FakeResp()}),
                          cands, delay=0)
    assert [r.discovered_via for r in found] == ["url_probe"]


# ---- parsing ---------------------------------------------------------------------------
def test_parse_system_mapping_quirks():
    old_label = "North of England Commissioning Region"
    rows = [*V2_ROWS, ("NTV0b", "Synthetic WIC", *icb("QDD", "Delta"), old_label)]
    df, meta = im.parse_system_mapping(mapping_xlsx(rows, "14 May 2026"))
    assert list(df["org_code"]) == ["RAA", "RBB", "RCC", "REE", "RFF", "RGG", "NTV0B"]  # dedup
    assert df.set_index("org_code").loc["RGG", "region"] == "SOUTH EAST"
    assert df.set_index("org_code").loc["NTV0B", "region"] == LEGACY          # pre-2019 label
    assert meta == {"title": "Mapping A&E Providers to ICBs", "last_updated_text": "14 May 2026",
                    "last_updated": date(2026, 5, 14)}
    clash = [*V2_ROWS, ("RAA", "Synthetic Trust A", *icb("QNW", "New"), LON)]
    with pytest.raises(ValueError, match="RAA"):
        im.parse_system_mapping(mapping_xlsx(clash))


def test_parse_stp_sheet_ignores_side_table():
    stp = im.parse_stp_sheet(attribution_xlsx(STP_ROWS))
    assert len(stp) == len(STP_ROWS) and set(stp["stp_name"]) == {"Alpha STP", "Mixed STP"}
    assert stp.set_index("org_code").loc["ROLD1", "stp_name"] == "Alpha STP"   # trailing space


# ---- archive ---------------------------------------------------------------------------
def test_fetch_and_store_is_immutable(tmp_path):
    raw, manifest = tmp_path / "raw", tmp_path / "m.jsonl"
    body = mapping_xlsx(V2_ROWS)
    s = FakeSession({V2_URL: FakeResp(body, headers=lm(date(2026, 5, 14)))})
    rec = im.fetch_and_store(im.MappingRef(V2_URL, im.SYSTEM_MAPPING), s, raw, manifest)
    assert rec["stored"] and rec["path"] == "2026-05/System-Mapping-Apr-26.xls"
    assert (rec["period"], rec["financial_year"]) == ("2026-04", "2026-27")
    assert rec["published"] == date(2026, 5, 14)
    assert rec["published_source"] == "http_last_modified"
    # identical bytes at another URL: recorded, not stored twice
    other = UP + "2026/06/System-Mapping-Apr-26.xls"
    s.routes[other] = FakeResp(body)
    dup = im.fetch_and_store(im.MappingRef(other, im.SYSTEM_MAPPING), s, raw, manifest)
    assert not dup["stored"] and dup["identical_to"] == rec["path"]
    assert dup["published_source"] == "upload_month_second_thursday"      # no Last-Modified
    # same URL, new bytes (never seen in practice): stored alongside, not overwritten
    s.routes[V2_URL] = FakeResp(mapping_xlsx(V1_ROWS))
    new = im.fetch_and_store(im.MappingRef(V2_URL, im.SYSTEM_MAPPING), s, raw, manifest)
    assert new["stored"] and new["path"] != rec["path"]
    assert (raw / rec["path"]).read_bytes() == body
    lines = [json.loads(x) for x in manifest.read_text().splitlines()]
    assert len(lines) == 3
    assert all({"url", "sha256", "fetched_at", "period", "published"} <= set(x) for x in lines)
    # a failed download is recorded with its error
    missing = im.MappingRef(UP + "2026/07/x.xls", im.SYSTEM_MAPPING)
    bad = im.fetch_and_store(missing, s, raw, manifest)
    assert not bad["stored"] and "404" in bad["error"]


def test_fetch_ods_records_trims_and_follows_successors():
    full = {"Organisation": {**succ("RMID")["Organisation"], "Name": "SYNTHETIC OLD TRUST",
                             "Contacts": {"Contact": [{"type": "tel"}]}, "Rels": {"Rel": []}}}
    base = "https://directory.spineservices.nhs.uk/ORD/2-0-0/organisations/"
    s = FakeSession({base + "ROLD": FakeResp(js=full),
                     base + "RMID": FakeResp(js={"Organisation": succ("RNEW")["Organisation"]})})
    rec = im.fetch_ods_records(["ROLD", "RNONE"], {}, s, stop={"RNEW"}, delay=0)
    assert set(rec) == {"ROLD", "RMID", "RNONE"}                   # RNEW is in the target: stop
    assert set(rec["ROLD"]["Organisation"]) == {"Name", "Succs"}   # contacts/relations dropped
    assert "_error" in rec["RNONE"]
    assert im.ods_successors(rec) == {"ROLD": {"RMID"}, "RMID": {"RNEW"}}


# ---- build and backfill ----------------------------------------------------------------
def test_build_reference_tables(archive):
    ref, s = archive["ref"], archive["summary"]
    assert s["versions"] == 2 and s["current"] == "2026-05/System-Mapping-Apr-26.xls"
    cur = pd.read_csv(ref / im.CURRENT_CSV, dtype=str)
    required = {"org_code", "icb_code", "icb_name", "region", "source", "valid_from"}
    assert required <= set(cur.columns)
    assert list(cur["org_code"]) == ["RAA", "RBB", "RCC", "REE", "RFF", "RGG"]   # one row each
    assert set(cur["valid_from"]) == {"2026-04-01"} and set(cur["published"]) == {"2026-05-14"}
    assert cur["icb_code"].nunique() == 3
    hist = pd.read_csv(ref / im.HISTORY_CSV, dtype=str)
    assert hist.groupby("source")["org_code"].size().to_dict() == {
        "2025-06/System-Mapping.xls": 8, "2026-05/System-Mapping-Apr-26.xls": 6}
    assert set(hist["financial_year"]) == {"2025-26", "2026-27"}


def test_crosswalks():
    hist = pd.DataFrame(V1_ROWS, columns=["org_code", "org_name", "icb_code", "icb_name", "r"])
    tgt, _ = im.parse_system_mapping(mapping_xlsx(V2_ROWS))
    assert im.icb_crosswalk(hist, tgt) == {"QAA": "QAA", "QBB": "QNW", "QCC": "QNW",
                                           "QDD": "QDD", "QSP": None}      # QSP was split
    stp = im.parse_stp_sheet(attribution_xlsx(STP_ROWS))
    assert im.stp_crosswalk(stp, tgt) == {"Alpha STP": "QAA", "Mixed STP": None}


def test_backfill_methods(archive):
    fill = pd.read_csv(archive["ref"] / im.BACKFILL_CSV, dtype=str).set_index("org_code")
    got = fill[["icb_code", "method"]].apply(tuple, axis=1).to_dict()
    assert got == {
        "RDD": ("QNW", "earlier_mapping"),     # its ICB QCC merged into QNW
        "ROLD1": ("QAA", "legacy_stp"),        # every current Alpha-STP provider is in QAA
        "RMERGED": ("QDD", "ods_successor"),   # STP ambiguous; successor RGG decides
        "RBURTON": ("QNW", "ods_successor"),   # successor beats the STP (series continuity)
        "ROLD3": ("QNW", "ods_successor"),     # successor RDD resolved from the earlier file
    }
    # left out: RHH (its ICB was split), ROLD2 (mixed STP), RSPLIT (successors disagree)
    assert fill.loc["RMERGED", "icb_name"] == "NHS Delta Integrated Care Board"
    assert fill.loc["RMERGED", "region"] == "SOUTH EAST"


def test_load_reference_current_and_by_year(archive):
    ref, ods = archive["ref"], archive["ods"]
    cur = im.load_reference(reference_dir=ref, ods_path=ods)
    assert cur["method"].value_counts()["nhs_england_mapping"] == 6 and len(cur) == 11
    only = im.load_reference(backfill=False, reference_dir=ref, ods_path=ods)
    assert set(only["method"]) == {"nhs_england_mapping"}
    old = im.load_reference("2025-26", reference_dir=ref, ods_path=ods).set_index("org_code")
    assert old.loc[old["method"] == "nhs_england_mapping", "icb_code"].nunique() == 5
    assert old.loc["RBURTON", "icb_code"] == "QCC"      # backfill re-derived for that structure
    assert old.loc["ROLD3", "icb_code"] == "QCC"        # its successor RDD is in the v1 file
    assert "ROLD2" not in old.index and "RDD" in old.index
    with pytest.raises(ValueError):
        im.load_reference("2019-20", reference_dir=ref, ods_path=ods)


# ---- hierarchy -------------------------------------------------------------------------
def test_current_icb_map_case_insensitive_with_unmapped_bucket():
    mapping = pd.DataFrame({"org_code": ["RAA", "ntv0b", "RCC"], "icb_code": ["QAA", "QAA", "QBB"],
                            "icb_name": ["NHS Alpha", "NHS Alpha", "NHS Beta"],
                            "region": ["LONDON", "LONDON", "MIDLANDS"]})
    rows = pd.DataFrame({"org_code": ["RAA", "NTV0B", "RZZ", "ENGLAND"],
                         "is_total": [False, False, False, True]})
    m = current_icb_map(rows, mapping)
    assert m.to_dict() == {"RAA": "QAA", "NTV0B": "QAA", "RZZ": UNMAPPED}   # spelled as in data
    assert current_icb_map(rows, mapping, field="icb_name")["RAA"] == "NHS Alpha"
    assert current_icb_map(mapping=mapping)["NTV0B"] == "QAA"               # no rows: lookup
    assert icb_region_map(mapping).to_dict() == {"QAA": "LONDON", "QBB": "MIDLANDS"}
