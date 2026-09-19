"""Guard G1: failed base forecasts (amendment "Guard G1 registered", 2026-09-13; scope D4 = (a)).

A base forecast, keyed by origin, target, series and horizon, is **failed** if its nine
quantiles are all exactly zero while the series' last observed month is positive. The last
observed month is the last non-missing month of that series in the as-of training data at the
origin, at the forecast's own level; region and England series are sums of the mapped ICBs, as
in the Stage F design. Failed forecasts are kept out of every calibration pool, the MinT error
covariance and the reconciliation inputs, and are issued as produced (``calibrate.online``,
``evaluate.stage_f``). They are scored as issued and count as not covered (``mark``).
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

from nhs_ae.evaluate.asof import TARGETS, load_asof

KEY = ["origin", "target", "series", "horizon"]
EXCLUDE = ("UNMAPPED", "LEGACY")


def _panels(d, target: str, levels, regions: pd.Series | None) -> dict[str, pd.DataFrame]:
    out = {lv: d.panel(target, lv) for lv in levels if lv in ("provider", "icb")}
    if {"region", "england"} & set(levels):
        icb = d.panel(target, "icb")
        icb = icb[[c for c in icb.columns if c not in EXCLUDE]]
        if "region" in levels:
            out["region"] = icb.T.groupby(regions.reindex(icb.columns).fillna("?")).sum(min_count=1).T
        if "england" in levels:
            out["england"] = icb.sum(axis=1, min_count=1).rename("ENGLAND").to_frame()
    return out


def last_observed(vintages: pd.DataFrame, origins: Iterable, levels=("provider",),
                  regions: pd.Series | None = None, region_map: pd.Series | None = None,
                  targets=tuple(TARGETS)) -> pd.DataFrame:
    """``origin, level, target, series, last_value``: each series' value in its last
    non-missing month of the as-of data at each origin. ``regions`` (ICB -> region) is needed
    for the region level."""
    rows = []
    for o in origins:
        d = load_asof(o, "asof", vintages, region_map)
        for t in targets:
            for lv, p in _panels(d, t, levels, regions).items():
                last = p.ffill().iloc[-1] if len(p) else pd.Series(dtype=float)
                rows.append(pd.DataFrame({"origin": pd.Timestamp(o), "level": lv, "target": t,
                                          "series": last.index.astype(str), "last_value": last.to_numpy(float)}))
    return pd.concat(rows, ignore_index=True)


def all_zero(fc: pd.DataFrame, last: pd.DataFrame) -> pd.DataFrame:
    """Forecasts in ``fc`` (one model) whose quantiles are all exactly zero, with the series'
    ``last_value`` (NaN if the series has no as-of history at that origin and level)."""
    w = fc.set_index([*KEY, "level", "quantile"])["value"].unstack("quantile")   # raises on duplicates
    zero = (w.fillna(-1.0).to_numpy() == 0.0).all(axis=1)       # every quantile present and exactly zero
    z = w.index[zero].to_frame(index=False)
    return z.merge(last, on=["origin", "level", "target", "series"], how="left")


def failed_forecasts(fc: pd.DataFrame, last: pd.DataFrame) -> pd.DataFrame:
    """The failed forecasts in ``fc`` (one model; ``KEY`` and ``level`` columns)."""
    z = all_zero(fc, last)
    return z.loc[z["last_value"] > 0, [*KEY, "level"]].reset_index(drop=True)


def mask(frame: pd.DataFrame, failed: pd.DataFrame | None, on: list[str]) -> np.ndarray:
    """Boolean array over ``frame``'s rows: True where the row's ``on`` keys are a failed forecast."""
    if failed is None or failed.empty:
        return np.zeros(len(frame), dtype=bool)
    keys = failed[on].drop_duplicates().assign(_failed=True)
    return frame[on].merge(keys, on=on, how="left")["_failed"].fillna(False).to_numpy(bool)


def mark(scored: pd.DataFrame, failed: pd.DataFrame | None, on: list[str]) -> pd.DataFrame:
    """Scored rows with a ``failed`` column; failed forecasts keep their WIS and count as not
    covered at every interval."""
    f = mask(scored, failed, on)
    out = scored.assign(failed=f)
    for c in [c for c in out.columns if str(c).startswith("cov")]:
        out[c] = out[c] & ~f
    return out
