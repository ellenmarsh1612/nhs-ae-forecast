"""Stage H hypotheses (design §7, §11) on synthetic scored frames and a synthetic vintage table.

Every value here is invented; the calendar dates are real so that W5, CONF19 and CONF21, the
D7 fold and the DEV winter seasons are the ones the run will use.
"""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from nhs_ae.evaluate import audit, stage_f
from nhs_ae.evaluate.asof import load_asof
from nhs_ae.evaluate.metrics import paired_bootstrap
from nhs_ae.evaluate.stage_h import hypotheses as hy
from nhs_ae.evaluate.stage_h import stats
from nhs_ae.evaluate.stage_h.common import (
    CONF19,
    CONF21,
    D7_FOLD,
    DRY,
    DRY_END,
    H4B_MIN_COUNT,
    M2_FAIL_LIMIT,
    NAMES,
    RUN_END,
    W5,
)
from nhs_ae.ingest.recover import publication_date

TARGETS3 = ("att_all", "att_type1", "adm_via_ae")
QS = (0.025, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.975)
T = pd.Timestamp
W5_AT = {T(o): i for i, o in enumerate(W5)}


def scored(series=6, origins=W5, horizons=(3,), targets=TARGETS3, model=NAMES["b0"],
           level="provider", mode="asof", p=0.9, seed=0, failed=None, **const) -> pd.DataFrame:
    """Rows as ``harness.score_forecasts`` returns them: one per series x target x origin x
    horizon, period = origin - 1 + horizon months; ``failed`` (a share) adds a G1 column."""
    names = [f"R{i:02d}" for i in range(series)] if isinstance(series, int) else list(series)
    g = pd.MultiIndex.from_product(
        [names, list(targets), pd.DatetimeIndex([T(o) for o in origins]), list(horizons)],
        names=["series", "target", "origin", "horizon"]).to_frame(index=False)
    m = g["origin"].dt.year * 12 + g["origin"].dt.month - 2 + g["horizon"]
    g["period"] = pd.to_datetime(pd.DataFrame({"year": m // 12, "month": m % 12 + 1, "day": 1}))
    rng = np.random.default_rng(seed)
    g["scale"], g["y"] = 1.0, 1000.0
    for q in QS:
        g[q] = 1000.0 * (0.7 + 0.6 * q)
    g["wis"] = rng.uniform(10.0, 20.0, len(g))
    g["abs_err"] = 0.0
    g["mase"] = rng.uniform(0.5, 1.5, len(g))
    g["cov50"] = rng.random(len(g)) < 0.5
    g["cov90"] = rng.random(len(g)) < p
    g["pit"] = 0.5
    g["winter"] = g["period"].dt.month.isin((12, 1, 2, 3))
    if failed is not None:
        g["failed"] = rng.random(len(g)) < failed
        g.loc[g["failed"], ["cov50", "cov90"]] = False               # g1.mark
    return g.assign(model=model, level=level, mode=mode, **const)


def at_w5(frame: pd.DataFrame, values) -> np.ndarray:
    """values[i] at W5[i], row by row."""
    return np.asarray(values, float)[frame["origin"].map(W5_AT).to_numpy()]


def flag(x):
    """A table's flag (numpy or Python bool, or None/NaN) as True, False or None."""
    return None if x is None or pd.isna(x) else bool(x)


# ---- H1 (§7.3, §11) ----------------------------------------------------------------------
def test_h1_tested_at_0_8_of_reference_is_confirmed():
    ref = scored(10, W5, horizons=(1, 3))
    other = scored(10, [date(2024, 3, 1)], horizons=(3,))           # not a W5 origin
    ref = pd.concat([ref, other], ignore_index=True)
    rows = pd.concat([ref, ref.assign(model=NAMES["m1"], mase=0.8 * ref["mase"]),
                      ref.assign(model=NAMES["m1_v3_raw"], mase=0.9 * ref["mase"], failed=False)],
                     ignore_index=True)
    out = hy.h1(rows, W5)
    t = out["table"].set_index(["model", "target"])
    for tg in TARGETS3:
        r = t.loc[(NAMES["m1"], tg)]
        assert r["rel"] == pytest.approx(-0.20)
        assert r["rel_lo"] == pytest.approx(-0.20) and r["rel_hi"] == pytest.approx(-0.20)
        assert r["verdict"] == "confirmed" and pd.isna(r["qualifier"]) and r["role"] == "decides"
        assert flag(r["fragile"]) is False
        assert t.loc[(NAMES["m1_v3_raw"], tg), "verdict"] == hy.NOT_CONFIRMED
        assert t.loc[(NAMES["m1_v3_raw"], tg), "qualifier"] == "partial support"
    pooled = t.loc[(NAMES["m1"], hy.POOLED)]
    w5_ref = hy._winter_h3(ref, W5)
    assert len(w5_ref) == 150 and pooled["n_pairs"] == len(w5_ref) == pooled["n_ref"]
    assert pooled["role"] == "descriptive" and pooled["verdict"] == "descriptive"
    assert pooled["rel"] == pytest.approx(-0.20)
    tested = w5_ref.assign(model=NAMES["m1"], mase=0.8 * w5_ref["mase"])
    assert paired_bootstrap(w5_ref, tested, metric="mase")["n_pairs"] == 3 * len(w5_ref)
    assert out["overall"]["verdict"] == "confirmed" and out["overall"]["fragile"] is False
    assert out["overall"]["by_model"][NAMES["m1_v3_raw"]]["verdict"] == hy.NOT_CONFIRMED
    assert out["overall"]["caveat"] == hy.S9_CAVEAT and "within one winter" in hy.S9_CAVEAT
    assert set(out["table"]["origin_set"]) == {"W5"} and set(out["table"]["split"]) == {"conf"}
    assert out["loo"]["dropped"].nunique() == 5
    pd.testing.assert_frame_equal(out["failed_dropped"]["table"].drop(columns="g1"),
                                  out["table"].drop(columns="g1"))      # no row failed


NEXT_UP, NEXT_DOWN = np.nextafter(hy.H1_BAR, 0), np.nextafter(hy.H1_BAR, -1)


@pytest.mark.parametrize("rel, rel_hi, verdict, qualifier", [
    (-0.20, -0.15, hy.NOT_CONFIRMED, "point estimate meets the bar"),    # rel_hi exactly -0.15
    (-0.15, -0.10, hy.NOT_CONFIRMED, "point estimate meets the bar"),    # rel exactly -0.15
    (NEXT_UP, 0.0, hy.NOT_CONFIRMED, "partial support"),
    (np.nextafter(0.0, -1), 0.05, hy.NOT_CONFIRMED, "partial support"),
    (0.0, 0.10, hy.NOT_CONFIRMED, "no improvement"),                      # rel exactly 0
    (-0.30, NEXT_DOWN, "confirmed", None),
    (np.nan, -0.30, "not evaluable", None),
])
def test_h1_label_boundaries(rel, rel_hi, verdict, qualifier):
    """rel = ratio - 1 is exact for a ratio in [0.5, 1), so no computed rel can equal the
    float -0.15 (not a multiple of 2**-53): that edge is tested on the rule itself. rel_hi,
    computed as (b - a) / a, can: see the end-to-end test below."""
    assert hy.h1_label(rel, rel_hi) == (verdict, qualifier)


def test_h1_rel_hi_exactly_at_the_bar_end_to_end():
    """B0 MASE 20 and M1 MASE 17 on every row: rel_hi = (17 - 20) / 20 is the float -0.15
    exactly, and rel = 17 / 20 - 1 = -0.15000000000000002."""
    ref = scored(6, W5).assign(mase=20.0)
    out = hy.h1(pd.concat([ref, ref.assign(model=NAMES["m1"], mase=17.0)], ignore_index=True),
                W5, alongside=False)
    t = per_target(out)
    assert (t["rel_hi"] == -0.15).all() and (t["rel"] < -0.15).all()
    assert (t["verdict"] == hy.NOT_CONFIRMED).all()
    assert (t["qualifier"] == "point estimate meets the bar").all()
    assert out["overall"]["verdict"] == hy.NOT_CONFIRMED
    assert out["overall"]["by_model"][NAMES["m1"]]["composite"] == -0.15
    assert t["fragile_range"].map(flag).tolist() == [True] * 3       # -0.15 in [min, max]


def test_h1_rel_exactly_zero_is_no_improvement():
    ref = scored(8, W5)
    out = hy.h1(pd.concat([ref, ref.assign(model=NAMES["m1"])], ignore_index=True), W5,
                alongside=False)
    t = out["table"]
    per = t[t["target"] != hy.POOLED]
    assert (per["rel"] == 0.0).all() and (per["qualifier"] == "no improvement").all()
    assert (per["verdict"] == "not confirmed (refuted, as registered)").all()
    assert out["overall"]["verdict"] == "not confirmed (refuted, as registered)"


def h1_rows(values: dict, n_series: int = 6) -> pd.DataFrame:
    """B0's MASE is 1 on every row and default M1's is 1 + values[target][i] at W5[i]. Every
    series has the same ratio, so rel = rel_lo = rel_hi = the mean of the values kept."""
    ref = scored(n_series, W5).assign(mase=1.0)
    tested = ref.assign(model=NAMES["m1"])
    tested["mase"] = 1.0 + np.array([values[t][W5_AT[o]] for t, o in
                                     zip(tested["target"], tested["origin"])])
    return pd.concat([ref, tested], ignore_index=True)


def per_target(out) -> pd.DataFrame:
    t = out["table"]
    return t[(t["model"] == NAMES["m1"]) & (t["target"] != hy.POOLED)].set_index("target")


def test_h1_not_confirmed_with_one_failing_and_one_straddling_is_not_fragile():
    out = hy.h1(h1_rows({"att_all": [0.0] * 5,
                         "att_type1": [-0.30, -0.25, -0.10, -0.10, -0.05],
                         "adm_via_ae": [-0.30] * 5}), W5, alongside=False)
    t = per_target(out)
    assert t.loc["att_all", "verdict"] == hy.NOT_CONFIRMED
    assert flag(t.loc["att_all", "fragile"]) is False
    assert t.loc["att_type1", "verdict"] == "confirmed"
    assert flag(t.loc["att_type1", "fragile"]) is True
    assert t.loc["att_type1", "loo_rel_hi_min"] < hy.H1_BAR < t.loc["att_type1", "loo_rel_hi_max"]
    assert out["overall"]["verdict"] == hy.NOT_CONFIRMED
    assert out["overall"]["fragile"] is False and out["overall"]["flips"] == []


def test_h1_two_targets_flipping_under_different_origins_is_not_fragile():
    out = hy.h1(h1_rows({"att_all": [0.2, -0.2, -0.2, -0.2, -0.2],
                         "att_type1": [-0.2, 0.2, -0.2, -0.2, -0.2],
                         "adm_via_ae": [-0.3] * 5}), W5, alongside=False)
    t = per_target(out)
    assert (t.loc[["att_all", "att_type1"], "verdict"] == hy.NOT_CONFIRMED).all()
    assert flag(t.loc["att_all", "fragile"]) is True and flag(t.loc["att_type1", "fragile"]) is True
    assert t.loc["att_all", "loo_drop_at_rel_hi_min"] == T(W5[0])
    assert t.loc["att_type1", "loo_drop_at_rel_hi_min"] == T(W5[1])
    o = out["overall"]
    assert o["verdict"] == hy.NOT_CONFIRMED and o["fragile"] is False and o["flips"] == []
    assert o["by_model"][NAMES["m1"]]["loo_min"] == pytest.approx(-0.1)


def test_h1_confirmed_with_one_target_straddling_is_fragile():
    out = hy.h1(h1_rows({"att_all": [-0.3] * 5, "att_type1": [-0.3] * 5,
                         "adm_via_ae": [-0.4, -0.1, -0.1, -0.1, -0.1]}), W5, alongside=False)
    o = out["overall"]
    assert o["verdict"] == "confirmed" and o["fragile"] is True
    d = o["by_model"][NAMES["m1"]]
    assert d["fragile_range"] is True and d["flips"] == [T(W5[0])]
    assert d["drop_at_max"] == T(W5[0]) and d["loo_max"] == pytest.approx(-0.1)
    assert flag(per_target(out).loc["adm_via_ae", "qualifier_fragile"]) is None     # confirmed


def test_h1_full_sample_differs_extension():
    """Every subset misses the bar while the full sample clears it: the subset range
    [-0.1475, 0] of max-over-targets rel_hi excludes -0.15, so only the extension flags it."""
    out = hy.h1(h1_rows({"att_all": [-0.21, -0.21, -0.21, -0.21, 0.04],
                         "att_type1": [0.0, 0.0, 0.0, 0.0, -0.8],
                         "adm_via_ae": [-0.3] * 5}), W5, alongside=False)
    d = out["overall"]["by_model"][NAMES["m1"]]
    assert d["verdict"] == "confirmed" and d["composite"] == pytest.approx(-0.16)
    assert d["loo_min"] == pytest.approx(-0.1475) and d["loo_max"] == pytest.approx(0.0)
    assert d["fragile_range"] is False and d["fragile_differs"] is True
    assert d["fragile"] is True and d["flips"] == [T(o) for o in W5]


def test_h1_qualifier_fragility_uses_its_boundaries():
    out = hy.h1(h1_rows({"att_all": [0.12, -0.03, -0.03, -0.03, -0.03],     # rel 0
                         "att_type1": [-0.2, -0.1, -0.1, -0.1, -0.1],       # rel -0.12
                         "adm_via_ae": [-0.3] * 5}), W5, alongside=False)
    t = per_target(out)
    assert t.loc["att_all", "qualifier"] == "no improvement"
    assert flag(t.loc["att_all", "qualifier_fragile"]) is True     # subsets: -0.0075..0.0375
    assert t.loc["att_type1", "qualifier"] == "partial support"
    assert flag(t.loc["att_type1", "qualifier_fragile"]) is False  # -0.125..-0.1 in (-0.15, 0)


def test_h1_one_winter_origin_gives_an_empty_loo_and_no_fragility():
    """The dry run (design §10): a single winter-h3 origin."""
    rows = h1_rows({t: [-0.3] * 5 for t in TARGETS3})
    out = hy.h1(rows[rows["origin"] == T(W5[1])], W5, alongside=False)
    assert out["loo"].empty and out["overall"]["fragile"] is None
    assert per_target(out)["fragile"].isna().all()


def test_h1_and_h4_refuse_a_missing_alongside_item_unless_opted_out():
    rows = h1_rows({t: [-0.3] * 5 for t in TARGETS3})
    with pytest.raises(ValueError, match=f"{NAMES['m1_v3_raw']} rows.*alongside=False"):
        hy.h1(rows, W5, loo=False)
    assert hy.h1(rows, W5, loo=False, alongside=False)["overall"]["verdict"] == "confirmed"
    frames = h4_frames()
    one_mode = {k: f for k, f in frames.items() if k != ("m1_v3_raw", "final")}
    neither = {k: f for k, f in frames.items() if k[0] != "m1_v3_raw"}
    for fn in (lambda f, **kw: hy.h4(f, W5, loo=False, **kw),
               lambda f, **kw: hy.h4_original(f, W5, hy.h4(neither, W5, loo=False,
                                                            alongside=False), **kw)):
        with pytest.raises(ValueError, match="m1_v3_raw', 'final'"):
            fn(one_mode)
        with pytest.raises(ValueError, match="m1_v3_raw', 'final'"):
            fn(one_mode, alongside=False)                               # never in one mode only
        with pytest.raises(ValueError, match="reported alongside"):
            fn(neither)
        out = fn(neither, alongside=False)
        assert "m1_v3_raw" not in set(out["table"]["key"])
    assert "m1_v3_raw" in set(hy.h4(frames, W5, loo=False, alongside=False)["table"]["key"])


def test_h1_failed_dropped_variant_for_m1_v3_raw_only():
    ref = scored(6, W5)
    v3 = ref.assign(model=NAMES["m1_v3_raw"], failed=False)
    v3.loc[v3.index[:4], "failed"] = True
    rows = pd.concat([ref, ref.assign(model=NAMES["m1"]), v3], ignore_index=True)
    out = hy.h1(rows, W5)
    fd = out["failed_dropped"]["table"].set_index(["model", "target"])
    t = out["table"].set_index(["model", "target"])
    assert fd.loc[(NAMES["m1_v3_raw"], hy.POOLED), "n_tested"] == len(v3) - 4
    assert fd.loc[(NAMES["m1"], hy.POOLED), "n_pairs"] == t.loc[(NAMES["m1"], hy.POOLED), "n_pairs"]
    with pytest.raises(ValueError, match="no G1 flag"):
        hy.h1(pd.concat([ref, ref.assign(model=NAMES["m1"]), v3.assign(failed=np.nan)]), W5)


# ---- coverage: the primary and H2 (§7.5, §11) --------------------------------------------
def test_primary_report_holds_the_12_origin_year_cells_with_conf21_separate():
    rows = scored(6, CONF21, horizons=range(1, 7), model=hy.PRIMARY_MODEL, p=0.9, seed=3,
                  failed=0.05)
    out = hy.primary(rows, CONF19, D7_FOLD)
    t = out["table"]
    assert t["horizon"].tolist() == list(range(1, 7)) and set(t["origin_set"]) == {"CONF19"}
    assert out["verdict"] == stats.verdict_primary(t)
    r19 = rows[rows["origin"] <= T("2025-07-01")]
    assert np.allclose(t["point"], r19.groupby("horizon")["cov90"].mean(), rtol=0, atol=1e-15)
    issued = out["alongside"]["as_issued"]
    cells = issued["cells"]
    assert len(cells) == 12 and set(cells["origin_set"]) == {"CONF19"}
    assert cells.groupby("oyear")["origins"].unique().map(list).to_dict() == {2024: [12],
                                                                               2025: [7]}
    assert (cells["n"] == cells["origins"] * 6 * 3).all() and cells["met"].dtype == bool
    assert cells["met"].tolist() == cells["value"].between(0.87, 0.93).tolist()
    c21 = issued["cells_conf21"]
    assert len(c21) == 12 and set(c21["origin_set"]) == {"CONF21"}
    assert c21.groupby("oyear")["origins"].first().to_dict() == {2024: 12, 2025: 9}
    assert set(issued["conf21"]["origin_set"]) == {"CONF21"}
    assert (issued["conf21"]["n_units"] == 19).all()                   # D7 fold
    assert set(issued["by_horizon"]["stat"]) == {"cov90", "cov50"}
    assert len(issued["per_target"]) == 2 * 3 * 6
    dropped = out["alongside"]["failed_dropped"]
    assert len(dropped["cells"]) == 12 and set(dropped["cells"]["g1"]) == {"failed_dropped"}
    assert (dropped["cells"]["n"] <= cells["n"]).all()
    assert dropped["cells"]["n"].sum() < cells["n"].sum()
    assert issued["failed"]["n_failed"].sum() == int(r19["failed"].sum())


def test_primary_and_h2_run_on_a_dry_run_shaped_table():
    """Design §10: six DEV origins treated as CONF-like, horizon h scored at the first 7 - h
    (the embargo drops the rest); h5 and h6 are origin-degenerate, and no CONF21 table."""
    parts = [scored(6, DRY[:7 - h], horizons=(h,), model=hy.PRIMARY_MODEL, seed=h, failed=0.02)
             for h in range(1, 7)]
    out = hy.primary(pd.concat(parts, ignore_index=True), DRY, {})
    t = out["table"]
    assert set(t["split"]) == {"dev"} and set(t["origin_set"]) == {"DRY"}
    assert t["degenerate"].tolist() == [False] * 4 + [True] * 2
    assert out["verdict"]["verdict"] in ("within tolerance", "outside tolerance", "inconclusive")
    assert "conf21" not in out["alongside"]["as_issued"]
    m1 = pd.concat([p.assign(model=NAMES["m1"]).drop(columns="failed") for p in parts])
    assert hy.h2_m1(m1, DRY, {})["conf21"] is None


def test_primary_refuses_another_model():
    rows = scored(4, CONF19, horizons=range(1, 7), model=NAMES["m1_v3_raw"])
    with pytest.raises(ValueError, match="model"):
        hy.primary(rows, CONF19, D7_FOLD)


def test_h2_m1_point_estimates_decide_with_conf21_alongside():
    rows = scored(8, CONF21, horizons=range(1, 7), model=NAMES["m1"], seed=5)
    rows.loc[rows["horizon"] == 5, "cov90"] = False                     # h5 at 0: under
    rows.loc[rows["horizon"] == 2, "cov90"] = True                      # h2 at 1: over
    out = hy.h2_m1(rows, CONF19, D7_FOLD)
    v = out["verdict"]
    assert v["verdict"] == "confirmed" and v["directions"][5] == "under"
    assert v["directions"][2] == "over" and v["fragile"] is False
    assert out["caveat"] == hy.S9_CAVEAT
    assert set(out["table"]["origin_set"]) == {"CONF19"}
    assert set(out["conf21"]["table"]["origin_set"]) == {"CONF21"}
    assert len(out["cells"]) == 12 and len(out["conf21"]["cells"]) == 12
    assert out["failed_dropped"] is None and out["n_all_zero"] == 0


ICBS = [f"Q{c}" for c in "ABCDEF"]


def m2_fits(failed=(), retried=()) -> pd.DataFrame:
    rows = []
    for o in CONF21:
        o = T(o)
        tries = [True, True] if o in failed else [True, False] if o in retried else [False]
        for a, f in enumerate(tries):
            rows.append({"origin": o, "attempt": a, "failed": f,
                         "rhat_max": np.nan if f else 1.05 + 0.001 * o.month,
                         "ess_bulk_min": np.nan if f else 60.0, "divergences": np.nan if f else 0})
    return pd.DataFrame(rows)


@pytest.mark.parametrize("n_failed, evaluable", [(3, True), (4, False)])
def test_h2_m2_not_evaluable_from_four_failed_counted_units(n_failed, evaluable):
    failed = [T(o) for o in CONF19[2:2 + n_failed]]
    present = [o for o in CONF21 if T(o) not in failed]
    rows = scored(ICBS, present, horizons=range(1, 7), model=NAMES["m2"], level="icb", seed=6)
    fits = m2_fits(failed, retried=[T(CONF19[0])])
    out = hy.h2_m2(rows, CONF19, D7_FOLD, fits)
    assert out["evaluable"] is evaluable and out["fail_limit"] == M2_FAIL_LIMIT == 4
    assert out["n_failed_counted"] == n_failed and out["n_full"] == 21
    assert (out["verdict"]["verdict"] == "not evaluable") is (not evaluable)
    assert out["table"]["n_units"].max() == 19 - n_failed               # units present only
    assert "phase-1b test at ICB level" in out["phase"] and "§9 fallback" in out["phase"]
    assert out["limitation"] == hy.TEXT_A and out["caveat"] == hy.S9_CAVEAT
    d = out["diagnostics"]
    assert set(d["split"]) == {"dev", "conf"} and (d.loc[d["split"] == "conf", "fits"].sum()
                                                   == 19 - n_failed)
    assert set(zip(d["split"], d["origin_set"])) == {("dev", "DEV"), ("conf", "CONF19")}
    assert len(out["fits"]) == len(fits)


def test_h2_m2_diagnostics_label_the_dry_run_fits_dev():
    """The dry run's counted origins are DEV: its fits are never labelled CONF."""
    fits = pd.DataFrame([{"origin": T(o), "attempt": 0, "failed": False, "rhat_max": 1.05,
                          "ess_bulk_min": 60.0, "divergences": 0} for o in DRY])
    d = hy._m2_diagnostics(fits, DRY)
    assert set(d["split"]) == {"dev"}
    assert d.loc[d["origin_set"] == "DRY", "fits"].tolist() == [6]
    assert set(d["origin_set"]) == {"DEV", "DRY"}                       # two files, not one


def test_h2_m2_refuses_rows_that_disagree_with_the_fits():
    failed = [T(CONF19[3])]
    rows = scored(ICBS, CONF21, horizons=range(1, 7), model=NAMES["m2"], level="icb")
    with pytest.raises(ValueError, match="rows at failed origins"):
        hy.h2_m2(rows, CONF19, D7_FOLD, m2_fits(failed))
    with pytest.raises(ValueError, match="no M2 fit recorded"):
        hy.h2_m2(rows, CONF19, D7_FOLD, m2_fits().iloc[1:])
    rowless_fold = rows[rows["origin"] != T("2025-08-01")]              # fitted, no rows
    with pytest.raises(ValueError, match=r"no rows at fitted origins \['2025-08'\]"):
        hy.h2_m2(rowless_fold, CONF19, D7_FOLD, m2_fits())


def test_fail_limits_follow_the_registered_counts():
    assert hy._fail_limit(19) == M2_FAIL_LIMIT == int(np.floor(0.2 * 19)) + 1
    assert hy._fail_limit(6) == 2                                       # dry run: more than 20%
    assert {n: hy._more_than_half(n) for n in H4B_MIN_COUNT} == H4B_MIN_COUNT
    assert all(n // 2 + 1 == k for n, k in H4B_MIN_COUNT.items()) and hy._more_than_half(69) == 35


# ---- descriptive headline (§7.6) ---------------------------------------------------------
def test_headline_on_common_rows_with_paired_gaps():
    raw, pooled = {}, {}
    for i, m in enumerate((NAMES["b1"], NAMES["m1_v3_raw"])):
        r = scored(6, CONF19, horizons=range(1, 7), model=m, p=0.75, seed=10 + i, failed=0.02)
        p = r.assign(model=f"{m}+pooled", cov90=np.random.default_rng(i).random(len(r)) < 0.9)
        p.loc[p["failed"], "cov90"] = False
        extra = scored(["RZZ"], CONF19, horizons=range(1, 7), model=f"{m}+pooled", failed=0.0)
        raw[m], pooled[m] = r, pd.concat([p, extra], ignore_index=True)
    icb = scored(ICBS, CONF19, horizons=range(1, 7), model=NAMES["b1"], level="icb", failed=0.0)
    out = hy.headline(raw, pooled, CONF19, D7_FOLD, icb_raw_ets=icb)
    h = out["by_horizon"]
    assert len(h) == 12 and (h["n_rows_raw"] == h["n_rows_pooled"]).all()   # RZZ dropped
    assert (h["n_rows_raw"] == 6 * 3 * 19).all() and (h["n_series_pooled"] == 6).all()
    assert np.allclose(h["point_diff"], h["point_pooled"] - h["point_raw"], rtol=0, atol=1e-15)
    assert np.allclose(h["raw_gap_point_pp"], 100 * (h["point_raw"] - 0.9))
    assert np.allclose(h["diff_point_pp"], 100 * h["point_diff"])
    assert (h["lo_diff"] <= h["point_diff"]).all() and (h["point_diff"] <= h["hi_diff"]).all()
    b1 = raw[NAMES["b1"]]
    exp = b1.groupby("horizon")["cov90"].mean().to_numpy()
    assert np.allclose(h.loc[h["model"] == NAMES["b1"], "point_raw"], exp, rtol=0, atol=1e-15)
    assert set(out["by_origin_year"]["oyear"]) == {2024, 2025}
    assert out["failed_dropped"]["by_horizon"]["n_rows_raw"].sum() < h["n_rows_raw"].sum()
    icb_h = out["icb_raw_ets"]["as_issued"]["by_horizon"]
    assert set(icb_h["level"]) == {"icb"} and (icb_h["n_series"] == 6).all()


# ---- H3 (§7.7, §11) ----------------------------------------------------------------------
LEVEL_SERIES = {"provider": [f"R{i:02d}" for i in range(6)], "icb": ["QA", "QB", "QC"],
                "region": ["Y1", "Y2"], "england": ["ENGLAND"]}


def h3_frames(icb, provider) -> dict:
    """Base WIS 1 everywhere; MinT's is 1 + icb[i] (ICB), 1 + provider[i] (provider) and 1
    elsewhere at W5[i], so rel = rel_hi = the mean of the values kept, for every base."""
    out = {}
    for b in stage_f.BASE_MODELS:
        name = f"{NAMES[b]}+pooled"
        base = pd.concat([scored(LEVEL_SERIES[lv], W5, model=name, level=lv, failed=0.0)
                          for lv in stage_f.LEVELS], ignore_index=True).assign(wis=1.0)
        mint = base.assign(model=f"{name}+mint")
        add = {"icb": at_w5(mint, icb), "provider": at_w5(mint, provider)}
        mint["wis"] = 1.0 + np.select([mint["level"] == lv for lv in add], list(add.values()), 0.0)
        out[(b, "base")], out[(b, "mint")] = base, mint
    return out


def test_h3_both_clauses_failing_with_one_straddling_is_not_fragile():
    out = hy.h3(h3_frames(icb=[-0.4, 0.1, 0.1, 0.1, 0.12], provider=[0.1] * 5), W5)
    v = out["verdicts"].set_index("base")
    for base in ("ETS", "STL+ARIMA", "M1"):
        assert v.loc[base, "H3"] == "fails" and flag(v.loc[base, "fragile"]) is False
        assert flag(v.loc[base, "icb_straddles_0"]) is True                   # descriptive only
        assert v.loc[base, "loo_icb_rel_hi_min"] == pytest.approx(-0.025)
        assert flag(v.loc[base, "provider_straddles_2pct"]) is False
    assert out["headline"] == {"base": "M1", "verdict": "fails", "fragile": False, "flips": []}


def test_h3_holding_with_one_straddling_is_fragile():
    out = hy.h3(h3_frames(icb=[-0.1] * 5, provider=[0.09, 0.0, 0.0, 0.0, 0.0]), W5)
    v = out["verdicts"].set_index("base")
    assert v.loc["M1", "H3"] == "holds" and flag(v.loc["M1", "fragile"]) is True
    assert v.loc["M1", "flips"] == [T(o) for o in W5[1:]]
    assert flag(v.loc["M1", "provider_straddles_2pct"]) is True
    assert out["headline"]["verdict"] == "holds" and out["headline"]["fragile"] is True
    t = out["table"].set_index(["base", "level"])
    assert np.isnan(t.loc[("M1", "england"), ["rel_lo", "rel_hi"]].to_numpy(float)).all()
    assert t.loc[("M1", "england"), "note"] == hy.ENGLAND_NA
    assert t.loc[("M1", "region"), "note"] == "caution: bootstrap over 2 series"
    assert t.loc[("M1", "icb"), "rel_hi"] == pytest.approx(-0.1)
    assert (t["n_pairs"] == t["n_ref"]).all() and (t["unpaired_ref"] == 0).all()
    assert "R2 not tested (phase 1b)" in out["notes"]
    assert out["failed_dropped"] is not None and len(out["loo"]) == 5 * 3


def test_h3_refuses_duplicate_rows_as_compare_does():
    frames = h3_frames(icb=[-0.1] * 5, provider=[0.0] * 5)
    b = frames[("m1_v3_raw", "base")]
    frames[("m1_v3_raw", "base")] = pd.concat([b, b.iloc[:3]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate"):
        hy.h3(frames, W5)


# ---- H4 and H4-original (§7.8, §7.9, §11) ------------------------------------------------
BASE_WIS = {"b0": 1.0, "b1": 2.0, "b2": 3.0, "m1": 4.0, "m1_v3_raw": 5.0}


def h4_frames(d=None, asof=None, n_series=10) -> dict:
    """As-of WIS asof[(m, target)] (default BASE_WIS[m]); final = as-of x (1 + d[(m, target)][i])
    at W5[i]. G1 bases carry a ``failed`` column."""
    out = {}
    for m, w in BASE_WIS.items():
        a = scored(n_series, W5, model=NAMES[m], failed=0.0 if m in ("b1", "b2", "m1_v3_raw")
                   else None)
        a["wis"] = [(asof or {}).get((m, t), w) for t in a["target"]]
        f = a.assign(mode="final")
        mult = [1 + (d or {}).get((m, t), [0.0] * 5)[W5_AT[o]] for t, o in
                zip(f["target"], f["origin"])]
        f["wis"] = a["wis"].to_numpy() * np.array(mult)
        out[(m, "asof")], out[(m, "final")] = a, f
    return out


def test_h4_two_percent_clause_uses_the_interval_not_the_point():
    frames = h4_frames(d={("b1", "att_all"): [0.03] * 5, ("b2", "att_all"): [-0.03] * 5})
    f = frames[("m1", "final")]                                          # half the series +6%
    half = f["series"].isin([f"R{i:02d}" for i in range(5)]) & (f["target"] == "att_all")
    f.loc[half, "wis"] *= 1.06
    out = hy.h4(frames, W5)
    t = out["table"].set_index(["key", "target"])
    b1, b2 = t.loc[("b1", "att_all")], t.loc[("b2", "att_all")]
    assert flag(b1["differs"]) is True and b1["rel_lo"] > 0.02
    assert flag(b2["differs"]) is True and b2["rel_hi"] < -0.02
    m1 = t.loc[("m1", "att_all")]
    assert m1["rel"] == pytest.approx(0.03) and m1["rel_lo"] < 0.02 < m1["rel_hi"]
    assert flag(m1["differs"]) is False
    assert flag(t.loc[("b0", "att_type1"), "differs"]) is False
    assert t.loc[("m1_v3_raw", "att_all"), "role"] == "alongside"
    v = out["verdict"]
    assert v["verdict"] == "refuted" and set(v["refuting"]) == {
        f"{NAMES['b1']} att_all", f"{NAMES['b2']} att_all"}
    assert v["note"] == hy.H4_NOTE and "exploratory" in v["note"]


def test_h4_clause_fragility_on_rel_lo_and_rel_hi():
    out = hy.h4(h4_frames(d={("b1", "att_type1"): [0.09, 0, 0, 0, 0],
                             ("b2", "att_type1"): [-0.09, 0, 0, 0, 0],
                             ("m1", "att_type1"): [0.01] * 5}), W5)
    t = out["table"].set_index(["key", "target"])
    b1, b2, m1 = (t.loc[(k, "att_type1")] for k in ("b1", "b2", "m1"))
    assert flag(b1["differs"]) is False and b1["loo_rel_lo_min"] == pytest.approx(0.0)
    assert b1["loo_rel_lo_max"] == pytest.approx(0.0225) and flag(b1["fragile"]) is True
    assert flag(b2["differs"]) is False and b2["loo_rel_hi_min"] == pytest.approx(-0.0225)
    assert flag(b2["fragile"]) is True
    assert flag(m1["differs"]) is False and flag(m1["fragile"]) is False
    assert out["verdict"]["verdict"] == "confirmed" and out["verdict"]["fragile"] is True


def test_h4_ranking_flip_refutes():
    asof = {("b2", "adm_via_ae"): 2.02}                                  # b1 < b2 by 1%
    out = hy.h4(h4_frames(d={("b1", "adm_via_ae"): [0.015] * 5}, asof=asof), W5)
    assert not out["table"]["differs"].astype(bool).any()                 # no 2% call
    v = out["verdict"]
    assert v["verdict"] == "refuted" and v["refuting"] == ["ranking adm_via_ae"]
    assert v["ranking_holds"] == {"att_all": True, "att_type1": True, "adm_via_ae": False}
    r = out["ranking"].set_index(["target", "mode", "key"])["rank"]
    assert (r.loc[("adm_via_ae", "asof", "b1")], r.loc[("adm_via_ae", "final", "b1")]) == (2, 3)
    assert v["elements"] == [{"element": "ranking adm_via_ae", "fragile": False}]


def test_h4_common_row_ranking_ignores_extra_rows():
    frames = h4_frames()
    plain = hy.h4(frames, W5, loo=False)["ranking"]
    extra = {k: f.copy() for k, f in frames.items()}
    big = scored(["RZZ"], W5, model=NAMES["b1"], failed=0.0).assign(wis=1000.0)
    extra[("b1", "asof")] = pd.concat([extra[("b1", "asof")], big], ignore_index=True)
    b0_extra = scored(["RYY"], W5, model=NAMES["b0"]).assign(mode="final", wis=1000.0)
    extra[("b0", "final")] = pd.concat([extra[("b0", "final")], b0_extra], ignore_index=True)
    out = hy.h4(extra, W5, loo=False)
    cols = ["target", "mode", "key", "mean_wis", "rank", "n_rows", "n_series"]
    pd.testing.assert_frame_equal(out["ranking"][cols], plain[cols])
    naive = extra[("b1", "asof")].query("target == 'att_all'")["wis"].mean()
    assert naive > BASE_WIS["m1"]                                        # all rows would reorder
    assert out["verdict"]["verdict"] == "confirmed"


def test_h4_refuted_with_every_refuting_element_fragile():
    """One fragile refuting element: dropping 2024-01 clears it, so that subset is confirmed
    and the verdict is fragile. Two, each cleared by a different origin: every subset keeps
    one, so every subset is refuted and the verdict is not fragile."""
    one = hy.h4(h4_frames(d={("b1", "att_all"): [0.12, 0, 0, 0, 0]}), W5)
    v = one["verdict"]
    assert v["verdict"] == "refuted" and v["elements"] == [
        {"element": f"{NAMES['b1']} att_all", "fragile": True}]
    assert v["fragile"] is True and v["flips"] == [T(W5[0])]
    two = hy.h4(h4_frames(d={("b1", "att_all"): [0.12, 0, 0, 0, 0],
                             ("b2", "att_type1"): [0, 0.12, 0, 0, 0]}), W5)
    v = two["verdict"]
    assert v["verdict"] == "refuted" and len(v["elements"]) == 2
    assert all(e["fragile"] is True for e in v["elements"])
    assert v["fragile"] is False and v["flips"] == []


def test_h4_failed_dropped_variant_drops_g1_rows_only():
    frames = h4_frames()
    a = frames[("b1", "asof")]
    a.loc[a.index[:3], "failed"] = True
    out = hy.h4(frames, W5, loo=False)
    fd = out["failed_dropped"]
    assert fd["n_failed"]["b1/asof"] == 0 and out["n_failed"]["b1/asof"] == 3
    assert fd["ranking"]["n_rows"].min() < out["ranking"]["n_rows"].min()


def test_h4_original_deltas_and_the_ranking_link():
    asof = {("b1", t): 0.8 for t in TARGETS3}
    frames = h4_frames(d={("b1", "att_all"): [0.075] * 5}, asof=asof)
    h4r = hy.h4(frames, W5, loo=False)
    out = hy.h4_original(frames, W5, h4r)
    t = out["table"].set_index(["key", "target"])
    r = t.loc[("b1", "att_all")]
    assert r["rel_asof"] == pytest.approx(-0.2) and r["rel_final"] == pytest.approx(-0.14)
    assert r["delta_pp"] == pytest.approx(6.0) and flag(r["exceeds"]) is True
    assert flag(t.loc[("b2", "att_all"), "exceeds"]) is False
    for mode in ("asof", "final"):                                      # every compare count
        assert (t[f"n_ref_{mode}"] == 50).all() and (t[f"n_tested_{mode}"] == 50).all()
        assert (t[f"n_pairs_{mode}"] == 50).all() and (t[f"n_units_{mode}"] == 10).all()
        assert (t[f"unpaired_ref_{mode}"] == 0).all() and (t[f"unpaired_tested_{mode}"] == 0).all()
        assert t[f"evaluable_{mode}"].astype(bool).all()
    assert out["verdict"] == {"verdict": "holds", "exceeds": [f"{NAMES['b1']} att_all"],
                              "ranking_changes": []}
    assert out["failed_dropped"]["verdict"]["verdict"] == "holds"


# ---- H4b (§7.10, §11) --------------------------------------------------------------------
PROVIDERS = ("RAA", "RBB", "RCC")
PARTS = {"att_type1": 100, "att_type2": 10, "att_other": 20, "adm_via_ae_type1": 30,
         "adm_via_ae_type2": 1, "adm_via_ae_other": 2}
LOST = (T("2025-07-01"), T("2025-08-01"))


def vintage_table(start="2023-06-01", end="2025-08-01", delayed=None) -> pd.DataFrame:
    """Periods ``start`` to ``end`` (default 2023-06 to 2025-08), each published on its
    publication date and revised once four months later; a period in ``delayed`` lost its
    original release and first appears on the date given (default: 2025-07 and 2025-08, on
    2025-11-13). Revisions add 5 to RAA's type 1 attendances; RCC submits 2024-10
    only at the revision (late); RBB's 2024-12 other attendances are revised to missing
    (withdrawn from att_all). Integer values, so every sum is exact."""
    delayed = dict.fromkeys(LOST, T("2025-11-13")) if delayed is None else delayed
    rows = []
    for p in pd.date_range(start, end, freq="MS"):
        pub = delayed.get(p, T(publication_date(p.date())))
        rev = pub + pd.DateOffset(months=4)
        for j, org in enumerate(PROVIDERS):
            for snap in (pub, rev):
                if org == "RCC" and p == T("2024-10-01") and snap == pub:
                    continue
                for metric, base in PARTS.items():
                    val = float(base * (j + 1) + p.month)
                    if snap == rev and org == "RAA" and metric == "att_type1":
                        val += 5
                    if (snap == rev and org == "RBB" and p == T("2024-12-01")
                            and metric == "att_other"):
                        val = np.nan
                    rows.append((p, org, "NHS ENGLAND LONDON", f"Trust {org}", metric, val, False,
                                 snap))
    return pd.DataFrame(rows, columns=["period", "org_code", "parent_org", "org_name", "metric",
                                       "value", "is_total", "snapshot"])


@pytest.fixture(scope="module")
def vintages():
    return vintage_table()


def test_h4b_identity_and_components(vintages):
    origins = [date(2024, m, 1) for m in range(7, 13)] + [date(2025, m, 1) for m in range(1, 10)]
    c = hy.h4b_components(vintages, origins)
    assert len(c) == 15 * 3
    assert (c["sum_final"] - c["sum_asof"] == c["V"] + c["L"] - c["Wd"]).all()
    feb = c[(c["origin"] == T("2025-02-01"))].set_index("target")          # as-of 2025-02-13
    assert feb.loc["att_all", "E_o"] == T("2025-01-01")
    assert feb.loc["att_all", "V"] == 4 * 5                    # RAA 2024-10..2025-01 unrevised
    assert feb.loc["att_all", "L"] == 100 * 3 + 10 * 3 + 20 * 3 + 3 * 10       # RCC 2024-10
    assert feb.loc["att_all", "Wd"] == 100 * 2 + 10 * 2 + 20 * 2 + 3 * 12      # RBB 2024-12
    assert feb.loc["att_all", ["n_late", "n_withdrawn"]].tolist() == [1, 1]
    assert feb.loc["att_type1", "Wd"] == 0 and feb.loc["adm_via_ae", "V"] == 0
    a = c.assign(late_larger=c["L"].abs() > c["V"].abs())
    assert a["late_larger"].any() and not a["late_larger"].all()


def test_h4b_window_alignment_at_a_truncated_origin_and_the_lost_originals(vintages):
    origins = [date(2025, 7, 1), date(2025, 8, 1), date(2025, 9, 1)]
    c = hy.h4b_components(vintages, origins).set_index(["origin", "target"])
    for o in origins:
        e = load_asof(o, "asof", vintages).last_period                  # the loader's end month
        r = c.loc[(T(o), "att_type1")]
        assert r["E_o"] == e == T("2025-06-01")
        assert r["window_start"] == T("2024-07-01") and flag(r["truncated"]) is (o != origins[0])
        assert r["n_both"] == 12 * 3 and r["n_late"] == 0 == r["n_withdrawn"]
    lost = c.xs("att_type1", level="target")
    assert lost["lost_originals_n"].tolist() == [0, 3, 6]
    jul = sum(100 * (j + 1) + 7 for j in range(3)) + 5                  # final: revised RAA
    aug = sum(100 * (j + 1) + 8 for j in range(3)) + 5
    assert lost["lost_originals_final"].tolist() == [0.0, jul, jul + aug]
    nominal = audit.training_leakage(vintages, [date(2025, 8, 1)])       # anchored at M-1
    assert nominal.set_index("measure").loc["att_all", "only_in_final"] == 3


# The truncated DEV origins' missing months (P10's corrected list): each original release was
# lost, and the first surviving version, a revision, appeared on the next origin's as-of date.
DEV_LOST = {T("2018-10-01"): T("2018-12-13"), T("2021-09-01"): T("2021-11-11")}
E_O = {    # origin -> the as-of loader's end month, at the truncated origins and their neighbours
    "dev": {date(2018, 10, 1): "2018-09", date(2018, 11, 1): "2018-09",
            date(2018, 12, 1): "2018-11", date(2021, 9, 1): "2021-08",
            date(2021, 10, 1): "2021-08", date(2021, 11, 1): "2021-10"},
    "conf": {date(2025, 7, 1): "2025-06", date(2025, 8, 1): "2025-06",
             date(2025, 9, 1): "2025-06"},
}


@pytest.mark.parametrize("case", ["dev", "conf"])
def test_h4b_window_is_the_loaders_last_12_months_at_the_truncated_origins(case, vintages):
    """P14: W_o is the 12 months ending at the as-of loader's end month E_o (the last month in
    o's as-of data), not at M-1. Checked at the truncated DEV origins 2018-11 and 2021-10,
    whose missing month first appears on the next origin's as-of date (so it is in that
    origin's window), and at the CONF-like 2025-08 and 2025-09, each with its neighbours. The
    window's sums are the loader's own as-of and final panels over those 12 months, and the
    months after E_o up to M-1 are the lost originals."""
    v = vintage_table("2017-06-01", "2021-10-01", DEV_LOST) if case == "dev" else vintages
    c = hy.h4b_components(v, list(E_O[case]), end=RUN_END).set_index(["origin", "target"])
    for o, end_month in E_O[case].items():
        asof, final = load_asof(o, "asof", v), load_asof(o, "final", v)
        e, m1 = T(f"{end_month}-01"), T(o) - pd.DateOffset(months=1)
        assert asof.last_period == e and final.last_period == m1
        window = pd.date_range(e - pd.DateOffset(months=11), e, freq="MS")
        after = pd.date_range(e + pd.DateOffset(months=1), m1, freq="MS")  # empty unless truncated
        for t in TARGETS3:
            r, a, f = c.loc[(T(o), t)], asof.panel(t, "provider"), final.panel(t, "provider")
            assert r["E_o"] == e and r["window_start"] == window[0]
            assert flag(r["truncated"]) is (len(after) > 0)
            assert r["n_late"] == 0 == r["n_withdrawn"]
            assert (r["n_both"] == a.loc[window].notna().sum().sum()
                    == f.loc[window].notna().sum().sum())
            assert r["sum_asof"] == a.loc[window].sum().sum()
            assert r["sum_final"] == f.loc[window].sum().sum()
            assert (r["lost_originals_n"] == f.loc[after].notna().sum().sum()
                    == len(after) * len(PROVIDERS))
            assert r["lost_originals_final"] == f.loc[after].sum().sum()
        assert c.loc[(T(o), "att_type1"), "n_both"] == 12 * len(PROVIDERS)
    truncated = c.xs("att_type1", level="target")["truncated"].map(flag).astype(bool)
    assert [o.date() for o in truncated[truncated].index] == (
        [date(2018, 11, 1), date(2021, 10, 1)] if case == "dev"
        else [date(2025, 8, 1), date(2025, 9, 1)])
    if case == "dev":      # the legacy audit table is anchored at M-1: the unseen month is "late"
        legacy = audit.training_leakage(v, [date(2018, 11, 1), date(2021, 10, 1)])
        assert (legacy.loc[legacy["measure"].isin(TARGETS3), "only_in_final"]
                == len(PROVIDERS)).all()


def test_h4b_components_are_bounded_by_the_end_origin(vintages, monkeypatch):
    """§2.4: an origin beyond E raises, and no period after the last origin's M-1 is read,
    so appending later periods with extreme values changes nothing."""
    origins = [date(2025, 7, 1), date(2025, 8, 1), date(2025, 9, 1)]
    with pytest.raises(ValueError, match="beyond E = 2025-09"):
        hy.h4b_components(vintages, [*origins, date(2025, 10, 1)], end=RUN_END)
    with pytest.raises(ValueError, match="beyond E = 2023-12"):
        hy.h4b_components(vintages, [date(2024, 1, 1)], end=DRY_END)
    plain = hy.h4b_components(vintages, origins, end=RUN_END)
    later = pd.concat([vintages[vintages["period"] == T("2025-08-01")].assign(
        period=T(p), value=1e15, snapshot=T(s)) for p, s in
        (("2025-09-01", "2025-09-11"), ("2025-09-01", "2025-10-09"),
         ("2025-12-01", "2026-01-08"))], ignore_index=True)
    seen = []
    real = hy._provider_targets
    monkeypatch.setattr(hy, "_provider_targets",
                        lambda s: seen.append(s["period"].max()) or real(s))
    out = hy.h4b_components(pd.concat([vintages, later], ignore_index=True), origins,
                            end=RUN_END)
    pd.testing.assert_frame_equal(out, plain)
    assert max(seen) == T("2025-08-01")
    seen.clear()
    dry = hy.h4b_components(pd.concat([vintages, later], ignore_index=True), DRY, end=DRY_END)
    assert max(seen) == T("2023-11-01") and len(dry) == len(DRY) * 3


def test_h4b_verdicts_19_and_21():
    rows = []
    for o in CONF21:
        for t in TARGETS3:
            late = (T(o) in [T(x) for x in CONF19[:10]]
                    and not (t == "att_type1" and T(o) == T(CONF19[0])))
            rows.append({"origin": T(o), "target": t, "V": 1.0, "L": 2.0 if late else 0.5,
                         "lost_originals_n": 3 if T(o) >= T("2025-08-01") else 0})
    out = hy.h4b(pd.DataFrame(rows), CONF19, CONF21)
    t = out["table"].set_index("target")
    assert set(t["origin_set"]) == {"CONF19"} and set(t["n_origins"]) == {19}
    assert t.loc["att_all", "late_larger"] == 10 and t.loc["att_all", "need"] == 10
    assert t.loc["att_all", "verdict"] == "confirmed"
    assert t.loc["att_type1", "verdict"] == "not confirmed"
    t21 = out["conf21"]["table"].set_index("target")                     # §7.1: its own table
    assert set(t21["origin_set"]) == {"CONF21"} and set(t21["n_origins"]) == {21}
    assert t21.loc["att_all", "need"] == 11 and t21.loc["att_all", "verdict"] == "not confirmed"
    for table in (out["table"], out["conf21"]["table"]):
        assert not any(c.endswith(("_counted", "_full")) or c == "origin_set_full"
                       for c in table.columns)
    assert out["overall"]["verdict"] == "not confirmed" and out["overall"]["label"] == "seen"
    assert out["overall"]["verdict_full"] == "not confirmed"
    assert out["overall"]["per_target"]["att_all"] == "confirmed"
    assert out["overall"]["per_target_full"]["att_all"] == "not confirmed"
    assert len(out["lost_originals"]) == 2 * 3 and len(out["per_origin"]) == 21 * 3
    assert set(out["table"]["split"]) == {"conf"} and set(out["per_origin"]["split"]) == {"conf"}
    assert set(out["per_origin"]["origin_set"]) == {"CONF21"}
    with pytest.raises(ValueError, match="no H4b components"):
        hy.h4b(pd.DataFrame(rows)[lambda d: d["origin"] != T("2024-05-01")], CONF19, CONF21)
    dry_rows = pd.DataFrame([{"origin": T(o), "target": t, "V": 1.0, "L": 2.0,
                              "lost_originals_n": 0} for o in DRY for t in TARGETS3])
    dry = hy.h4b(dry_rows, DRY, DRY)                                     # one table only
    assert "conf21" not in dry and set(dry["table"]["origin_set"]) == {"DRY"}
    assert dry["overall"]["verdict_full"] == dry["overall"]["verdict"]


def test_h4b_dev_side_has_counts_and_no_verdict():
    dev = [date(2019, 1, 1), date(2019, 2, 1), date(2019, 3, 1), date(2019, 4, 1)]
    rows = [{"origin": T(o), "target": t, "V": 1.0, "L": 2.0 if i < 3 else 0.0,
             "lost_originals_n": 1 if i == 0 else 0} for i, o in enumerate(dev) for t in TARGETS3]
    out = hy.h4b_dev(pd.DataFrame(rows), dev)
    t = out["table"].set_index("target")
    assert not any("verdict" in c or c == "need" for c in t.columns)
    assert (t["late_larger"] == 3).all() and (t["share"] == 0.75).all()
    assert set(t["role"]) == {"descriptive"} and set(t["label"]) == {"seen"}
    assert set(t["split"]) == {"dev"} and set(t["n_origins"]) == {4}
    assert len(out["per_origin"]) == 12 and len(out["lost_originals"]) == 3
    assert "no DEV verdict" in out["note"]
    with pytest.raises(ValueError, match="DEV origins only"):
        hy.h4b_dev(pd.DataFrame(rows).assign(origin=T(CONF19[0])), CONF19[:1])


# ---- H5 and F2 (§7.11, §7.12) ------------------------------------------------------------
def test_h5_line():
    assert hy.H5_LINE.startswith("H5 (cold start): not evaluable on CONF")
    assert "never testable on a sealed split" in hy.H5_LINE and "\n" not in hy.H5_LINE


F2_SERIES = {"provider": ["P1", "P2", "P3", "P4"], "icb": ["QA", "QB"], "region": ["Y1"],
             "england": ["ENGLAND"]}
F2_MEDIAN = {"P1": 100, "P2": 200, "P3": 300, "P4": 400, "QA": 300, "QB": 700, "Y1": 1000,
             "ENGLAND": 1000}


def f2_forecasts(model: str, levels, skew: dict | None = None) -> pd.DataFrame:
    """Long forecasts with median F2_MEDIAN (times skew[series]) at every W5 origin."""
    g = pd.concat([pd.MultiIndex.from_product(
        [F2_SERIES[lv], TARGETS3, pd.DatetimeIndex([T(o) for o in W5]), range(1, 7), QS],
        names=["series", "target", "origin", "horizon", "quantile"]).to_frame(index=False)
        .assign(level=lv) for lv in levels], ignore_index=True)
    med = g["series"].map(F2_MEDIAN) * g["series"].map(skew or {}).fillna(1.0)
    return g.assign(value=med * (0.8 + 0.4 * g["quantile"]), model=model, mode="asof", scale=1.0)


def test_f2_median_non_additivity_label_and_wis_intervals():
    ref_label, m2_label = stage_f.F2_REFERENCE, "M2 frozen (m2d_corr)"
    ref_name = f"{NAMES['m1_v3_raw']}+pooled"
    contenders = {ref_label: f2_forecasts(ref_name, stage_f.LEVELS),
                  m2_label: f2_forecasts(NAMES["m2"], ("icb", "region", "england"),
                                         skew={"Y1": 1.01, "ENGLAND": 1.01})}
    sc = {ref_label: pd.concat([scored(F2_SERIES[lv], W5, horizons=range(1, 7), model=ref_name,
                                       level=lv, failed=0.0, seed=i)
                                for i, lv in enumerate(stage_f.LEVELS)], ignore_index=True)}
    m2 = sc[ref_label][sc[ref_label]["level"] != "provider"].assign(model=NAMES["m2"],
                                                                     failed=False)
    m2["wis"] = m2["wis"] * m2["target"].map({"att_all": 1.1, "att_type1": 1.2, "adm_via_ae": 1.3})
    sc[m2_label] = m2
    icb_of, region_of = {"P1": "QA", "P2": "QA", "P3": "QB", "P4": "QB"}, {"QA": "Y1", "QB": "Y1"}
    out = hy.f2(contenders, sc, icb_of, region_of, W5)
    t = out["table"].set_index(["model", "level"])
    assert (t.loc[m2_label, "gap_label"] == hy.MEDIAN_NON_ADDITIVITY).all()
    assert (t.loc[ref_label, "gap_label"] == "coherence gap").all()
    assert t.loc[(m2_label, "region"), "coh_gap_mean"] == pytest.approx(10 / 1010)
    assert t.loc[(ref_label, "icb"), "coh_gap_mean"] == pytest.approx(0.0)
    assert all(f"cov50_h{h}" in t.columns for h in range(1, 7))
    w = out["wis"].set_index(["model", "level", "target"])
    for lv in ("icb", "region", "england"):
        assert w.loc[(m2_label, lv, "att_type1"), "rel"] == pytest.approx(0.2)
        gm = w.loc[(m2_label, lv, "geometric mean"), "rel"]
        assert gm == pytest.approx(np.exp(np.mean(np.log([1.1, 1.2, 1.3]))) - 1)
        assert gm == pytest.approx(t.loc[(m2_label, lv), "wis_rel_m1"], abs=1e-12)
    eng = w.loc[(m2_label, "england", "att_all")]
    assert np.isnan(eng["rel_lo"]) and np.isnan(eng["rel_hi"]) and eng["note"] == hy.ENGLAND_NA
    assert w.loc[(m2_label, "region", "att_all"), "note"] == "caution: bootstrap over 1 series"
    cells = out["cells"]
    assert set(cells["stat"]) == {"cov90", "cov50"} and set(cells["level"]) == {"icb", "region",
                                                                                 "england"}
    assert cells.loc[cells["stat"] == "cov50", "met"].isna().all()
    assert out["failed_dropped"] is not None
    for part in ("table", "wis", "cells"):
        assert set(out[part]["mode"]) == {"asof"} and set(out[part]["split"]) == {"conf"}
    with pytest.raises(ValueError, match="no failed column"):
        hy.f2(contenders, {**sc, ref_label: sc[ref_label].drop(columns="failed")}, icb_of,
              region_of, W5)


def test_f2_coherence_gap_leaves_out_failed_and_non_positive_aggregates():
    """An all-zero issued ICB forecast makes stage_f's gap infinite; F2 leaves it out and
    counts it. G1-failed forecasts are left out wherever they are the aggregate or a child:
    ICB QA at W5[0] (failed and zero) and provider P3 at W5[1] (a child of QB)."""
    ref_label, ref_name = stage_f.F2_REFERENCE, f"{NAMES['m1_v3_raw']}+pooled"
    fc = f2_forecasts(ref_name, stage_f.LEVELS)
    fc.loc[(fc["series"] == "QA") & (fc["origin"] == T(W5[0])), "value"] = 0.0
    sc = {ref_label: pd.concat([scored(F2_SERIES[lv], W5, horizons=range(1, 7), model=ref_name,
                                       level=lv, failed=0.0, seed=i)
                                for i, lv in enumerate(stage_f.LEVELS)], ignore_index=True)}
    icb_of, region_of = {"P1": "QA", "P2": "QA", "P3": "QB", "P4": "QB"}, {"QA": "Y1", "QB": "Y1"}
    plain = stage_f.f2_table({ref_label: fc}, sc, icb_of, region_of, origins=W5)
    assert np.isinf(plain.set_index("level").loc["icb", "coh_gap_mean"])
    n = 3 * 6                                                            # targets x horizons
    zero_only = hy.f2({ref_label: fc}, sc, icb_of, region_of, W5)["table"].set_index("level")
    assert zero_only.loc["icb", "coh_gap_excluded_nonpositive"] == n
    assert zero_only.loc["icb", "coh_gap_excluded_failed"] == 0
    assert zero_only.loc["icb", "coh_gap_mean"] == 0.0 and zero_only.loc["icb", "coh_gap_n"] == 9 * n
    assert zero_only.loc["region", "coh_gap_max"] == pytest.approx(0.3)   # 1000 against 700
    key = ["origin", "target", "series", "horizon", "level"]
    failed = fc.loc[((fc["series"] == "QA") & (fc["origin"] == T(W5[0])))
                    | ((fc["series"] == "P3") & (fc["origin"] == T(W5[1]))), key].drop_duplicates()
    out = hy.f2({ref_label: fc}, sc, icb_of, region_of, W5, failed={ref_label: failed})
    t = out["table"].set_index("level")
    assert t.loc["icb", ["coh_gap_n", "coh_gap_excluded_failed",
                         "coh_gap_excluded_nonpositive"]].tolist() == [8 * n, 2 * n, 0]
    assert t.loc["region", ["coh_gap_n", "coh_gap_excluded_failed"]].tolist() == [4 * n, n]
    assert t.loc["england", ["coh_gap_n", "coh_gap_excluded_failed"]].tolist() == [5 * n, 0]
    assert np.isfinite(t["coh_gap_mean"]).all() and (t["coh_gap_max"] == 0.0).all()
    cols = list(out["table"].columns)
    assert cols[cols.index("coh_gap_max") + 1:cols.index("coh_gap_max") + 4] == list(hy.GAP_COUNTS)
    gap_cols = ["coh_gap_mean", "coh_gap_max", *hy.GAP_COUNTS]
    pd.testing.assert_frame_equal(out["failed_dropped"]["table"][gap_cols],
                                  out["table"][gap_cols])               # both variants share it
    g = hy.coherence_gaps(fc, icb_of, region_of, failed)
    assert set(g["excluded"]) == {"", hy.GAP_FAILED} and g["gap"].notna().sum() == 17 * n


# ---- DEV side by side (§7.13, §11) -------------------------------------------------------
DEV_WINTER = [date(y, m, 1) for y in range(2018, 2023) for m in (10, 11, 12)] + \
    [date(y, 1, 1) for y in range(2019, 2024)] + [date(2023, 10, 1)]
SEASON_WIS = {"2018/19": 10.0, "2019/20": 20.0, "2020/21": 30.0, "2021/22": 40.0,
              "2022/23": 50.0, "2023/24": 1000.0}


def test_dev_season_table_excludes_the_2023_24_fragment_from_min_and_max():
    rows = scored(4, DEV_WINTER, horizons=(1, 3))
    rows["wis"] = [SEASON_WIS[stats.season(p)] if w else -1.0
                   for p, w in zip(rows["period"], rows["winter"])]
    dev = hy.dev_seasons(lambda r: {"wis": r["wis"].mean()}, rows)
    assert dev["season"].tolist() == list(SEASON_WIS)
    assert dev["value"].tolist() == list(SEASON_WIS.values())            # winter h3 rows only
    frag = dev.set_index("season").loc["2023/24"]
    assert frag["fragment"] and not frag["in_range"] and frag["n_origins"] == 1
    assert dev.set_index("season").loc["2018/19", "n_origins"] == 4
    f = hy.dev_flags({"wis": 45.0}, dev).iloc[0]
    assert (f["dev_min"], f["dev_max"], f["n_seasons"]) == (10.0, 50.0, 5)
    assert flag(f["outside"]) is False
    assert flag(hy.dev_flags({"wis": 999.0}, dev)["outside"].iloc[0]) is True   # 2023/24 left out
    with pytest.raises(ValueError, match="DEV"):
        hy.dev_seasons(lambda r: {"wis": 0.0}, scored(4, W5))


def test_dev_seasons_on_a_dict_of_frames_with_a_table_statistic():
    frames = h4_frames()
    dev = {k: f.assign(origin=f["origin"] - pd.DateOffset(years=5)) for k, f in frames.items()}
    for f in dev.values():
        m = f["origin"].dt.year * 12 + f["origin"].dt.month + 1
        f["period"] = pd.to_datetime(pd.DataFrame({"year": m // 12, "month": m % 12 + 1, "day": 1}))
    out = hy.dev_seasons(lambda fr: hy.h4(fr, sorted(set().union(
        *(set(f["origin"]) for f in fr.values()))), loo=False)["table"][["key", "target", "rel"]],
        dev)
    assert set(out["season"]) == {"2018/19", "2019/20"}
    assert (out["rel"].abs() < 1e-12).all()
    flags = hy.dev_flags(pd.DataFrame({"key": ["b1"], "target": ["att_all"], "rel": [0.1]}), out,
                         keys=("key", "target"), value="rel")
    assert flags["outside"].tolist() == [True]


def test_dev_origin_years_and_coverage_flags():
    origins = [date(2019, m, 1) for m in (10, 11, 12)] + \
        [date(y, m, 1) for y in (2021, 2022, 2023) for m in range(7, 13)]
    dev_rows = scored(6, origins, horizons=range(1, 7), model=NAMES["m1"], seed=21)
    cells = hy.dev_origin_years(dev_rows)
    assert sorted(cells["oyear"].unique()) == [2021, 2022, 2023]          # 2019: three origins
    assert cells["assessed"].all() and (cells["origins"] >= 6).all()
    conf = scored(6, CONF19, horizons=range(1, 7), model=NAMES["m1"], seed=22)
    conf_cells = hy.origin_year_cells(conf)
    pooled = hy.coverage_by_horizon(conf, CONF19, {})
    f = hy.dev_coverage_flags(conf_cells, cells, pooled)
    assert len(f) == 12 and "conf_pooled" in f.columns
    lo = cells.groupby("horizon")["value"].min()
    hi = cells.groupby("horizon")["value"].max()
    expect = [not (lo[h] <= x <= hi[h]) for x, h in zip(f["conf"], f["horizon"])]
    assert f["outside"].tolist() == expect
    with pytest.raises(ValueError, match="stats"):
        hy.dev_coverage_flags(hy.origin_year_cells(conf, "cov50"), cells)
    with pytest.raises(ValueError, match="mixes splits"):
        hy.coverage_by_horizon(pd.concat([dev_rows, conf]), [*origins, *CONF19], {})


# ---- G1 variants -------------------------------------------------------------------------
def test_variants():
    rows = scored(3, W5)
    assert [n for n, _ in hy.variants(rows)] == ["as_issued"]
    marked = scored(3, W5, failed=0.3, seed=2)
    (_, issued), (_, dropped) = hy.variants(marked)
    assert issued is marked and len(dropped) == int((~marked["failed"]).sum())
    with pytest.raises(ValueError, match="no G1 flag"):
        hy.variants(marked.assign(failed=np.where(marked["failed"], True, np.nan)))


def test_unmarked_g1_base_frames_raise():
    """A G1 base (raw, + pooled or + MinT) without ``failed`` would lose its failed-dropped
    variant and show zero failed counts, with no sign; models outside G1's scope need none."""
    unmarked = "no failed column"
    with pytest.raises(ValueError, match=f"primary: .*{unmarked}"):
        hy.primary(scored(4, CONF19, horizons=range(1, 7), model=hy.PRIMARY_MODEL), CONF19,
                   D7_FOLD)
    ref = scored(4, W5)
    with pytest.raises(ValueError, match=f"H1: .*{unmarked}"):
        hy.h1(pd.concat([ref, ref.assign(model=NAMES["m1"]),
                         ref.assign(model=NAMES["m1_v3_raw"])], ignore_index=True), W5)
    frames = h4_frames()
    frames[("b1", "asof")] = frames[("b1", "asof")].drop(columns="failed")   # B2 still marked
    with pytest.raises(ValueError, match=f"H4 b1/asof: .*{unmarked}"):
        hy.h4(frames, W5, loo=False)
    with pytest.raises(ValueError, match=f"H4 b1/asof: .*{unmarked}"):
        hy.h4_original(frames, W5, {})
    h3f = h3_frames(icb=[-0.1] * 5, provider=[0.0] * 5)
    h3f[("b2", "mint")] = h3f[("b2", "mint")].drop(columns="failed")
    with pytest.raises(ValueError, match=f"H3 b2/mint: .*{unmarked}"):
        hy.h3(h3f, W5, loo=False)
    b1 = NAMES["b1"]
    raw = scored(4, CONF19, model=b1, failed=0.0)
    pooled = raw.assign(model=f"{b1}+pooled")
    with pytest.raises(ValueError, match=f"headline {b1}\\+pooled: .*{unmarked}"):
        hy.headline({b1: raw}, {b1: pooled.drop(columns="failed")}, CONF19, {})
    with pytest.raises(ValueError, match=f"ICB raw ETS: .*{unmarked}"):
        hy.headline({b1: raw}, {b1: pooled}, CONF19, {},
                    icb_raw_ets=scored(ICBS, CONF19, model=b1, level="icb"))
    for m in ("b0", "m1", "m2"):
        hy._need_g1(ref.assign(model=NAMES[m]), m)
