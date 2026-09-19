"""E-ensemble: quantile averaging and the coherence gap on synthetic forecasts."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nhs_ae.evaluate.stage_e_ensemble import coherence_gaps, vincentise
from nhs_ae.models.base import QUANTILES


def frame(series_values: dict[str, list[float]], level: str = "icb", model: str = "x") -> pd.DataFrame:
    rows = []
    for s, vals in series_values.items():
        for q, v in zip(QUANTILES, vals):
            rows.append({"origin": pd.Timestamp("2019-10-01"), "target": "att_all", "series": s,
                         "horizon": 3, "period": pd.Timestamp("2019-12-01"), "quantile": q,
                         "value": v, "scale": 1.0, "mode": "asof", "model": model, "level": level})
    return pd.DataFrame(rows)


def test_vincentise_averages_pointwise_and_sorts():
    ets = frame({"A": [10, 20, 30, 40, 50, 60, 70, 80, 90]})
    m2f = frame({"A": [30, 40, 50, 60, 70, 80, 90, 100, 110]})
    ens, excl = vincentise(ets, m2f, "icb")
    assert ens["value"].tolist() == pytest.approx([20, 30, 40, 50, 60, 70, 80, 90, 100])
    assert excl.empty


def test_failed_or_missing_ets_is_excluded_not_halved():
    ets = frame({"A": [0.0] * 9, "B": [np.nan] * 9, "C": [1, 2, 3, 4, 5, 6, 7, 8, 9]})
    m2f = frame({"A": list(range(100, 109)), "B": list(range(200, 209)), "C": [9, 8, 7, 6, 5, 4, 3, 2, 1]})
    ens, excl = vincentise(ets, m2f, "icb")
    got = ens.pivot_table(index="series", columns="quantile", values="value")
    assert got.loc["A"].tolist() == pytest.approx(list(range(100, 109)))        # M2f-r4 alone
    assert got.loc["B"].tolist() == pytest.approx(list(range(200, 209)))
    assert np.all(np.diff(got.loc["C"].to_numpy()) >= 0)                        # sorted after averaging
    assert set(excl["series"]) == {"A", "B"}
    assert bool(excl.set_index("series").loc["A", "failed_all_zero"])


def test_coherence_gap_is_zero_for_additive_medians_and_measures_a_mismatch():
    icb = frame({"I1": [5] * 9, "I2": [7] * 9}, level="icb")
    region = frame({"R": [12] * 9}, level="region")
    eng = frame({"ENGLAND": [13.2] * 9}, level="england")
    g = coherence_gaps(pd.concat([icb, region, eng]), {"I1": "R", "I2": "R"}).set_index("level")
    assert g.loc["region", "gap"] == pytest.approx(0.0)
    assert g.loc["england", "gap"] == pytest.approx(abs(13.2 - 12) / 13.2)
