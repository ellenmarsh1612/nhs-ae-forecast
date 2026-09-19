"""The contract every forecaster implements, so the harness can treat them identically.

Input: a *panel*, a wide DataFrame with a monthly DatetimeIndex (month starts) ending at
the last published period, one column per series (provider code, region name or
"ENGLAND"), NaN where a series was not published for that month.

Output: a long DataFrame with columns ``series, horizon, period, quantile, value`` where
``period = last index month + horizon`` and ``quantile`` runs over the requested levels.
A series the model cannot forecast is returned with NaN values, never omitted, so that
the harness can count what was not scoreable.
"""

from __future__ import annotations

from typing import Protocol

import pandas as pd

QUANTILES: tuple[float, ...] = (0.025, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.975)
HORIZONS: tuple[int, ...] = tuple(range(1, 7))
FORECAST_COLUMNS = ("series", "horizon", "period", "quantile", "value")


class Forecaster(Protocol):
    name: str

    def fit_predict(self, panel: pd.DataFrame, horizons: tuple[int, ...] = HORIZONS,
                    quantiles: tuple[float, ...] = QUANTILES) -> pd.DataFrame: ...


def target_periods(panel: pd.DataFrame, horizons: tuple[int, ...]) -> dict[int, pd.Timestamp]:
    last = panel.index[-1]
    return {h: last + pd.DateOffset(months=h) for h in horizons}


def quantile_frame(values: dict[tuple[str, int, pd.Timestamp], dict[float, float]]) -> pd.DataFrame:
    """Build the output frame from {(series, horizon, period): {quantile: value}}."""
    rows = [(s, h, p, q, v) for (s, h, p), qv in values.items() for q, v in qv.items()]
    return pd.DataFrame(rows, columns=list(FORECAST_COLUMNS))
