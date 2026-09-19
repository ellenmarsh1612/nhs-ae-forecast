"""B1 ETS quantiles are reproducible: the simulation seed must reach statsmodels."""

from __future__ import annotations

import numpy as np
import pandas as pd

from nhs_ae.models.statistical import ETS


def test_ets_forecast_is_identical_across_runs():
    idx = pd.date_range("2019-01-01", periods=60, freq="MS")
    rng = np.random.default_rng(3)
    panel = pd.DataFrame({"A": 1000 + 80 * np.sin(np.arange(60) * np.pi / 6) + rng.normal(0, 25, 60),
                          "B": 400 + 30 * np.cos(np.arange(60) * np.pi / 6) + rng.normal(0, 10, 60)}, index=idx)
    a = ETS(repetitions=200).fit_predict(panel, (1, 2, 3), (0.05, 0.5, 0.95))
    np.random.seed(12345)                                   # global state must not matter
    b = ETS(repetitions=200).fit_predict(panel, (1, 2, 3), (0.05, 0.5, 0.95))
    pd.testing.assert_frame_equal(a, b)
