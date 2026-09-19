"""Guard G1 (amendment "Guard G1 registered", 2026-09-13): failed base forecasts."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy import stats
from test_calibrate import synthetic

from nhs_ae.calibrate import g1
from nhs_ae.calibrate.online import calibrate
from nhs_ae.evaluate import stage_f
from nhs_ae.models.base import QUANTILES

T0 = pd.Timestamp("2019-01-01")


def _fc(rows):
    """rows: (series, values) at origin T0, horizon 1, provider level."""
    out = [(T0, "att_all", s, 1, "provider", q, v) for s, vals in rows for q, v in zip(QUANTILES, vals)]
    return pd.DataFrame(out, columns=["origin", "target", "series", "horizon", "level", "quantile", "value"])


def test_failed_needs_nine_exact_zeros_and_a_positive_last_month():
    z = [0.0] * 9
    fc = _fc([("A", z), ("B", z), ("C", [0.0] * 8 + [1.0]), ("D", [0.0] * 8 + [np.nan]), ("E", z)])
    last = pd.DataFrame({"origin": T0, "level": "provider", "target": "att_all",
                         "series": ["A", "B", "C", "D"], "last_value": [120.0, 0.0, 50.0, 50.0]})
    f = g1.failed_forecasts(fc, last)
    assert f["series"].tolist() == ["A"]                   # B closed (last 0), C/D not all zero, E no history
    assert f[g1.KEY + ["level"]].iloc[0].tolist() == [T0, "att_all", "A", 1, "provider"]
    assert set(g1.all_zero(fc, last)["series"]) == {"A", "B", "E"}


def _with_failures(n_fail=10):
    fc, fr = synthetic(n_origins=30)
    bad_origin = fc["origin"].unique()[14]
    bad = (fc["origin"] == bad_origin) & fc["series"].isin([f"S{s:02d}" for s in range(n_fail)])
    fc.loc[bad, "value"] = 0.0
    failed = fc.loc[bad, ["origin", "target", "series", "horizon", "level"]].drop_duplicates()
    return fc, fr, failed, bad_origin


def test_g1_calibration_is_calibration_without_the_failed_forecasts():
    fc, fr, failed, bad_origin = _with_failures()
    guarded = calibrate(fc, fr, failed=failed)
    key = ["model", "origin", "series", "horizon", "quantile"]
    dropped_in = fc.merge(failed.assign(_f=1), how="left", on=list(failed.columns))
    without = calibrate(fc[dropped_in["_f"].isna().to_numpy()], fr)
    is_failed = g1.mask(guarded, failed, ["origin", "target", "series", "horizon"])
    rest = guarded[~is_failed].sort_values(key).reset_index(drop=True)
    without = without.sort_values(key).reset_index(drop=True)
    pd.testing.assert_frame_equal(rest[key], without[key])
    np.testing.assert_allclose(rest["value"], without["value"])          # pooled, series and DtACI
    assert (guarded.loc[is_failed, "value"] == 0.0).all()                 # issued as produced
    assert is_failed.sum() == len(failed) * 9 * 3                          # 9 quantiles x 3 methods
    # and the guard matters: without it the zero forecasts widen later pooled intervals
    naive = calibrate(fc, fr).sort_values(key).reset_index(drop=True)
    later = (naive["origin"] > bad_origin + pd.DateOffset(months=3)) & (naive["model"] == "m+pooled")
    g = guarded.sort_values(key).reset_index(drop=True)
    assert not np.allclose(naive.loc[later, "value"], g.loc[later, "value"])


def test_mark_scores_failed_forecasts_as_issued_and_not_covered():
    s = pd.DataFrame({"origin": [T0, T0], "target": "att_all", "series": ["A", "B"], "horizon": 1,
                      "wis": [5.0, 7.0], "cov50": [True, True], "cov90": [True, True]})
    failed = pd.DataFrame({"origin": [T0], "target": ["att_all"], "series": ["A"], "horizon": [1]})
    m = g1.mark(s, failed, g1.KEY)
    assert m["failed"].tolist() == [True, False]
    assert m["cov90"].tolist() == [False, True] and m["cov50"].tolist() == [False, True]
    assert m["wis"].tolist() == [5.0, 7.0]


# ---- reconciliation ----------------------------------------------------------------------
ICB = {"P1": "I1", "P2": "I1", "P3": "I2"}
BASE = {"P1": 100.0, "P2": 200.0, "P3": 300.0, "I1": 300.0, "I2": 300.0, "R1": 600.0, "ENGLAND": 600.0}
LEVEL = {"P1": "provider", "P2": "provider", "P3": "provider", "I1": "icb", "I2": "icb",
         "R1": "region", "ENGLAND": "england"}
ORIGINS = pd.date_range("2019-01-01", periods=8, freq="MS")


def _hierarchy(monkeypatch, zero):
    rng = np.random.default_rng(0)
    z = stats.norm.ppf(QUANTILES)
    cal, fr = [], []
    for o in ORIGINS:
        for s, b in BASE.items():
            vals = np.zeros(9) if (o, s) in zero else b * np.exp(0.05 * z)
            cal += [(o, "asof", "m+pooled", LEVEL[s], "att_all", s, 1, o, q, v, 1.0) for q, v in zip(QUANTILES, vals)]
            fr.append(("att_all", s, o, b * np.exp(rng.normal(0, 0.05)), o + pd.DateOffset(months=1), LEVEL[s]))
    cal = pd.DataFrame(cal, columns=stage_f.COLS)
    fr = pd.DataFrame(fr, columns=["target", "series", "period", "y_first", "resolved", "level"])
    monkeypatch.setattr(stage_f, "TARGETS", ["att_all"])
    monkeypatch.setattr(stage_f, "members", lambda v: pd.Series(ICB))
    monkeypatch.setattr(stage_f, "icb_region_map", lambda: pd.Series({"I1": "R1", "I2": "R1"}))
    monkeypatch.setattr(stage_f, "calibrated", lambda name, lv, v, work=None, failed=None: cal[cal["level"] == lv])
    monkeypatch.setattr(stage_f, "first_release_level", lambda lv: fr[fr["level"] == lv])
    seen = {"bottom": {}, "parents": {}, "hist": []}
    real_s, real_w = stage_f.summing_matrix, stage_f.error_cov

    def spy_s(bottom, parents):
        seen["bottom"][len(seen["bottom"])] = list(bottom)
        seen["parents"][len(seen["parents"])] = dict(parents)
        return real_s(bottom, parents)

    def spy_w(hist, *a):
        seen["hist"].append(hist)
        return real_w(hist, *a)
    monkeypatch.setattr(stage_f, "summing_matrix", spy_s)
    monkeypatch.setattr(stage_f, "error_cov", spy_w)
    return cal, seen


def test_reconciliation_routes_failed_forecasts_around_mint(monkeypatch, tmp_path):
    t_p, t_e = ORIGINS[4], ORIGINS[6]
    _, seen = _hierarchy(monkeypatch, zero={(t_p, "P1"), (t_e, "ENGLAND")})
    failed = {lv: pd.DataFrame(columns=[*g1.KEY, "level"]) for lv in stage_f.LEVELS}
    failed["provider"] = pd.DataFrame([(t_p, "att_all", "P1", 1, "provider")], columns=[*g1.KEY, "level"])
    failed["england"] = pd.DataFrame([(t_e, "att_all", "ENGLAND", 1, "england")], columns=[*g1.KEY, "level"])
    rec = stage_f.reconcile_model("m", None, origins=list(ORIGINS), work=tmp_path, failed=failed)
    # every base forecast comes back once (the function checks the counts), failed ones as issued
    for o, s in ((t_p, "P1"), (t_e, "ENGLAND")):
        r = rec[(rec["origin"] == o) & (rec["series"] == s)]
        assert len(r) == 9 and (r["value"] == 0.0).all() and (r["model"] == "m+pooled+mint").all()
    k_p, k_e = list(ORIGINS).index(t_p), list(ORIGINS).index(t_e)
    assert "P1" not in seen["bottom"][k_p] and "I1~rest" in seen["bottom"][k_p]      # P1 joins I1's rest node
    assert "P1" in seen["bottom"][k_p + 1] and "I1~rest" not in seen["bottom"][k_p + 1]
    assert "ENGLAND" not in seen["parents"][k_e] and "ENGLAND" in seen["parents"][k_e + 1]  # drops out of S
    for h in seen["hist"]:                                                             # not in W
        assert not ((h["origin"] == t_p) & (h["series"] == "P1")).any()
        assert not ((h["origin"] == t_e) & (h["series"] == "ENGLAND")).any()
    later = seen["hist"][-1]
    assert ((later["origin"] == t_p) & (later["series"] == "P2")).any()               # others still are
    # the other series are reconciled: coherent medians at the failed provider's origin
    med = rec[(rec["origin"] == ORIGINS[-1]) & (rec["quantile"] == 0.5)].set_index("series")["value"]
    assert med["I1"] == pytest.approx(med["P1"] + med["P2"], rel=1e-6)


def test_guarded_output_never_goes_to_the_stage_f_cache():
    f = pd.DataFrame(columns=[*g1.KEY, "level"])
    with pytest.raises(ValueError):
        stage_f.calibrated("b1", "icb", None, work=None, failed=f)
    with pytest.raises(ValueError):
        stage_f.reconcile_model("b1", None, work=stage_f.WORK, failed={lv: f for lv in stage_f.LEVELS})
