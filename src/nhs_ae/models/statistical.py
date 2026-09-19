"""B1 (ETS) and B2 (STL + ARIMA), fitted per series with statsmodels.

Both take the harness panel, fit each column independently, and return the common
quantile table. Series handling, shared by both:

* leading NaN are trimmed; a series needs ``min_obs`` observations and a non-missing
  last month, else its forecast is NaN (unscoreable, counted by the harness);
* internal gaps (months a provider did not submit) are linearly interpolated *for
  fitting only*; the archive keeps them as NaN;
* quantiles are floored at zero.

B1 – ETS
    Candidates: additive error / additive seasonality with no trend or a damped
    additive trend; and, when the series is strictly positive, the multiplicative
    error / multiplicative seasonality versions. The winner has the lowest AICc.
    Quantiles come from ``simulate`` (1,000 sample paths from the fitted state).

B2 – STL + ARIMA
    STL (robust, seasonal window ``seasonal_window``) on the series; ARIMA on the
    seasonally adjusted series with the order chosen by AICc from a small grid
    ((0,1,1), (1,1,0), (1,1,1), (0,1,0)); the last seasonal cycle is projected forward.
    The default seasonal window is 25 cycles, effectively periodic for series of up to
    eleven years, rather than statsmodels' 7: with 7 (or 13) the 2020–21 distortions
    leak into the seasonal component and a September forecast for one large trust was
    20% high; with 25 it was within 2% of the outturn. Quantiles are Gaussian from the
    ARIMA forecast standard error, so they are symmetric and ignore seasonal-component
    uncertainty; that is a known weakness of the method, not a bug.
"""

from __future__ import annotations

import logging
import warnings

import numpy as np
import pandas as pd
from scipy import stats

from nhs_ae.models.base import HORIZONS, QUANTILES, quantile_frame, target_periods

log = logging.getLogger(__name__)

ETS_CANDIDATES = (  # (error, trend, damped, seasonal)
    ("add", None, False, "add"),
    ("add", "add", True, "add"),
    ("mul", None, False, "mul"),
    ("mul", "add", True, "mul"),
)
ARIMA_ORDERS = ((0, 1, 1), (1, 1, 0), (1, 1, 1), (0, 1, 0))


def _prepare(series: pd.Series, min_obs: int) -> pd.Series | None:
    s = series.astype(float)
    first = s.first_valid_index()
    if first is None or pd.isna(s.iloc[-1]):
        return None
    s = s.loc[first:]
    if s.notna().sum() < min_obs:
        return None
    s = s.interpolate(limit_direction="both")
    s.index = pd.DatetimeIndex(s.index, freq="MS")
    return s


def _seed_kwarg(simulate, seed: int) -> dict:
    """The seed for ``ETSResults.simulate``, passed explicitly. statsmodels 0.15 renamed its
    ``random_state`` argument ``rng`` and, left unset, draws fresh entropy: seeding NumPy's
    global generator (what this module did until 2026-09-12) had no effect, so every B1
    forecast before then is unseeded Monte Carlo. ``RandomState(seed)`` reproduces the
    old global-seed stream on versions where that worked."""
    import inspect
    params = inspect.signature(simulate).parameters
    name = "rng" if "rng" in params else "random_state"
    return {name: np.random.RandomState(seed)}


def _nan_forecast(series: str, periods: dict, quantiles) -> dict:
    return {(series, h, p): dict.fromkeys(quantiles, np.nan) for h, p in periods.items()}


class ETS:
    name = "b1_ets"

    def __init__(self, min_obs: int = 30, repetitions: int = 1000, seed: int = 0):
        self.min_obs, self.repetitions, self.seed = min_obs, repetitions, seed

    def _fit_one(self, y: pd.Series):
        from statsmodels.tsa.exponential_smoothing.ets import ETSModel
        best = None
        for error, trend, damped, seasonal in ETS_CANDIDATES:
            if error == "mul" and (y <= 0).any():
                continue
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    res = ETSModel(y, error=error, trend=trend, damped_trend=damped,
                                   seasonal=seasonal, seasonal_periods=12).fit(disp=False)
            except Exception as e:  # noqa: BLE001 – a candidate failing is not fatal
                log.debug("ETS %s failed on %s: %s", (error, trend, seasonal), y.name, e)
                continue
            if np.isfinite(res.aicc) and (best is None or res.aicc < best.aicc):
                best = res
        return best

    def fit_predict(self, panel: pd.DataFrame, horizons=HORIZONS, quantiles=QUANTILES) -> pd.DataFrame:
        periods = target_periods(panel, horizons)
        H = max(horizons)
        values: dict = {}
        for name in panel.columns:
            y = _prepare(panel[name], self.min_obs)
            res = self._fit_one(y) if y is not None else None
            if res is None:
                values.update(_nan_forecast(name, periods, quantiles))
                continue
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                sim = res.simulate(nsimulations=H, repetitions=self.repetitions, anchor="end",
                                   **_seed_kwarg(res.simulate, self.seed))
            paths = np.asarray(sim)  # H x repetitions
            for h in horizons:
                qs = np.quantile(paths[h - 1], quantiles)
                values[(name, h, periods[h])] = {q: float(max(v, 0.0)) for q, v in zip(quantiles, qs)}
        return quantile_frame(values)


class STLArima:
    name = "b2_stl_arima"

    def __init__(self, min_obs: int = 30, seasonal_window: int = 25):
        self.min_obs, self.seasonal_window = min_obs, seasonal_window

    def _fit_one(self, y: pd.Series):
        from statsmodels.tsa.arima.model import ARIMA
        from statsmodels.tsa.forecasting.stl import STLForecast
        best = None
        for order in ARIMA_ORDERS:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    res = STLForecast(y, ARIMA, model_kwargs={"order": order, "trend": "n"},
                                      period=12, robust=True, seasonal=self.seasonal_window).fit()
            except Exception as e:  # noqa: BLE001
                log.debug("STL+ARIMA %s failed on %s: %s", order, y.name, e)
                continue
            aicc = res.model_result.aicc
            if np.isfinite(aicc) and (best is None or aicc < best.model_result.aicc):
                best = res
        return best

    def fit_predict(self, panel: pd.DataFrame, horizons=HORIZONS, quantiles=QUANTILES) -> pd.DataFrame:
        periods = target_periods(panel, horizons)
        H = max(horizons)
        z = stats.norm.ppf(quantiles)
        values: dict = {}
        for name in panel.columns:
            y = _prepare(panel[name], self.min_obs)
            res = self._fit_one(y) if y is not None else None
            if res is None:
                values.update(_nan_forecast(name, periods, quantiles))
                continue
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                pr = res.get_prediction(start=len(y), end=len(y) + H - 1).summary_frame()
            mean, se = pr["mean"].to_numpy(), pr["mean_se"].to_numpy()
            for h in horizons:
                values[(name, h, periods[h])] = {
                    q: float(max(mean[h - 1] + zq * se[h - 1], 0.0)) for q, zq in zip(quantiles, z)}
        return quantile_frame(values)
