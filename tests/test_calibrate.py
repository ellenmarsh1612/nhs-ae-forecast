"""Stage D calibration layers: delayed feedback, conformal widening, DtACI, shrinkage."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest
from test_evaluate import make_vintages

from nhs_ae.calibrate.online import DtACI, calibrate, first_release
from nhs_ae.ingest.recover import month_range
from nhs_ae.models.base import QUANTILES


def synthetic(n_origins=40, n_series=30, sd_true=0.10, sd_model=0.05, shock_from=None, seed=0):
    """Forecast table + first-release table. The model's quantiles assume log-normal noise
    with sd ``sd_model``; outturns have sd ``sd_true`` (so raw intervals are too narrow).
    Each h-step forecast resolves exactly h months after its origin."""
    rng = np.random.default_rng(seed)
    from scipy import stats
    z = stats.norm.ppf(QUANTILES)
    origins = pd.date_range("2016-01-01", periods=n_origins, freq="MS")
    rows, fr = [], []
    for o in origins:
        for s in range(n_series):
            for h in (1, 2, 3):
                period = o + pd.DateOffset(months=h - 1)
                centre = np.log(1000.0)
                for q, zq in zip(QUANTILES, z):
                    rows.append((o, "asof", "m", "provider", "att_all", f"S{s:02d}", h, period,
                                 q, float(np.exp(centre + sd_model * zq)), 10.0))
    fc = pd.DataFrame(rows, columns=["origin", "mode", "model", "level", "target", "series",
                                     "horizon", "period", "quantile", "value", "scale"])
    periods = pd.date_range(origins[0], origins[-1] + pd.DateOffset(months=3), freq="MS")
    for p in periods:
        for s in range(n_series):
            sd = sd_true * (3 if shock_from is not None and p >= shock_from else 1)
            fr.append(("att_all", f"S{s:02d}", p, float(np.exp(np.log(1000.0) + rng.normal(0, sd))),
                       p + pd.DateOffset(months=1)))       # published the month after
    fr = pd.DataFrame(fr, columns=["target", "series", "period", "y_first", "resolved"])
    return fc, fr


def _cov90(cal, fr, method, origins_from):
    c = cal[cal["model"] == f"m+{method}"]
    w = c.pivot_table(index=["origin", "series", "horizon", "period"], columns="quantile",
                      values="value").reset_index().merge(fr, on=["series", "period"])
    w = w[w["origin"] >= origins_from]
    return float(((w[0.05] <= w["y_first"]) & (w["y_first"] <= w[0.95])).mean())


def test_no_future_outturn_changes_an_earlier_interval():
    fc, fr = synthetic(n_origins=24)
    cut = pd.Timestamp("2017-01-01")
    fr2 = fr.copy()
    later = fr2["resolved"] > cut                       # outturns not yet published at `cut`
    fr2.loc[later, "y_first"] *= 3.0
    a = calibrate(fc, fr)
    b = calibrate(fc, fr2)
    key = ["model", "origin", "series", "horizon", "quantile"]
    a, b = a.sort_values(key).reset_index(drop=True), b.sort_values(key).reset_index(drop=True)
    early = a["origin"] <= cut
    np.testing.assert_allclose(a.loc[early, "value"], b.loc[early, "value"])
    assert not np.allclose(a.loc[~early, "value"], b.loc[~early, "value"])


def test_conformal_repairs_too_narrow_intervals():
    fc, fr = synthetic(n_origins=40)
    cal = calibrate(fc, fr)
    raw = fc.assign(model="m+raw")
    assert _cov90(raw, fr, "raw", pd.Timestamp("2017-06-01")) < 0.75   # sd 0.05 vs 0.10
    for m in ("pooled", "series", "dtaci"):
        assert 0.84 <= _cov90(cal, fr, m, pd.Timestamp("2017-06-01")) <= 0.96, m


def test_dtaci_widens_after_misses_and_relaxes_after_hits():
    learner = DtACI(n_series=2, a=0.1)
    start = learner.level(np.array([0, 1]))
    for _ in range(5):                                  # series 0 keeps missing (beta = 0)
        learner.update(np.array([0, 1]), np.array([0.0, 0.9]))
    lv = learner.level(np.array([0, 1]))
    assert lv[0] < start[0] < lv[1]                     # lower alpha = wider interval
    assert np.allclose(learner.w.sum(axis=1), 1.0)


def test_dtaci_expert_update_matches_aci_rule():
    learner = DtACI(n_series=1, a=0.1, gammas=(0.05,))
    learner.update(np.array([0]), np.array([0.0]))     # a miss for alpha 0.1 > beta 0
    assert learner.alpha[0, 0] == pytest.approx(0.1 + 0.05 * (0.1 - 1.0))
    learner.update(np.array([0]), np.array([0.5]))     # a hit
    assert learner.alpha[0, 0] == pytest.approx(0.055 + 0.05 * 0.1)


def test_dtaci_adapts_to_a_shock_faster_than_pooled():
    fc, fr = synthetic(n_origins=48, shock_from=pd.Timestamp("2018-06-01"), seed=1)
    cal = calibrate(fc, fr)
    after = pd.Timestamp("2018-10-01")
    assert _cov90(cal, fr, "dtaci", after) > _cov90(cal, fr, "pooled", after) - 0.02


def test_first_release_uses_first_publication_and_late_submitters():
    v = make_vintages()
    v.loc[v["is_total"], "org_code"] = "ENGLAND"
    fr = first_release(v, month_range(date(2016, 6, 1), date(2017, 6, 1)), targets=("att_type1",))
    r = fr[(fr["series"] == "RAA") & (fr["period"] == "2016-05-01")].iloc[0]
    assert r["resolved"] == pd.Timestamp("2016-06-01")   # May data out on 9 June
    orig = v[(v.org_code == "RAA") & (v.period == "2016-05-01") & (v.metric == "att_type1")]
    assert r["y_first"] == pytest.approx(orig.sort_values("snapshot")["value"].iloc[0])
    # RCC never submitted month 10 (2017-02): it is simply absent
    assert fr[(fr["series"] == "RCC") & (fr["period"] == "2017-02-01")].empty


def test_enbpi_quantiles_are_ordered_and_cover_every_series():
    from nhs_ae.models.enbpi import EnbPI
    rng = np.random.default_rng(3)
    idx = pd.date_range("2016-01-01", periods=60, freq="MS")
    season = 1 + 0.1 * np.sin(2 * np.pi * (idx.month - 1) / 12)
    panel = pd.DataFrame({f"S{i}": (500 + 100 * i) * season * np.exp(rng.normal(0, 0.05, 60))
                          for i in range(12)}, index=idx)
    fc = EnbPI(n_boot=4).fit_predict(panel, horizons=(1, 3))
    assert set(fc["series"]) == set(panel.columns) and set(fc["horizon"]) == {1, 3}
    wide = fc.pivot_table(index=["series", "horizon"], columns="quantile", values="value")
    assert wide.notna().all().all()
    assert (np.diff(wide.to_numpy(), axis=1) >= 0).all()
    assert (wide[0.5] / panel.iloc[-12:].mean().reindex(wide.index.get_level_values(0)).to_numpy()
            ).between(0.7, 1.4).all()
