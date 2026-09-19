"""Stage H step 4 (design §2.4-§2.5, §5, §11 "Pools" and "MinT"), on synthetic data only.

Synthetic tables use real calendar dates. Every first release in them is for a period before
2024, as in the dry run (E = 2023-12), so the runner-side guards pass with token None; the one
exception is the run-mode test, which uses a fake token the guarded call is taken to have logged.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import stats
from test_g1 import ORIGINS as G1_ORIGINS
from test_g1 import _hierarchy

import nhs_ae.ingest.icb_mapping as im
from nhs_ae.calibrate import g1, online
from nhs_ae.calibrate.online import calibrate
from nhs_ae.config import PROJECT_ROOT
from nhs_ae.evaluate import g1_rerun, splits, stage_e, stage_f
from nhs_ae.evaluate.asof import load_asof
from nhs_ae.evaluate.harness import WINTER_MONTHS
from nhs_ae.evaluate.stage_h import pools
from nhs_ae.evaluate.stage_h.common import DEV, DRY_END, FR_START, INPUT_START, RUN_END, ts
from nhs_ae.features.hierarchy import current_region_map
from nhs_ae.ingest.recover import month_range, publication_date
from nhs_ae.models.base import QUANTILES

M = pd.DateOffset(months=1)
E = ts(DRY_END)                                               # 2023-12, the dry run's end origin
DEV_END = ts("2023-06-01")                                    # last origin of the synthetic DEV block
CONF_LIKE = pd.date_range("2023-07-01", E, freq="MS")         # the dry run's CONF-like origins
Z = stats.norm.ppf(QUANTILES)


# ---- a forecast table and its first releases ---------------------------------------------
def _fc_fr(first="2021-01-01", n_series=12, seed=0, end=E):
    """Provider forecasts at every origin first..end for h = 1-3 (period = origin + h - 1), and
    first releases published the month after each period, up to end (resolved <= end), so an
    h-step forecast resolves at origin + h."""
    rng = np.random.default_rng(seed)
    origins = pd.date_range(first, end, freq="MS")
    rows = [(o, "asof", "m", "provider", "att_all", f"S{s:02d}", h, o + (h - 1) * M, q,
             float(1000 * np.exp(0.05 * z)), 10.0)
            for o in origins for s in range(n_series) for h in (1, 2, 3) for q, z in zip(QUANTILES, Z)]
    fc = pd.DataFrame(rows, columns=stage_f.COLS)
    periods = pd.date_range(first, end - M, freq="MS")
    fr = pd.DataFrame([("att_all", f"S{s:02d}", p, float(1000 * np.exp(rng.normal(0, 0.1))), p + M)
                       for p in periods for s in range(n_series)],
                      columns=["target", "series", "period", "y_first", "resolved"])
    return fc, fr


def _window(t, h):
    return list(pd.date_range(t - (h + 11) * M, t - h * M, freq="MS"))


def test_pool_advances_at_each_conf_like_origin_and_a_frozen_table_is_detected():
    fc, fr = _fc_fr()
    trace = pools.pool_trace(fc, fr)
    for t in CONF_LIKE:
        for h in (1, 2, 3):
            assert trace[("att_all", t, h)] == _window(t, h), (t, h)
    assert trace[("att_all", CONF_LIKE[0], 1)][-1] == DEV_END                  # DEV forecasts feed the first
    assert trace[("att_all", E, 1)][-5:] == list(CONF_LIKE[:5])                # earlier CONF-like ones later
    assert pools.pool_origins(fc, fr, "att_all", 2, CONF_LIKE[3]) == _window(CONF_LIKE[3], 2)
    # negative control: first releases frozen at the end of DEV, as the old caches are
    frozen = pools.pool_trace(fc, fr[fr["resolved"] <= DEV_END])
    for h in (1, 2, 3):
        pools_h = [frozen[("att_all", t, h)] for t in CONF_LIKE]
        assert all(p != _window(t, h) for p, t in zip(pools_h, CONF_LIKE))    # detected at every origin
        assert all(p == _window(DEV_END, h) for p in pools_h)                  # the pool never moves


def test_trace_changes_no_calibrated_value():
    fc, fr = _fc_fr(first="2022-01-01", n_series=4)
    trace: dict = {}
    pd.testing.assert_frame_equal(calibrate(fc, fr), calibrate(fc, fr, trace=trace))
    assert all(isinstance(k[1], pd.Timestamp) and isinstance(k[2], int) for k in trace)
    assert all(v == sorted(v) and len(v) <= 12 for v in trace.values())


# ---- a vintage table with a late submitter and three lost originals ----------------------
PROVIDERS = {"RAA": "NHS England London", "RBB": "NHS England London", "RCC": "NHS ENGLAND MIDLANDS (WEST)",
             "RDD": "NHS ENGLAND MIDLANDS (WEST)", "RXX": "NHS England London"}
MAPPING = pd.DataFrame({"org_code": ["RAA", "RBB", "RCC", "RDD"], "icb_code": ["QAA", "QAA", "QBB", "QCC"],
                        "region": ["LONDON", "LONDON", "MIDLANDS", "MIDLANDS"]})     # RXX: in no ICB
REGIONS = pd.Series({"QAA": "LONDON", "QBB": "MIDLANDS", "QCC": "MIDLANDS"})
LOST = pd.date_range("2018-07-01", "2018-09-01", freq="MS")   # originals lost; first seen with 2018-10's file
LATE = {("RCC", ts("2018-03-01")), ("RBB", ts("2018-11-01")),   # absent from the original release;
        ("RCC", ts("2019-04-01"))}                               # this one is revised only after E
V_END = ts("2019-06-01")
METRICS = ("att_type1", "att_type2", "att_other", "adm_via_ae_type1", "adm_via_ae_type2", "adm_via_ae_other")


def _vintages(last=V_END) -> pd.DataFrame:
    """Periods 2017-01..last, each published on the second Thursday of the next month and revised
    (+5) at the next May or November release; LATE provider-months appear only in the revision;
    the LOST periods first appear on 2018-10's publication day (the 2025-07..09 case, with origins
    2018-08..10 truncated to 2018-06)."""
    rng = np.random.default_rng(0)
    rows = []
    for i, p in enumerate(pd.date_range("2017-01-01", last, freq="MS")):
        pub = pd.Timestamp(publication_date((LOST[-1] + M if p in LOST else p).date()))
        rev = next(d for d in pd.date_range(pub, periods=13, freq="MS") if d.month in (5, 11))
        rev += pd.Timedelta(days=12)
        for j, (org, parent) in enumerate(PROVIDERS.items()):
            season = 1 + 0.1 * np.sin(2 * np.pi * p.month / 12)
            att1 = (500 + 200 * j) * (1 + 0.004 * i) * season + rng.normal(0, 5)
            for snap, bump in ([(rev, 5.0)] if (org, p) in LATE else [(pub, 0.0), (rev, 5.0)]):
                vals = (att1 + bump, 40.0 + j, 150.0 + bump, 0.3 * att1, 1.0, 2.0 + j)
                rows += [(p, org, parent, f"Trust {org}", m, v, False, snap) for m, v in zip(METRICS, vals)]
    return pd.DataFrame(rows, columns=["period", "org_code", "parent_org", "org_name", "metric", "value",
                                       "is_total", "snapshot"])


@pytest.fixture(scope="module")
def vint():
    mp = pytest.MonkeyPatch()
    mp.setattr(im, "load_reference", lambda *a, **k: MAPPING)
    v = _vintages()
    rmap = current_region_map(v)
    yield v, rmap, pools.first_release_tables(v, V_END, rmap, REGIONS, None)
    mp.undo()


def _published(v, rmap, t, level, target) -> pd.Series:
    """Every cell the as-of data at origin t hold, periods from INPUT_START, keyed (period, series)."""
    p = load_asof(t.date(), "asof", v, rmap).panel(target, level)
    s = p.loc[p.index >= ts(INPUT_START)].stack(future_stack=True).dropna()
    return s[~s.index.get_level_values(1).isin(pools.EXCLUDE)]


def test_first_release_at_t_holds_every_period_published_by_t(vint):
    v, rmap, fr = vint
    icb_fr = fr["icb"]
    kids = {"region": REGIONS.groupby(REGIONS).groups, "england": {"ENGLAND": list(REGIONS.index)}}
    for t in pd.date_range(FR_START, V_END, freq="MS"):
        for target in ("att_all", "adm_via_ae"):
            for lv in ("provider", "icb"):
                pub = _published(v, rmap, t, lv, target)
                f = fr[lv][(fr[lv]["target"] == target) & (fr[lv]["resolved"] <= t)]
                assert set(zip(f["period"], f["series"])) == set(pub.index), (t, target, lv)
                new = f[f["resolved"] == t]                                  # value as published at t
                np.testing.assert_allclose(new["y_first"], pub.loc[list(zip(new["period"], new["series"]))])
            icb_pub = set(_published(v, rmap, t, "icb", target).index)
            for lv, tree in kids.items():
                f = fr[lv][(fr[lv]["target"] == target) & (fr[lv]["resolved"] <= t)]
                periods = {p for p, _ in icb_pub}
                want = {(p, a) for a, icbs in tree.items() for p in periods
                        if all((p, i) in icb_pub for i in icbs)}
                assert set(zip(f["period"], f["series"])) == want, (t, target, lv)
    # aggregates: y_first is the sum of the ICBs' first releases, resolved their maximum
    for lv, agg in (("region", icb_fr["series"].map(REGIONS)), ("england", "ENGLAND")):
        exp = (icb_fr.assign(agg=agg).groupby(["target", "agg", "period"])
               .agg(y=("y_first", "sum"), r=("resolved", "max"), n=("y_first", "size")).reset_index())
        exp = exp[exp["n"] == exp["agg"].map({"LONDON": 1, "MIDLANDS": 2, "ENGLAND": 3})]
        got = fr[lv].merge(exp, left_on=["target", "series", "period"],
                           right_on=["target", "agg", "period"])
        assert len(got) == len(fr[lv]) == len(exp) > 0
        np.testing.assert_allclose(got["y_first"], got["y"])
        assert (got["resolved"] == got["r"]).all()


def test_late_submitter_and_lost_originals_at_every_level(vint):
    v, rmap, fr = vint

    def cell(lv, series, period, col="resolved"):
        f = fr[lv]
        r = f.loc[(f["target"] == "att_all") & (f["series"] == series) & (f["period"] == ts(period)), col]
        return r.iloc[0] if len(r) else None

    # RCC (QBB's only provider) misses 2018-03's original and appears in the May revision
    assert cell("provider", "RCC", "2018-03-01") == ts("2018-06-01")
    assert cell("provider", "RDD", "2018-03-01") == ts("2018-04-01")
    assert cell("icb", "QBB", "2018-03-01") == ts("2018-06-01")
    assert cell("region", "MIDLANDS", "2018-03-01") == ts("2018-06-01")        # max over QBB, QCC
    assert cell("england", "ENGLAND", "2018-03-01") == ts("2018-06-01")
    assert cell("region", "LONDON", "2018-03-01") == ts("2018-04-01")
    # RBB late in 2018-11: QAA resolves on time with RAA's value alone (first-published semantics)
    assert cell("provider", "RBB", "2018-11-01") == ts("2019-06-01")
    assert cell("icb", "QAA", "2018-11-01") == ts("2018-12-01")
    y = {(lv, s, p): cell(lv, s, p, "y_first") for lv, s in (("icb", "QAA"), ("provider", "RAA"), ("provider", "RBB"))
         for p in ("2018-10-01", "2018-11-01")}
    assert y[("icb", "QAA", "2018-11-01")] == pytest.approx(y[("provider", "RAA", "2018-11-01")])
    assert y[("icb", "QAA", "2018-10-01")] == pytest.approx(y[("provider", "RAA", "2018-10-01")]
                                                            + y[("provider", "RBB", "2018-10-01")])
    # QBB unresolved by E: MIDLANDS and England get no first release (Stage F's rule would sum QCC alone)
    assert cell("icb", "QBB", "2019-04-01") is None and cell("icb", "QCC", "2019-04-01") == ts("2019-05-01")
    assert cell("region", "MIDLANDS", "2019-04-01") is None and cell("england", "ENGLAND", "2019-04-01") is None
    assert cell("region", "LONDON", "2019-04-01") == ts("2019-05-01")
    # the three lost originals resolve together at 2018-11; the truncated origins resolve nothing
    for lv, series in (("provider", "RAA"), ("icb", "QCC"), ("region", "LONDON"), ("england", "ENGLAND")):
        assert {cell(lv, series, p) for p in LOST} == {ts("2018-11-01")}
        assert not fr[lv]["resolved"].isin(pd.date_range("2018-08-01", "2018-10-01", freq="MS")).any()
    assert "UNMAPPED" not in set(fr["icb"]["series"])
    # the table stops at E: ending at 2018-10 (like E = 2025-09) leaves the lost periods out entirely
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(im, "load_reference", lambda *a, **k: MAPPING)
        short = pools.first_release_tables(v, date(2018, 10, 1), rmap, REGIONS, None)
    key, cols = ["target", "series", "period"], ["target", "series", "period", "y_first", "resolved"]
    for lv in pools.LEVELS:
        assert short[lv]["resolved"].max() <= ts("2018-10-01") and not short[lv]["period"].isin(LOST).any()
        prefix = fr[lv][fr[lv]["resolved"] <= ts("2018-10-01")]
        pd.testing.assert_frame_equal(short[lv].sort_values(key).reset_index(drop=True)[cols],
                                      prefix.sort_values(key).reset_index(drop=True)[cols])


def test_pool_freezes_at_truncated_origins_and_jumps_when_the_lost_months_appear(vint):
    """The synthetic analogue of 2025-07..09 (and of DEV's 2018-11/12, 2021-10/11)."""
    v, rmap, fr = vint
    rows = []
    for t in pd.date_range(FR_START, V_END, freq="MS"):
        d = load_asof(t.date(), "asof", v, rmap)
        for s in d.panel("att_all", "provider").columns:
            for h in (1, 2):
                rows += [(t, "asof", "m", "provider", "att_all", s, h, d.last_period + h * M, q,
                          900.0 * np.exp(0.05 * z), 1.0) for q, z in zip(QUANTILES, Z)]
    fc = pd.DataFrame(rows, columns=stage_f.COLS)
    trace = pools.pool_trace(fc, fr["provider"])
    newest = {t: trace[("att_all", t, 1)][-1] for t in pd.date_range("2018-06-01", "2019-01-01", freq="MS")}
    assert newest[ts("2018-07-01")] == ts("2018-06-01")
    for t in ("2018-08-01", "2018-09-01", "2018-10-01"):                       # truncated: frozen
        assert trace[("att_all", ts(t), 1)] == trace[("att_all", ts("2018-07-01"), 1)]
    assert newest[ts("2018-11-01")] == ts("2018-10-01")                        # jumps four origins
    assert newest[ts("2018-12-01")] == ts("2018-11-01")


# ---- invariance of DEV-origin rows -------------------------------------------------------
def test_dev_calibration_unchanged_when_conf_like_origins_and_later_releases_are_appended():
    fc, fr = _fc_fr()
    late = fr["series"].isin(["S00", "S01"]) & fr["period"].between("2023-01-01", "2023-04-01")
    fr.loc[late, "resolved"] = ts("2023-09-01")                                 # late submissions
    failed = fc.loc[(fc["origin"] == ts("2022-05-01")) & (fc["series"] == "S03"), [*g1.KEY, "level"]]
    failed = failed.drop_duplicates()
    long = pools.calibrate_population(fc, fr, failed, "stage_d", "provider", None, None)
    short = pools.calibrate_population(fc[fc["origin"] <= DEV_END], fr[fr["resolved"] <= DEV_END], failed,
                                       "stage_d", "provider", None, None)
    key = ["origin", "series", "horizon", "quantile"]
    dev = long[long["origin"] <= DEV_END].sort_values(key).reset_index(drop=True)
    pd.testing.assert_frame_equal(dev, short.sort_values(key).reset_index(drop=True))
    later = long[long["origin"] > DEV_END].sort_values(key).reset_index(drop=True)
    assert len(later) and not np.allclose(later["value"], fc[fc["origin"] > DEV_END].sort_values(key)["value"])


ICB_OF = {"P1": "I1", "P2": "I1", "P3": "I2"}
REGION_OF = {"I1": "R1", "I2": "R1"}
TREE = {"P1": ("provider", 100.0), "P2": ("provider", 200.0), "P3": ("provider", 300.0), "I1": ("icb", 300.0),
        "I2": ("icb", 300.0), "R1": ("region", 600.0), "ENGLAND": ("england", 600.0)}


def _tree(first="2021-01-01", zero=(), end=E):
    """Calibrated forecasts (h = 1, 2) and first releases at every level, origins first..end."""
    rng = np.random.default_rng(1)
    cal, fr = [], []
    for o in pd.date_range(first, end, freq="MS"):
        for s, (lv, b) in TREE.items():
            for h in (1, 2):
                vals = np.zeros(9) if (o, s) in zero else b * np.exp(0.05 * Z + rng.normal(0, 0.03))
                cal += [(o, "asof", "m+pooled", lv, "att_all", s, h, o + (h - 1) * M, q, v, 1.0)
                        for q, v in zip(QUANTILES, vals)]
            if o < end:
                fr.append(("att_all", s, o, b * np.exp(rng.normal(0, 0.05)), o + M, lv))
    cal = pd.DataFrame(cal, columns=stage_f.COLS)
    fr = pd.DataFrame(fr, columns=["target", "series", "period", "y_first", "resolved", "level"])
    return ({lv: cal[cal["level"] == lv] for lv in stage_f.LEVELS},
            {lv: fr[fr["level"] == lv] for lv in stage_f.LEVELS})


def test_dev_reconciliation_unchanged_when_conf_like_origins_are_appended(monkeypatch):
    monkeypatch.setattr(stage_f, "TARGETS", ["att_all"])
    t_fail = ts("2022-03-01")
    cal, fr = _tree(zero={(t_fail, "P1")})
    p = fr["provider"]
    late = (p["series"] == "P2") & (p["period"] == ts("2023-05-01"))           # a late submission
    fr["provider"] = p.assign(resolved=p["resolved"].where(~late, ts("2023-10-01")))
    failed = {lv: pd.DataFrame(columns=[*g1.KEY, "level"]) for lv in stage_f.LEVELS}
    failed["provider"] = pd.DataFrame([(t_fail, "att_all", "P1", h, "provider") for h in (1, 2)],
                                      columns=[*g1.KEY, "level"])
    every = month_range(date(2021, 7, 1), E.date())
    dev = [o for o in every if ts(o) <= DEV_END]
    long = pools.reconcile(cal, fr, failed, every, ICB_OF, REGION_OF, None)
    short = pools.reconcile({lv: c[c["origin"] <= DEV_END] for lv, c in cal.items()},
                           {lv: f[f["resolved"] <= DEV_END] for lv, f in fr.items()}, failed, dev,
                           ICB_OF, REGION_OF, None)
    key = ["origin", "series", "horizon", "quantile"]
    pd.testing.assert_frame_equal(long[long["origin"] <= DEV_END].sort_values(key).reset_index(drop=True),
                                  short.sort_values(key).reset_index(drop=True))
    assert set(long["origin"]) == set(map(ts, every))
    p1 = long[(long["origin"] == t_fail) & (long["series"] == "P1")]
    assert len(p1) == 18 and (p1["value"] == 0).all()                           # G1: issued as produced


def test_reconcile_frames_reproduces_reconcile_model(tmp_path):
    for zero in (set(), {(G1_ORIGINS[4], "P1"), (G1_ORIGINS[6], "ENGLAND")}):
        failed = None
        if zero:
            failed = {lv: pd.DataFrame(columns=[*g1.KEY, "level"]) for lv in stage_f.LEVELS}
            failed["provider"] = pd.DataFrame([(G1_ORIGINS[4], "att_all", "P1", 1, "provider")],
                                              columns=[*g1.KEY, "level"])
            failed["england"] = pd.DataFrame([(G1_ORIGINS[6], "att_all", "ENGLAND", 1, "england")],
                                             columns=[*g1.KEY, "level"])
        with pytest.MonkeyPatch.context() as mp:
            cal, _ = _hierarchy(mp, zero=zero)
            model = stage_f.reconcile_model("m", None, origins=list(G1_ORIGINS), work=tmp_path, failed=failed)
            args = ({lv: cal[cal["level"] == lv] for lv in stage_f.LEVELS},
                    {lv: stage_f.first_release_level(lv) for lv in stage_f.LEVELS},
                    failed, list(G1_ORIGINS), stage_f.members(None).to_dict(),
                    stage_f.icb_region_map().to_dict())
            frames = stage_f.reconcile_frames(*args)
            via_pools = pools.reconcile(*args, None)
        pd.testing.assert_frame_equal(model, frames)
        pd.testing.assert_frame_equal(model, via_pools)


INCOHERENT = ts("2023-02-01")                                     # a ladder origin where "B" is incoherent


def _f2_frames():
    """Median forecasts and scores of contenders "A" and "B" and of the reference, h = 1 and 3,
    at every origin 2022-01..E (ladder and off-ladder). Medians are coherent except B's I1 at
    INCOHERENT (twice its providers' sum); A's WIS is 0.9 and B's 1.2 times the reference's."""
    rng = np.random.default_rng(2)
    fcs, scored = {"A": [], "B": []}, {"A": [], "B": [], stage_f.F2_REFERENCE: []}
    for o in pd.date_range("2022-01-01", E, freq="MS"):
        for s, (lv, b) in TREE.items():
            for h in (1, 3):
                p = o + (h - 1) * M
                wis, cov = b * 0.05 * np.exp(rng.normal(0, 0.2)), (rng.random(2) < (0.9, 0.5)).astype(float)
                for label, k in ((stage_f.F2_REFERENCE, 1.0), ("A", 0.9), ("B", 1.2)):
                    scored[label].append((o, lv, "att_all", s, h, p, k * wis, *cov, p.month in WINTER_MONTHS))
                for label in ("A", "B"):
                    med = 2 * b if (label, o, s) == ("B", INCOHERENT, "I1") else b
                    fcs[label].append((o, "asof", label, lv, "att_all", s, h, p, 0.5, med, 1.0))
    cols = ["origin", "level", "target", "series", "horizon", "period", "wis", "cov90", "cov50", "winter"]
    return ({k: pd.DataFrame(r, columns=stage_f.COLS) for k, r in fcs.items()},
            {k: pd.DataFrame(r, columns=cols) for k, r in scored.items()})


def test_f2_table_default_is_the_ladder_and_origins_restrict_every_frame(monkeypatch):
    monkeypatch.setattr(stage_f, "TARGETS", ["att_all"])
    fcs, scored = _f2_frames()
    seen, real = [], stage_f.paired_bootstrap

    def spy(a, b, **k):                                                          # a: the reference
        seen.append(set(a["origin"]) | set(b["origin"]))
        return real(a, b, **k)
    monkeypatch.setattr(stage_f, "paired_bootstrap", spy)
    ladder = set(map(ts, stage_e.ladder_origins()))
    default = stage_f.f2_table(fcs, scored, ICB_OF, REGION_OF)
    pd.testing.assert_frame_equal(default, stage_f.f2_table(fcs, scored, ICB_OF, REGION_OF,
                                                            origins=stage_e.ladder_origins()))
    sub = [date(2022, 10, 1), date(2022, 12, 1)]                                # winter h=3 periods 2022-12, 2023-02
    seen.clear()
    t = stage_f.f2_table(fcs, scored, ICB_OF, REGION_OF, origins=sub)
    assert seen and all(s <= set(map(ts, sub)) for s in seen)                   # the reference restricted too
    for table, keep in ((default, ladder), (t, set(map(ts, sub)))):
        assert len(table) == 6
        for label, lv, n in table[["model", "level", "n"]].itertuples(index=False):
            s = scored[label][scored[label]["level"] == lv]
            assert n == s["origin"].isin(keep).sum() < len(s), (label, lv)
    d, t = default.set_index(["model", "level"]), t.set_index(["model", "level"])
    assert INCOHERENT in ladder and d.loc[("B", "icb"), "coh_gap_max"] == pytest.approx(0.5)
    assert t.loc[("B", "icb"), "coh_gap_max"] == 0 and t.loc[("A", "icb"), "coh_gap_max"] == 0
    assert t.loc[("A", "icb"), "wis_rel_m1"] == pytest.approx(-0.1)
    assert t.loc[("B", "england"), "wis_rel_m1"] == pytest.approx(0.2)


# ---- the runner-side guards ----------------------------------------------------------------
def test_guard_first_releases_raises_on_a_sealed_period_without_a_token():
    f = pd.DataFrame({"period": pd.to_datetime(["2023-11-01", "2024-01-01"]), "y_first": [1.0, 2.0]})
    with pytest.raises(splits.SealedOriginError):
        pools.guard_first_releases(f, None)
    pools.guard_first_releases(f.iloc[:1], None)                                # pre-2024 passes
    pools.guard_first_releases(f.assign(y_first=[1.0, np.nan]), None)           # no first release, no score


def test_calibration_and_mint_run_the_guard(monkeypatch):
    fc, fr = _fc_fr(first="2022-06-01", n_series=3)
    leak = fr.iloc[:1].assign(period=ts("2024-01-01"), resolved=E)              # a first release for 2024-01
    with pytest.raises(splits.SealedOriginError):
        pools.calibrate_population(fc, pd.concat([fr, leak]), None, "stage_d", "provider", None, None)
    with pytest.raises(splits.SealedOriginError):
        pools.pool_trace(fc, pd.concat([fr, leak]))
    monkeypatch.setattr(stage_f, "TARGETS", ["att_all"])
    cal, frs = _tree(first="2023-01-01")
    frs["icb"] = pd.concat([frs["icb"], frs["icb"].iloc[:1].assign(period=ts("2024-01-01"), resolved=E)])
    with pytest.raises(splits.SealedOriginError):
        pools.reconcile(cal, frs, None, month_range(date(2023, 7, 1), E.date()), ICB_OF, REGION_OF, None)


def test_builds_are_refused_beyond_e_before_any_data_are_read():
    """Negative control of §2.5: E = 2025-09 in dry mode. ``vintages`` is None, so only a refusal
    made before reading can raise SealedOriginError."""
    for build in (pools.first_release_tables, pools.last_observed):
        with pytest.raises(splits.SealedOriginError):
            build(None, RUN_END, None, None, None)
        with pytest.raises(splits.SealedOriginError):                             # origin 2024-01 is sealed
            build(None, date(2024, 1, 1), None, None, None)
        with pytest.raises(ValueError, match="beyond E"):
            build(None, date(2025, 11, 1), None, None, None)


def test_a_token_is_refused_before_the_guarded_call(monkeypatch):
    def never(*a, **k):
        raise AssertionError("assert_not_sealed must not be reached")
    monkeypatch.setattr(splits, "assert_not_sealed", never)
    monkeypatch.setattr(splits, "_logged_tokens", set())
    f = pd.DataFrame({"period": [ts("2023-11-01")], "y_first": [1.0]})
    with pytest.raises(RuntimeError, match="before the guarded call"):
        pools.guard_first_releases(f, "0" * 40)
    with pytest.raises(RuntimeError, match="before the guarded call"):
        pools.first_release_tables(None, DRY_END, None, None, "0" * 40)


def test_calibration_and_mint_origins_are_bounded(monkeypatch):
    """§2.4 in dry mode: a 2024 origin is refused before any calibration or MinT, even with no
    first release for a sealed period present (so §2.5's guard alone would let it through); an
    origin beyond RUN_END is refused too."""
    def never(*a, **k):
        raise AssertionError("calibration or MinT reached")
    monkeypatch.setattr(online, "calibrate", never)
    monkeypatch.setattr(stage_f, "reconcile_frames", never)
    fc, fr = _fc_fr(first="2022-06-01", n_series=3)                              # first releases to 2023-11
    for origin, err, match in (("2024-01-01", splits.SealedOriginError, "sealed"),
                               ("2025-10-01", ValueError, "beyond E")):
        more = pd.concat([fc, fc[fc["origin"] == E].assign(origin=ts(origin))])
        with pytest.raises(err, match=match):
            pools.calibrate_population(more, fr, None, "stage_d", "provider", None, None)
        with pytest.raises(err, match=match):
            pools.pool_trace(more, fr)
    cal, frs = _tree(first="2023-01-01")
    dry = month_range(date(2023, 7, 1), E.date())
    with pytest.raises(splits.SealedOriginError):                                 # an origin to reconcile at
        pools.reconcile(cal, frs, None, [*dry, date(2024, 1, 1)], ICB_OF, REGION_OF, None)
    c = cal["icb"]
    with pytest.raises(splits.SealedOriginError):                                 # a calibrated forecast's origin
        pools.reconcile({**cal, "icb": pd.concat([c, c[c["origin"] == E].assign(origin=ts("2024-01-01"))])},
                        frs, None, dry, ICB_OF, REGION_OF, None)


FAKE = "f" * 40


def test_a_logged_token_runs_every_build_past_2023(monkeypatch, tmp_path):
    """The run-mode path on synthetic data: with a token the guarded call has logged, every build
    reaches E = 2024-04 (periods to 2024-03) and nothing writes to the unseal log. The builds
    pass the token on, so the guards inside online and stage_f (P11) see it too: every call
    into them, pool_trace's included, carries it."""
    monkeypatch.setattr(splits, "_tag_commit", lambda tag=splits.CONF_TAG: FAKE)
    monkeypatch.setattr(splits, "_context_problems", lambda token, amendment: [])  # P11's seam
    monkeypatch.setattr(splits, "UNSEAL_LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(splits, "_logged_tokens", {FAKE})
    monkeypatch.setattr(splits, "_unseal_context", {})
    monkeypatch.setattr(im, "load_reference", lambda *a, **k: MAPPING)
    passed = []

    def spy(mod, name):
        real = getattr(mod, name)

        def call(*a, **k):
            passed.append((name, k.get("unseal_token")))
            return real(*a, **k)
        monkeypatch.setattr(mod, name, call)
    for mod, name in ((online, "first_release"), (online, "calibrate"), (stage_f, "reconcile_frames")):
        spy(mod, name)
    end = ts("2024-04-01")
    v = _vintages(last=ts("2024-05-01"))                                         # data beyond E exist
    rmap = current_region_map(v)
    fr = pools.first_release_tables(v, end.date(), rmap, REGIONS, FAKE)
    for lv, t in fr.items():
        assert t["period"].max() == ts("2024-03-01") and t["resolved"].max() == end, lv
    last = pools.last_observed(v, end.date(), rmap, REGIONS, FAKE)
    assert last["origin"].max() == end
    p = fr["provider"]
    first = p.loc[(p["target"] == "att_all") & (p["series"] == "RAA") & (p["period"] == ts("2024-03-01")), "y_first"]
    got = last.loc[(last["origin"] == end) & (last["level"] == "provider") & (last["target"] == "att_all")
                   & (last["series"] == "RAA"), "last_value"]
    assert got.item() == pytest.approx(first.item())                            # 2024-03 as first published
    fc, frp = _fc_fr(first="2023-01-01", n_series=3, end=end)                   # first releases to 2024-03
    cal = pools.calibrate_population(fc, frp, None, "stage_d", "provider", None, FAKE)
    assert cal["origin"].max() == end and len(cal) == len(fc)
    assert pools.pool_origins(fc, frp, "att_all", 1, end, token=FAKE)[-1] == ts("2024-03-01")
    monkeypatch.setattr(stage_f, "TARGETS", ["att_all"])
    calt, frt = _tree(first="2023-01-01", end=end)
    rec = pools.reconcile(calt, frt, None, month_range(date(2023, 7, 1), end.date()), ICB_OF, REGION_OF, FAKE)
    assert rec["origin"].max() == end
    assert not (tmp_path / "log.jsonl").exists() and splits._logged_tokens == {FAKE}
    assert list(splits._unseal_context) == [FAKE]
    # provider and ICB tables; calibrate_population and pool_trace; reconcile
    assert sorted(passed) == [("calibrate", FAKE)] * 2 + [("first_release", FAKE)] * 2 + [
        ("reconcile_frames", FAKE)]


# ---- aggregates, joins and G1 --------------------------------------------------------------
def test_aggregate_first_release_completeness_rule():
    p1, p2 = ts("2023-01-01"), ts("2023-02-01")
    r2, r3, r4 = ts("2023-02-01"), ts("2023-03-01"), ts("2023-04-01")
    icb = pd.DataFrame([("att_all", "QAA", p1, 10.0, r2), ("att_all", "QBB", p1, 20.0, r4),
                        ("att_all", "QCC", p1, 30.0, r2), ("att_all", "QAA", p2, 11.0, r3),
                        ("att_all", "QCC", p2, 31.0, r3), ("att_all", "UNMAPPED", p2, 99.0, r3)],
                       columns=["target", "series", "period", "y_first", "resolved"])
    reg = pools.aggregate_first_release(icb, REGIONS, "region").set_index(["series", "period"])
    assert reg.loc[("MIDLANDS", p1), "y_first"] == 50.0 and reg.loc[("MIDLANDS", p1), "resolved"] == r4
    assert ("MIDLANDS", p2) not in reg.index                                     # QBB has no 2023-02 yet
    assert reg.loc[("LONDON", p2), "y_first"] == 11.0
    eng = pools.aggregate_first_release(icb, REGIONS, "england")
    assert eng[["series", "period", "y_first", "resolved"]].values.tolist() == [["ENGLAND", p1, 60.0, r4]]
    with pytest.raises(ValueError, match="no first release"):                    # QDD could never resolve
        pools.aggregate_first_release(icb, pd.concat([REGIONS, pd.Series({"QDD": "LONDON"})]), "england")
    unplaced = pd.concat([icb, icb.iloc[:1].assign(series="QZZ")])     # an ICB the map lacks: region "?"
    assert set(pools.aggregate_first_release(unplaced, REGIONS, "region")["series"]) == {"LONDON", "MIDLANDS",
                                                                                         "?"}
    assert pools.aggregate_first_release(unplaced, REGIONS, "england")["y_first"].tolist() == [70.0]


def test_join_inputs_refuses_overlapping_origins_and_mixed_tables():
    fc, _ = _fc_fr(first="2023-01-01", n_series=2)
    inputs, new = fc[fc["origin"] <= DEV_END], fc[fc["origin"] > DEV_END]
    joined = pools.join_inputs(inputs, new, end=E)
    assert len(joined) == len(fc) and set(joined["origin"]) == set(fc["origin"])
    over = fc[fc["origin"] >= DEV_END]
    with pytest.raises(ValueError, match="in both"):
        pools.join_inputs(inputs, over)
    with pytest.raises(ValueError, match="in both"):                              # another unit: still seen
        pools.join_inputs(inputs.assign(origin=inputs["origin"].astype("datetime64[ns]")),
                          over.assign(origin=over["origin"].astype("datetime64[s]")))
    o = over["origin"]
    for hidden in (o.dt.date, o.dt.strftime("%Y-%m-%d"), o.dt.tz_localize("UTC")):  # would intersect as empty
        with pytest.raises(ValueError, match="tz-naive datetime64"):
            pools.join_inputs(inputs, over.assign(origin=hidden))
    with pytest.raises(ValueError, match="beyond E"):
        pools.join_inputs(inputs, new, end=date(2023, 9, 1))
    with pytest.raises(ValueError, match="beyond E"):                             # default: RUN_END
        pools.join_inputs(inputs, new.assign(origin=new["origin"] + pd.DateOffset(years=3)))
    for col, val in (("model", "other"), ("level", "icb"), ("mode", "final")):
        with pytest.raises(ValueError, match=col):
            pools.join_inputs(inputs, new.assign(**{col: val}))


def test_populations():
    fc, fr = _fc_fr(first="2022-06-01", n_series=4)
    members = pd.Series({"S00": "Q1", "S01": "Q1", "S02": "Q2"})
    d = pools.calibrate_population(fc, fr, None, "stage_d", "provider", members, None)
    f = pools.calibrate_population(fc, fr, None, "stage_f", "provider", members, None)
    assert set(d["series"]) == {"S00", "S01", "S02", "S03"} and set(f["series"]) == set(members.index)
    icb = fc.assign(level="icb", series=fc["series"].replace({"S03": "UNMAPPED"}))
    assert "UNMAPPED" not in set(pools.calibrate_population(icb, fr.assign(series=fr["series"].replace(
        {"S03": "UNMAPPED"})), None, "stage_f", "icb", None, None)["series"])
    with pytest.raises(ValueError, match="provider level only"):
        pools.calibrate_population(icb, fr, None, "stage_d", "icb", None, None)


def test_failed_tables_and_the_dev_count_check():
    def rows(origin, series, zero):
        vals = [0.0] * 9 if zero else list(np.linspace(1, 9, 9))
        return [(ts(origin), "asof", "b1_ets", "provider", "att_all", series, 1, ts(origin), q, v, 1.0)
                for q, v in zip(QUANTILES, vals)]
    base = pd.DataFrame(rows("2017-09-01", "A", True) + rows("2020-05-01", "A", True) + rows("2020-05-01", "B", True)
                        + rows("2024-02-01", "A", True) + rows("2020-06-01", "A", False), columns=stage_f.COLS)
    last = pd.DataFrame({"origin": pd.to_datetime(["2017-09-01", "2020-05-01", "2020-05-01", "2024-02-01"]),
                         "level": "provider", "target": "att_all", "series": ["A", "A", "B", "A"],
                         "last_value": [5.0, 5.0, 0.0, 5.0]})                   # B closed: not failed
    failed = pools.failed_tables({("b1", "provider"): base}, last)
    assert len(failed[("b1", "provider")]) == 3
    counts = pools.failed_counts(failed)
    cols = ["model", "failed", "failed_dev_origins", "failed_new_origins"]
    assert counts.iloc[0][cols].tolist() == ["ETS", 2, 1, 1]           # 2017-09 burn-in, 2020-05 DEV, 2024-02 new
    ref = pd.DataFrame({"model": ["ETS", "ETS"], "level": ["provider", "icb"], "failed": [2, 0],
                        "failed_dev_origins": [1, 0]})
    assert pools.failed_count_mismatches(counts, ref)["level"].tolist() == ["icb"]   # missing here: reported
    assert pools.failed_count_mismatches(counts, ref.iloc[:1]).empty
    assert pools.G1_COUNTS.relative_to(PROJECT_ROOT) == Path("results/F-reconciliation-G1/failed_counts.csv")
    # the reference row as the Stage F G1 re-run builds it, over the same base's input span
    _, row = g1_rerun._count("ETS", "provider", base[base["origin"] <= ts(DEV[-1])], last, True)
    assert {k: row[k] for k in ("model", "level", "failed", "failed_dev_origins")} == {
        "model": "ETS", "level": "provider", "failed": 2, "failed_dev_origins": 1}
    assert pools.failed_count_mismatches(counts, pd.DataFrame([row])).empty
    with pytest.raises(ValueError):
        pools.failed_tables({("b1", "icb"): base}, last)
