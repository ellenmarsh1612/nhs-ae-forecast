"""Cluster-robust mean and slope used by the median-exceedance decomposition."""

from __future__ import annotations

import numpy as np
import pytest

from nhs_ae.evaluate.stage_e_exceedance import cluster_mean, cluster_slope


def test_singleton_clusters_give_the_usual_standard_error_of_a_mean():
    rng = np.random.default_rng(0)
    x = rng.normal(size=200)
    m, se = cluster_mean(x, np.arange(200))
    assert m == pytest.approx(x.mean())
    assert se == pytest.approx(x.std(ddof=1) / np.sqrt(200))


def test_clustering_widens_the_interval_when_clusters_share_a_shock():
    rng = np.random.default_rng(1)
    g = np.repeat(np.arange(20), 30)
    x = rng.normal(size=600) + np.repeat(rng.normal(size=20), 30)
    _, se_cl = cluster_mean(x, g)
    _, se_iid = cluster_mean(x, np.arange(600))
    assert se_cl > 2 * se_iid


def test_slope_point_estimate_matches_least_squares():
    rng = np.random.default_rng(2)
    h = np.tile(np.arange(1, 7), 50).astype(float)
    x = 0.02 * h + rng.normal(scale=0.1, size=h.size)
    b, se = cluster_slope(x, h, np.repeat(np.arange(50), 6))
    assert b == pytest.approx(np.polyfit(h, x, 1)[0])
    assert 0 < se < 0.01
