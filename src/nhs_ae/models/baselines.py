"""Statistical baselines. B0 here; ETS (B1) and STL+ARIMA (B2) to follow.

B0, seasonal naive with trailing growth
---------------------------------------
Point forecast for month ``p`` at horizon ``h`` from last observed month ``L``:

    y_hat[p] = y[p - 12] * g,   g = sum(y[L-11..L]) / sum(y[L-23..L-12])

with the two sums taken over months where both terms are present (missing months drop
out of both), and g = 1 when fewer than ``min_growth_months`` such pairs exist. It is
the MASE reference model in the pre-registration.

Uncertainty comes from the model's own in-sample errors: for every historical month t
we recompute the same rule as it would have stood ``h`` months earlier, take the log
ratio of actual to forecast, and use the empirical quantiles of those log ratios,
per series when there are at least ``min_residuals`` of them and pooled across all
series otherwise. Quantile forecasts are ``y_hat * exp(q_tau)``. Intervals are
therefore multiplicative, symmetric in log space only if the errors are, and grow
with horizon because the growth factor at t-h uses staler data. Only the last
``residual_window`` months of errors are used (36 by default): with 60 the 2020
collapse kept every 2024 interval absurdly wide. This interval construction is a
choice the pre-registration did not specify and is recorded there as an amendment.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from nhs_ae.models.base import HORIZONS, QUANTILES, quantile_frame, target_periods


def _growth(y: pd.DataFrame, end_pos: int, min_months: int) -> pd.Series:
    """Ratio of the 12 months ending at ``end_pos`` to the 12 before, paired on presence."""
    recent = y.iloc[end_pos - 11: end_pos + 1]
    prior = y.iloc[end_pos - 23: end_pos - 11]
    if len(recent) < 12 or len(prior) < 12:
        return pd.Series(1.0, index=y.columns)
    both = recent.notna().to_numpy() & prior.notna().to_numpy()
    num = np.where(both, recent.to_numpy(), 0.0).sum(axis=0)
    den = np.where(both, prior.to_numpy(), 0.0).sum(axis=0)
    n = both.sum(axis=0)
    g = np.where((n >= min_months) & (den > 0), num / np.where(den > 0, den, 1.0), 1.0)
    return pd.Series(g, index=y.columns)


class SeasonalNaive:
    name = "b0_seasonal_naive"

    def __init__(self, min_growth_months: int = 6, min_residuals: int = 12,
                 residual_window: int = 36):
        self.min_growth_months = min_growth_months
        self.min_residuals = min_residuals
        self.residual_window = residual_window

    def point(self, y: pd.DataFrame, end_pos: int, h: int) -> pd.Series:
        """Forecast for the month ``h`` after position ``end_pos`` using data to ``end_pos``."""
        base_pos = end_pos + h - 12
        if base_pos < 0:
            return pd.Series(np.nan, index=y.columns)
        return y.iloc[base_pos] * _growth(y, end_pos, self.min_growth_months)

    def _log_residuals(self, y: pd.DataFrame, h: int) -> pd.DataFrame:
        """log(actual / forecast) for every month the rule could have been applied."""
        T = len(y)
        out = pd.DataFrame(np.nan, index=y.index, columns=y.columns)
        for t in range(max(12, T - self.residual_window), T):
            end_pos = t - h
            if end_pos < 0:
                continue
            f = self.point(y, end_pos, h)
            actual = y.iloc[t]
            ok = (f > 0) & (actual > 0)
            with np.errstate(divide="ignore", invalid="ignore"):
                out.iloc[t] = np.where(ok, np.log(actual / f.where(f > 0)), np.nan)
        return out

    def fit_predict(self, panel: pd.DataFrame, horizons: tuple[int, ...] = HORIZONS,
                    quantiles: tuple[float, ...] = QUANTILES) -> pd.DataFrame:
        y = panel.astype(float)
        T = len(y)
        periods = target_periods(y, horizons)
        values: dict = {}
        for h in horizons:
            point = self.point(y, T - 1, h)
            resid = self._log_residuals(y, h)
            pooled = resid.to_numpy().ravel()
            pooled = pooled[np.isfinite(pooled)]
            for s in y.columns:
                r = resid[s].dropna().to_numpy()
                src = r if len(r) >= self.min_residuals else pooled
                if np.isnan(point[s]) or len(src) == 0:
                    values[(s, h, periods[h])] = dict.fromkeys(quantiles, np.nan)
                    continue
                qs = np.quantile(src, quantiles)
                values[(s, h, periods[h])] = {q: float(point[s] * np.exp(v)) for q, v in zip(quantiles, qs)}
        return quantile_frame(values)

