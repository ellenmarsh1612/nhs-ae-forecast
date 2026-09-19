"""M2 at ICB level on synthetic panels (skipped where PyMC/nutpie are not installed)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pm = pytest.importorskip("pymc")
pytest.importorskip("nutpie")

from nhs_ae.models import m2
from nhs_ae.models.base import QUANTILES


def panels(n_icb=4, months=48, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2019-01-01", periods=months, freq="MS")
    season = 1 + 0.08 * np.cos(2 * np.pi * (idx.month - 1) / 12)
    t1 = pd.DataFrame({f"I{i}": rng.poisson(8000 * (1 + 0.3 * i) * season) for i in range(n_icb)},
                      index=idx).astype(float)
    other = pd.DataFrame({c: rng.poisson(0.4 * t1[c]) for c in t1}, index=idx).astype(float)
    adm = pd.DataFrame({c: rng.poisson(0.28 * t1[c]) for c in t1}, index=idx).astype(float)
    t1.iloc[5, 1] = np.nan                                  # an unpublished month
    return {"att_type1": t1, "att_all": t1 + other, "adm_via_ae": adm}


def test_prepare_centres_on_recent_level_and_keeps_gaps():
    d = m2.prepare(panels())
    assert d.y["type1"].shape == (4, 48) and np.isnan(d.y["type1"][1, 5])
    assert np.allclose(np.exp(d.offset["type1"]), np.nanmean(d.y["type1"][:, -12:], axis=1))
    assert np.allclose(np.exp(d.offset["adm"]), 0.28, atol=0.02)


def test_design_measures_time_from_origin():
    idx = pd.date_range("2023-01-01", periods=3, freq="MS")
    x = m2.design(idx, pd.Timestamp("2022-12-01"))
    assert np.allclose(x["tau"], [1 / 12, 2 / 12, 3 / 12]) and x["F"].shape == (3, 2 * m2.K)
    assert x["booked"].all() and not x["covid"].any()


def test_fit_and_forecast_are_coherent_and_ordered():
    d = m2.prepare(panels())
    trace, _ = m2.fit(m2.build_model(d), draws=100, tune=150, chains=2, cores=2)
    fc = m2.forecast(trace, d, horizons=(1, 2))
    assert set(fc["target"]) == {"att_type1", "att_all", "adm_via_ae"}
    assert len(fc) == 3 * 4 * 2 * len(QUANTILES)
    w = fc.pivot_table(index=["target", "series", "horizon"], columns="quantile", values="value")
    assert (np.diff(w.to_numpy(), axis=1) >= 0).all()
    med = w[0.5].unstack("target")
    assert (med["att_all"] > med["att_type1"]).all()       # all types = Type 1 + other
    ratio = (med["adm_via_ae"] / med["att_type1"]).to_numpy()
    assert np.allclose(ratio, 0.28, atol=0.03)


def test_m2b_m2c_paths_fit_and_forecast():
    d = m2.prepare(panels(), region_of=pd.Series({"I0": "R1", "I1": "R1", "I2": "R2", "I3": "R2"}))
    assert list(d.region) == [0, 0, 1, 1]
    trace, _ = m2.fit(m2.build_model(d, m2.M2C_ON_B), draws=100, tune=150, chains=2, cores=2)
    assert "f_icb_type1" in trace.posterior and "lk_icb_adm" in trace.posterior
    fc = m2.forecast(trace, d, horizons=(1, 4), rung=m2.M2C_ON_B)
    w = fc.pivot_table(index=["target", "series", "horizon"], columns="quantile", values="value")
    assert w.notna().all().all() and (np.diff(w.to_numpy(), axis=1) >= 0).all()


def test_offset_falls_back_to_latest_valid_year():
    p = panels()
    p["att_all"].iloc[-14:, 2] = p["att_type1"].iloc[-14:, 2] - 5     # negative 'other' -> missing
    d = m2.prepare(p)
    assert np.isfinite(d.offset["other"]).all()
    valid = d.y["other"][2][~np.isnan(d.y["other"][2])]
    assert np.isclose(np.exp(d.offset["other"][2]), valid[-12:].mean())


def test_m2d_random_walk_is_centred_and_uncertainty_grows_with_horizon():
    d = m2.prepare(panels(months=36))
    model = m2.build_model(d, m2.M2D)
    assert "ell_type1" in [v.name for v in model.value_vars]          # levels sampled directly
    assert not any(v.name.startswith("z_") for v in model.value_vars)
    trace, _ = m2.fit(model, draws=100, tune=150, chains=2, cores=2)
    diag = m2.diagnostics(trace, m2.M2D)
    assert set(diag) >= {"rhat_max", "ess_bulk_min", "divergences"}
    fc = m2.forecast(trace, d, horizons=(1, 6), rung=m2.M2D)
    w = fc[fc.target == "att_type1"].pivot_table(index=["series", "horizon"], columns="quantile",
                                                   values="value")
    width = (w[0.95] - w[0.05]) / w[0.5]
    assert (width.xs(6, level="horizon") > width.xs(1, level="horizon")).all()


def test_centred_m2a_matches_non_centred_structure():
    d = m2.prepare(panels())
    model = m2.build_model(d, m2.M2A_C)
    names = [v.name for v in model.value_vars]
    assert "a_type1" in names and not any(n.startswith("z_a") for n in names)


def test_direct_all_models_all_types_as_its_own_series():
    d = m2.prepare(panels(months=36), clean=True)
    assert "all" in d.y and np.allclose(d.y["all"], d.y["type1"] + d.y["other"], equal_nan=True)
    model = m2.build_model(d, m2.M2A_C)
    assert "y_all" in model.named_vars and "y_other" not in model.named_vars


def test_m2d2_and_m2e_paths():
    d = m2.prepare(panels(months=48), clean=True)                    # spans the COVID window
    for rung in (m2.M2D2, m2.M2E_ON_D2):
        trace, _ = m2.fit(m2.build_model(d, rung), draws=100, tune=150, chains=2, cores=2)
        post = trace.posterior
        assert "sigma_rwc_type1" in post
        if rung.dyn_conversion:
            assert "omega_conv_icb" in post
        fc = m2.forecast(trace, d, horizons=(1, 3), rung=rung)
        w = fc.pivot_table(index=["target", "series", "horizon"], columns="quantile", values="value")
        assert w.notna().all().all() and (np.diff(w.to_numpy(), axis=1) >= 0).all()


def test_m2f_shares_a_national_walk_and_aggregates_coherently():
    region_of = pd.Series({"I0": "R1", "I1": "R1", "I2": "R2", "I3": "R2"})
    d = m2.prepare(panels(months=48), region_of=region_of, clean=True)
    rung = m2.with_factor(m2.M2D2)
    trace, _ = m2.fit(m2.build_model(d, rung), draws=100, tune=150, chains=2, cores=2)
    assert "gnat_type1" in trace.posterior and trace.posterior["gnat_type1"].shape[-2:] == (1, 48)
    fut, draws = m2.predictive_draws(trace, d, (1, 3), seed=1, rung=rung)
    agg = m2.aggregate_forecast(draws, d, region_of, (1, 3), fut)
    assert set(agg["level"]) == {"region", "england"} and set(agg["series"]) == {"R1", "R2", "ENGLAND"}
    # England draws are exactly the sum of the ICB draws, so its median equals the median of sums
    eng = agg[(agg.level == "england") & (agg.target == "att_type1") & (agg.horizon == 1) & (agg["quantile"] == 0.5)]
    assert np.isclose(eng["value"].iloc[0], np.median(draws["att_type1"][:, :, 0].sum(axis=1)))


def test_refactored_forecast_reproduces_quantiles_for_existing_rungs():
    d = m2.prepare(panels(months=36), clean=True)
    trace, _ = m2.fit(m2.build_model(d, m2.M2D), draws=60, tune=100, chains=2, cores=2)
    a = m2.forecast(trace, d, horizons=(1, 2), seed=5, rung=m2.M2D)
    fut, draws = m2.predictive_draws(trace, d, (1, 2), seed=5, rung=m2.M2D)
    b = m2._quantile_rows(draws, d.icbs, (1, 2), fut, m2.QUANTILES)
    assert np.allclose(a["value"], b["value"])


def test_innovation_corr_recovers_co_movement_and_draws_keep_t_marginals():
    rng = np.random.default_rng(0)
    common = rng.standard_normal(200)
    paths = np.cumsum(np.vstack([0.8 * common + 0.6 * rng.standard_normal(200) for _ in range(5)]), axis=1)
    chol = m2.innovation_corr(paths, shrink=0.0)
    r = chol @ chol.T
    assert np.allclose(np.diag(r), 1) and 0.5 < r[0, 1] < 0.8               # true 0.64
    z = np.einsum("ij,sjh->sih", chol, rng.standard_normal((20000, 5, 1)))
    x = z * np.sqrt(m2.RW_NU / rng.chisquare(m2.RW_NU, size=(20000, 1, 1)))
    from scipy import stats
    assert stats.kstest(x[:, 0, 0], stats.t(m2.RW_NU).cdf).pvalue > 0.01    # marginal t(4)
    assert np.var(x.sum(axis=1)) > 3 * np.var(x[:, 0, 0])                   # sums fatten


def test_m2d_corr_path_runs():
    d = m2.prepare(panels(months=36), region_of=pd.Series({"I0": "R1", "I1": "R1", "I2": "R2", "I3": "R2"}),
                   clean=True)
    trace, _ = m2.fit(m2.build_model(d, m2.M2D_CORR), draws=80, tune=120, chains=2, cores=2)
    _, draws = m2.predictive_draws(trace, d, (1, 3), seed=2, rung=m2.M2D_CORR)
    assert draws["att_type1"].shape[1:] == (4, 2) and np.isfinite(draws["att_type1"]).all()


def test_calendar_season_has_days_offset_and_zero_sum_month_effects():
    d = m2.prepare(panels(months=48), clean=True)
    months = pd.date_range("2024-01-01", periods=24, freq="MS")               # 2024 is a leap year
    att = m2.calendar_season(d, "type1", months)
    adm = m2.calendar_season(d, "adm", months)
    logdays = np.log(months.days_in_month.to_numpy() / 30.4375)
    effects = np.asarray(att - logdays)
    assert np.allclose(effects[:12], effects[12:])                            # same month, same effect
    assert abs(effects[:12].sum()) < 1e-9                                     # sum to zero
    assert np.isclose(att[1] - att[13], np.log(29 / 28))                      # leap-year February
    assert abs(adm[:12].sum()) < 1e-9 and np.allclose(adm[:12], adm[12:])     # no days offset


def test_m2f_r3_path_runs():
    region_of = pd.Series({"I0": "R1", "I1": "R1", "I2": "R2", "I3": "R2"})
    d = m2.prepare(panels(months=48), region_of=region_of, clean=True)
    trace, _ = m2.fit(m2.build_model(d, m2.M2F_R3), draws=80, tune=120, chains=2, cores=2)
    fut, draws = m2.predictive_draws(trace, d, (1, 3), seed=1, rung=m2.M2F_R3)
    agg = m2.aggregate_forecast(draws, d, region_of, (1, 3), fut)
    assert np.isfinite(agg["value"]).all() and set(agg["level"]) == {"region", "england"}


def test_m2f_r4_national_regime_path():
    region_of = pd.Series({"I0": "R1", "I1": "R1", "I2": "R2", "I3": "R2"})
    d = m2.prepare(panels(months=48), region_of=region_of, clean=True)      # spans the window
    trace, _ = m2.fit(m2.build_model(d, m2.M2F_R4), draws=80, tune=120, chains=2, cores=2)
    assert "sigma_gc_type1" in trace.posterior and "sigma_rwc_type1" not in trace.posterior
    _, draws = m2.predictive_draws(trace, d, (1, 3), seed=1, rung=m2.M2F_R4)
    assert np.isfinite(draws["att_all"]).all()
