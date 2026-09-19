"""Stage G occupancy model on synthetic trusts (no real NHS numbers)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nhs_ae.decide.occupancy import (
    THRESHOLD,
    breach_table,
    cost_loss_expense,
    fit_coefficients,
    occupancy_draws,
    quarterly_admissions,
    sample_quantiles,
)
from nhs_ae.models.base import QUANTILES


def synthetic_trusts(n_trusts=12, seed=0):
    """Monthly admissions and quarterly KH03-style rows with a known bed-days ratio c_j."""
    rng = np.random.default_rng(seed)
    months = pd.date_range("2017-01-01", "2023-12-01", freq="MS")
    true_c = {f"T{j:02d}": float(np.exp(rng.normal(np.log(8.0), 0.2))) for j in range(n_trusts)}
    adm = pd.DataFrame([(o, p, float(2000 + 150 * j + rng.normal(0, 50)))
                        for j, o in enumerate(true_c) for p in months],
                       columns=["org_code", "period", "adm"])
    q = quarterly_admissions(adm)
    q["c"] = q["org_code"].map(true_c)
    q["ga_occupied"] = q["c"] * q["adm"] / q["days"] * np.exp(rng.normal(0, 0.03, len(q)))
    q["ga_available"] = q["ga_occupied"] / 0.9
    q["published"] = q["quarter_start"] + pd.DateOffset(months=5)
    return adm, q[["org_code", "quarter_start", "ga_available", "ga_occupied", "published"]], true_c


def test_coefficients_recover_the_true_ratio_and_respect_publication():
    adm, kh03, true_c = synthetic_trusts()
    adm_q = quarterly_admissions(adm)
    coefs = fit_coefficients(kh03, adm_q, pd.Timestamp("2023-12-15")).set_index("org_code")
    est = np.exp(coefs["log_c"])
    assert np.allclose(est, pd.Series(true_c).reindex(est.index), rtol=0.05)
    early = fit_coefficients(kh03, adm_q, pd.Timestamp("2018-06-01"))
    assert (early["beds_quarter"] <= pd.Timestamp("2018-01-01")).all()   # 5-month publication lag
    pooled = fit_coefficients(kh03, adm_q, pd.Timestamp("2023-12-15"), pooled_only=True)
    assert pooled["log_c"].nunique() == 1


def test_covid_quarters_are_not_used():
    adm, kh03, _ = synthetic_trusts()
    kh03.loc[kh03["quarter_start"].between("2020-01-01", "2021-06-30"), "ga_occupied"] *= 0.5
    coefs = fit_coefficients(kh03, quarterly_admissions(adm), pd.Timestamp("2021-12-15"))
    assert (coefs["s"] < 0.1).all()                     # the halved quarters would inflate s


def test_quantile_sampling_reproduces_the_forecast_quantiles():
    rng = np.random.default_rng(1)
    q = np.array([[np.exp(np.log(1000) + 0.1 * z) for z in
                   __import__("scipy").stats.norm.ppf(QUANTILES)]])
    draws = sample_quantiles(q, QUANTILES, 200_000, rng)
    np.testing.assert_allclose(np.quantile(draws[0], QUANTILES), q[0], rtol=0.01)


def test_escalation_beds_bring_breach_probability_to_target():
    rng = np.random.default_rng(2)
    occ = rng.normal(500, 25, size=(3, 50_000))
    beds = np.array([520.0, 560.0, 700.0])
    t = breach_table(occ, beds)
    assert t["p_breach"].iloc[0] > t["p_breach"].iloc[1] > t["p_breach"].iloc[2]
    after = (occ / (beds + t["escalation_beds"].to_numpy())[:, None] > THRESHOLD).mean(axis=1)
    assert (after[:2] <= 0.2 + 1e-3).all() and t["escalation_beds"].iloc[2] == 0


def test_cost_loss_expense():
    p, event = np.array([0.05, 0.3, 0.6]), np.array([True, False, True])
    assert cost_loss_expense(p, event, 0.25) == pytest.approx((1 + 0.25 + 0.25) / 3)


def test_occupancy_draws_scale_with_coefficient():
    rng = np.random.default_rng(3)
    coefs = pd.DataFrame({"log_c": np.log([5.0, 10.0]), "s": [0.0, 0.0]})
    occ = occupancy_draws(np.full((2, 10), 3000.0), np.array([30.0, 30.0]), coefs, rng)
    assert np.allclose(occ[0], 500.0) and np.allclose(occ[1], 1000.0)


def test_footprint_break_drops_pre_merger_quarters_and_versions_are_as_of():
    adm, kh03, true_c = synthetic_trusts(n_trusts=3)
    t = kh03["org_code"] == "T00"
    after = kh03["quarter_start"] >= "2022-01-01"
    kh03.loc[t & after, ["ga_available", "ga_occupied"]] *= 2.5     # absorbs a neighbour
    adm.loc[(adm["org_code"] == "T00") & (adm["period"] >= "2022-01-01"), "adm"] *= 2.5
    kh03.loc[t & after, "ga_occupied"] *= 1.2                        # ... with a higher ratio
    adm_q = quarterly_admissions(adm)
    c = fit_coefficients(kh03, adm_q, pd.Timestamp("2023-12-15")).set_index("org_code")
    assert np.exp(c.loc["T00", "log_c"]) == pytest.approx(1.2 * true_c["T00"], rel=0.08)
    assert c.loc["T00", "n"] == 7          # 7 post-merger quarters published; window is 8
    # a later revision is invisible before its publication date
    rev = kh03[kh03["org_code"] == "T01"].tail(1).assign(
        ga_occupied=lambda d: d["ga_occupied"] * 3, published=pd.Timestamp("2025-01-01"))
    k2 = pd.concat([kh03, rev])
    a = fit_coefficients(k2, adm_q, pd.Timestamp("2024-06-01")).set_index("org_code")
    b = fit_coefficients(kh03, adm_q, pd.Timestamp("2024-06-01")).set_index("org_code")
    assert a.loc["T01", "log_c"] == pytest.approx(b.loc["T01", "log_c"])
