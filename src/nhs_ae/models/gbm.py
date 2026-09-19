"""M1: global LightGBM quantile regression, direct multi-horizon, conformalised.

One model per quantile level, shared across every series in the panel and every
horizon (horizon is a feature). Rows are (series, origin month t, horizon h) with the
target

    z = log1p(y[t+h]) − log1p(level[t]),   level[t] = mean of the last 12 observed months,

so that trusts of very different size share one model and the quantile predictions are
relative. Features at row (s, t, h) use only values published at or before ``t``: lags
1–12 in the same log-relative units, the same month last year and two years, 3- and
12-month means, trailing 12-month growth, months of history, the target month's
calendar month, the horizon, deterministic regime flags (COVID period from 2020-03 to
2021-06; booked-appointment era from 2020-08) and the series identifier as a
categorical. Nothing is imputed: LightGBM handles missing values natively.

Conformal calibration (Romano, Patterson & Candès 2019, conformalised quantile
regression). The quantile models are trained on rows whose target month is at least
``calibration_months`` (12) before the end of the panel; the held-out last year gives
out-of-sample conformity scores per horizon and per central interval,
``max(q_lo − z, z − q_hi)``, and each interval is widened (or narrowed) by the
``(1 − α)(1 + 1/n)`` empirical quantile of those scores, pooled across series. The
median is left as predicted. Quantiles are then sorted to remove crossing and mapped
back with ``expm1``. The training loss of one year's targets is the price of a valid
calibration set; the last year still supplies features.

Hyperparameters are fixed defaults (below). The pre-registration allows tuning on
origins before 2019-09 only; that has not been done and is recorded as such.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from nhs_ae.models.base import HORIZONS, QUANTILES, quantile_frame, target_periods

log = logging.getLogger(__name__)

PARAMS = {
    "objective": "quantile", "learning_rate": 0.05, "num_leaves": 31, "min_data_in_leaf": 50,
    "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1, "lambda_l2": 1.0,
    "verbose": -1, "num_threads": 2, "seed": 0,
}
NUM_ROUNDS = 300
LAGS = tuple(range(1, 13))
COVID = (pd.Timestamp("2020-03-01"), pd.Timestamp("2021-06-01"))
BOOKED_FROM = pd.Timestamp("2020-08-01")


def build_rows(panel: pd.DataFrame, horizons: tuple[int, ...], with_target: bool = True,
               level_window: int = 12) -> pd.DataFrame:
    """Feature rows for every (series, origin month, horizon).

    With ``with_target`` the origin months are every month with a target inside the
    panel; without it, only the last month (the forecast rows). ``level_window`` is
    the number of trailing months whose mean defines the series level that the target
    and the lag features are expressed relative to.
    """
    ly = np.log1p(panel.astype(float))
    level = np.log1p(panel.rolling(level_window, min_periods=max(1, level_window // 2)).mean())
    rel = ly - level
    idx = panel.index
    origins = range(len(idx)) if with_target else [len(idx) - 1]
    frames = []
    for h in horizons:
        for t in origins:
            if with_target and t + h >= len(idx):
                continue
            row = pd.DataFrame(index=panel.columns)
            row["series"], row["t"], row["h"] = panel.columns, idx[t], h
            row["level"] = level.iloc[t].to_numpy()
            for lag in LAGS:  # lag1 is the origin month itself, the newest published value
                row[f"lag{lag}"] = rel.iloc[t - lag + 1].to_numpy() if t - lag + 1 >= 0 else np.nan
            tgt = t + h
            row["same_month_ly"] = rel.iloc[tgt - 12].to_numpy() if tgt - 12 >= 0 and tgt - 12 <= t else np.nan
            row["same_month_2y"] = rel.iloc[tgt - 24].to_numpy() if tgt - 24 >= 0 else np.nan
            row["mean3"] = rel.iloc[max(0, t - 2): t + 1].mean().to_numpy()
            row["mean12"] = rel.iloc[max(0, t - 11): t + 1].mean().to_numpy()
            recent = panel.iloc[max(0, t - 11): t + 1].sum(min_count=6)
            prior = panel.iloc[max(0, t - 23): t - 11].sum(min_count=6)
            row["growth12"] = np.log((recent / prior).where(prior > 0)).to_numpy()
            row["history"] = panel.iloc[: t + 1].notna().sum().to_numpy()
            target_month = idx[t] + pd.DateOffset(months=h)
            row["month"] = target_month.month
            row["covid"] = int(COVID[0] <= target_month <= COVID[1])
            row["booked_era"] = int(target_month >= BOOKED_FROM)
            if with_target:
                row["z"] = rel.iloc[tgt].to_numpy()
            frames.append(row.reset_index(drop=True))
    rows = pd.concat(frames, ignore_index=True)
    rows["series"] = rows["series"].astype("category")
    return rows


FEATURES = [f"lag{lag}" for lag in LAGS] + ["same_month_ly", "same_month_2y", "mean3", "mean12",
                                            "growth12", "history", "month", "h", "covid",
                                            "booked_era", "series"]


class LightGBMQuantile:
    name = "m1_lightgbm"

    def __init__(self, params: dict | None = None, num_rounds: int = NUM_ROUNDS,
                 calibration_months: int = 12, min_train_rows: int = 200, tuned: bool = False,
                 per_horizon: bool = False, level_window: int = 12, seed: int | None = None,
                 conformal: bool = True):
        self.per_horizon, self.level_window, self.conformal = per_horizon, level_window, conformal
        if tuned:  # parameters chosen by models/tune.py on pre-2019-09 origins
            import json
            from pathlib import Path
            cfg = json.loads(Path(__file__).with_name("m1_tuned.json").read_text())
            params = {**{k: cfg[k] for k in ("learning_rate", "num_leaves", "min_data_in_leaf",
                                             "lambda_l2", "feature_fraction")}, **(params or {})}
            num_rounds, calibration_months = cfg["num_rounds"], cfg["calibration_months"]
            self.name = "m1_lightgbm_tuned"
        if per_horizon and level_window != 12:  # amendment of 2026-09-09: v2 variant
            self.name = "m1_lightgbm_v2"
        elif per_horizon:  # v3: per-horizon models only, 12-month level kept
            self.name = "m1_lightgbm_v3"
        self.params = {**PARAMS, **(params or {})}
        if seed is not None:  # LightGBM's `seed` sets the bagging, feature and data seeds
            self.params["seed"] = seed
        if not conformal:  # raw quantiles, trained on every row; calibrated downstream
            self.name += "_raw"
            calibration_months = 0
        self.num_rounds = num_rounds
        self.calibration_months = calibration_months
        self.min_train_rows = min_train_rows

    def fit_predict(self, panel: pd.DataFrame, horizons=HORIZONS, quantiles=QUANTILES) -> pd.DataFrame:
        import lightgbm as lgb
        periods = target_periods(panel, horizons)
        rows = build_rows(panel, horizons, with_target=True,
                          level_window=self.level_window).dropna(subset=["z", "level"])
        cut = np.datetime64(panel.index[-1] - pd.DateOffset(months=self.calibration_months), "M")
        target_month = (rows["t"].to_numpy().astype("datetime64[M]")
                        + rows["h"].to_numpy().astype("timedelta64[M]"))
        train, calib = rows[target_month <= cut].copy(), rows[target_month > cut].copy()
        test = build_rows(panel, horizons, with_target=False, level_window=self.level_window)
        if len(train) < self.min_train_rows:
            log.warning("LightGBM: only %d training rows; returning NaN", len(train))
            return quantile_frame({(s, h, periods[h]): dict.fromkeys(quantiles, np.nan)
                                   for s in panel.columns for h in horizons})
        cats = train["series"].cat.categories
        for f in (calib, test):
            f["series"] = pd.Categorical(f["series"].astype(str), categories=cats)
        if self.per_horizon:  # one model per horizon: short horizons get their own trees
            pred_c = np.full((len(calib), len(quantiles)), np.nan) if len(calib) else None
            pred_t = np.full((len(test), len(quantiles)), np.nan)
            for h in horizons:
                tr = train[train["h"] == h]
                if len(tr) < self.min_train_rows // len(horizons):
                    continue
                models = {q: self._fit(lgb, tr, q) for q in quantiles}
                mt = (test["h"] == h).to_numpy()
                pred_t[mt] = np.column_stack([models[q].predict(test[mt][FEATURES]) for q in quantiles])
                if pred_c is not None:
                    mc = (calib["h"] == h).to_numpy()
                    if mc.any():
                        pred_c[mc] = np.column_stack([models[q].predict(calib[mc][FEATURES]) for q in quantiles])
        else:
            models = {q: self._fit(lgb, train, q) for q in quantiles}
            pred_c = (np.column_stack([models[q].predict(calib[FEATURES]) for q in quantiles])
                      if len(calib) else None)
            pred_t = np.column_stack([models[q].predict(test[FEATURES]) for q in quantiles])
        # conformal widening per horizon and central interval, pooled across series
        adj = np.zeros((len(test), len(quantiles)))
        if pred_c is not None:
            zc = calib["z"].to_numpy()
            for i, (lo, hi) in enumerate(_pairs(quantiles)):
                alpha = 2 * quantiles[lo]
                for h in horizons:
                    mc, mt = (calib["h"] == h).to_numpy(), (test["h"] == h).to_numpy()
                    n = mc.sum()
                    if n < 10:
                        continue
                    scores = np.maximum(pred_c[mc, lo] - zc[mc], zc[mc] - pred_c[mc, hi])
                    scores = scores[np.isfinite(scores)]
                    n = len(scores)
                    if n < 10:
                        continue
                    k = min(1.0, (1 - alpha) * (1 + 1 / n))
                    e = np.quantile(scores, k)
                    adj[mt, lo] -= e
                    adj[mt, hi] += e
        pred = np.sort(pred_t + adj, axis=1)
        out = np.expm1(pred + test["level"].to_numpy()[:, None])
        out = np.maximum(out, 0.0)
        values = {}
        for r, (s, h) in enumerate(zip(test["series"].astype(str), test["h"])):
            values[(s, int(h), periods[int(h)])] = {q: float(out[r, j]) for j, q in enumerate(quantiles)}
        for s in panel.columns:
            for h in horizons:
                values.setdefault((s, h, periods[h]), dict.fromkeys(quantiles, np.nan))
        return quantile_frame(values)

    def _fit(self, lgb, train: pd.DataFrame, q: float):
        ds = lgb.Dataset(train[FEATURES], train["z"], categorical_feature=["series"],
                         free_raw_data=False)
        return lgb.train({**self.params, "alpha": q}, ds, num_boost_round=self.num_rounds)


def _pairs(quantiles) -> list[tuple[int, int]]:
    """Index pairs (lo, hi) of symmetric central intervals in a sorted quantile tuple."""
    qs = list(quantiles)
    return [(i, qs.index(round(1 - q, 6))) for i, q in enumerate(qs) if q < 0.5 and round(1 - q, 6) in qs]
