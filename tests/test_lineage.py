from datetime import date

from nhs_ae.ingest.lineage import Succession, canonical_code_map, successions_from_record


def test_successions_and_chain_following():
    rec = {"Organisation": {"Succs": {"Succ": [
        {"Type": "Successor", "Target": {"OrgId": {"extension": "RNEW"}},
         "Date": [{"Type": "Legal", "Start": "2024-04-01"}]},
    ]}}}
    s = successions_from_record("ROLD", rec)
    assert s == [Succession("ROLD", "RNEW", date(2024, 4, 1), "Successor")]
    chain = [Succession("A", "B", None, "Successor"), Succession("B", "C", None, "Successor")]
    assert canonical_code_map(chain) == {"A": "C", "B": "C"}
