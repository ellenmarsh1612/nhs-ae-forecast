"""MinT-shrink reconciliation on synthetic hierarchies."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nhs_ae.reconcile.mint import mint, reconcile_quantiles, shrink_cov, summing_matrix


def hierarchy():
    bottom = ["a", "b", "c", "d"]
    parents = {"TOTAL": bottom, "X": ["a", "b"], "Y": ["c", "d"], "EMPTY": ["zz"]}
    return summing_matrix(bottom, parents)


def test_summing_matrix_orders_aggregates_first_and_drops_empty():
    S, names = hierarchy()
    assert names == ["TOTAL", "X", "Y", "a", "b", "c", "d"]
    assert S.shape == (7, 4) and np.allclose(S[0], 1) and np.allclose(S[3:], np.eye(4))


def test_mint_output_is_coherent_and_leaves_coherent_input_unchanged():
    S, _ = hierarchy()
    rng = np.random.default_rng(0)
    W = np.diag(rng.uniform(1, 5, 7))
    yhat = rng.normal(100, 10, 7)
    rec = mint(yhat, S, W)
    assert np.isclose(rec[0], rec[3:].sum()) and np.isclose(rec[1], rec[3] + rec[4])
    coherent = S @ np.array([10.0, 20.0, 30.0, 40.0])
    assert np.allclose(mint(coherent, S, W), coherent)


def test_mint_trusts_low_variance_series():
    S, _ = hierarchy()
    yhat = np.array([200.0, 60, 60, 25, 25, 25, 25])                # total disagrees with bottoms
    trust_total = mint(yhat, S, np.diag([1e-4, 1, 1, 1, 1, 1, 1]))
    trust_bottom = mint(yhat, S, np.diag([1e4, 1e4, 1e4, 1, 1, 1, 1]))
    assert trust_total[0] == pytest.approx(200, rel=1e-3)
    assert trust_bottom[0] == pytest.approx(100, rel=1e-2)


def test_mint_infers_an_unforecast_bottom_series_from_its_parent():
    S, _ = hierarchy()
    truth = S @ np.array([10.0, 20.0, 30.0, 40.0])
    yhat = truth.copy()
    yhat[4] = np.nan                                                  # b has no base forecast
    obs = ~np.isnan(yhat)
    rng = np.random.default_rng(2)
    W = np.diag(rng.uniform(1, 5, obs.sum()))
    rec = mint(np.nan_to_num(yhat), S, W, obs)
    assert np.allclose(rec, truth)                                    # b = X − a, coherent input kept
    noisy = yhat + np.where(obs, rng.normal(0, 3, 7), 0)
    rec = mint(np.nan_to_num(noisy), S, W, obs)
    assert np.isclose(rec[0], rec[3:].sum()) and np.isclose(rec[1], rec[3] + rec[4])


def test_shrink_cov_is_positive_definite_and_uses_fallback():
    rng = np.random.default_rng(1)
    e = rng.normal(0, 1, (30, 5)) @ np.diag([1, 2, 3, 4, 5])
    e[:, 4] = np.nan                                                  # no history at all
    e[:28, 3] = np.nan                                                # two errors only
    W = shrink_cov(e, fallback_var=np.full(5, 7.0))
    assert np.all(np.linalg.eigvalsh(W) > 0)
    assert W[4, 4] == pytest.approx(7.0) and W[3, 3] == pytest.approx(7.0)
    assert W[2, 2] == pytest.approx(np.var(e[:, 2], ddof=1), rel=1e-6)


def test_reconcile_quantiles_are_coherent_per_level_and_sorted():
    S, names = hierarchy()
    q = pd.DataFrame({0.05: [90, 45, 45, 20, 20, 20, 20], 0.5: [110, 50, 50, 25, 25, 25, 25],
                      0.95: [130, 55, 55, 30, 30, 30, 30]}, index=names, dtype=float)
    rec = reconcile_quantiles(q, S, names, np.eye(7))
    for col in rec.columns:
        assert rec.loc["TOTAL", col] == pytest.approx(rec.loc[["a", "b", "c", "d"], col].sum())
    assert (np.diff(rec.to_numpy(), axis=1) >= 0).all()
