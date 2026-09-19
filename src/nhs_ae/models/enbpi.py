"""EnbPI for the LightGBM model (Xu & Xie, "Conformal prediction interval for dynamic
time-series", 2021): Stage D, design in the pre-registration amendment of 2026-09-10.

Per horizon (the v3 architecture), 20 LightGBM *median* models are fitted on bootstrap
samples of the training rows. The bootstrap resamples non-overlapping 12-month blocks of
origin months, so rows that share lags stay together. Each training row gets an
out-of-bag prediction (the mean of the models whose sample left its block out), hence an
out-of-sample residual without holding any data back. The residuals whose target month
lies in the last 12 months of the panel, pooled across providers, are EnbPI's sliding
window: refitting at every origin moves the window forward, which is how the method
tracks distribution shift. Forecast quantile τ = ensemble mean + the τ-quantile of those
residuals, on the log-relative scale of ``gbm.build_rows``; quantiles are asymmetric
because the residual quantiles are.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from nhs_ae.models.base import HORIZONS, QUANTILES, quantile_frame, target_periods
from nhs_ae.models.gbm import FEATURES, PARAMS, build_rows

log = logging.getLogger(__name__)
TUNED_PATH = Path(__file__).with_name("m1_tuned.json")   # not imported from tune: cycle


class EnbPI:
    name = "m1_enbpi"

    def __init__(self, n_boot: int = 20, block: int = 12, window: int = 12, seed: int = 0,
                 min_train_rows: int = 200):
        cfg = json.loads(TUNED_PATH.read_text())
        self.params = {**PARAMS, **{k: cfg[k] for k in ("learning_rate", "num_leaves",
                                                        "min_data_in_leaf", "lambda_l2",
                                                        "feature_fraction")},
                       "alpha": 0.5, "seed": seed}
        self.num_rounds = cfg["num_rounds"]
        self.n_boot, self.block, self.window, self.seed = n_boot, block, window, seed
        self.min_train_rows = min_train_rows

    def fit_predict(self, panel: pd.DataFrame, horizons=HORIZONS, quantiles=QUANTILES) -> pd.DataFrame:
        import lightgbm as lgb
        periods = target_periods(panel, horizons)
        rows = build_rows(panel, horizons, with_target=True).dropna(subset=["z", "level"])
        test = build_rows(panel, horizons, with_target=False)
        empty = {(s, h, periods[h]): dict.fromkeys(quantiles, np.nan)
                 for s in panel.columns for h in horizons}
        if len(rows) < self.min_train_rows:
            log.warning("EnbPI: only %d training rows; returning NaN", len(rows))
            return quantile_frame(empty)
        cats = rows["series"].cat.categories
        test["series"] = pd.Categorical(test["series"].astype(str), categories=cats)
        months = np.sort(rows["t"].unique())
        block_of = pd.Series(np.arange(len(months)) // self.block, index=months)
        n_blocks = int(block_of.max()) + 1
        rng = np.random.default_rng(self.seed)
        draws = [set(rng.integers(0, n_blocks, size=n_blocks)) for _ in range(self.n_boot)]
        cutoff = panel.index[-1] - pd.DateOffset(months=self.window)
        values = dict(empty)
        for h in horizons:
            tr, te = rows[rows["h"] == h], test[test["h"] == h]
            if len(tr) < self.min_train_rows // len(horizons) or te.empty:
                continue
            blk = block_of.reindex(tr["t"]).to_numpy()
            oob_sum, oob_n = np.zeros(len(tr)), np.zeros(len(tr))
            centre = np.zeros(len(te))
            for drawn in draws:
                inbag = np.isin(blk, list(drawn))
                ds = lgb.Dataset(tr.loc[inbag, FEATURES], tr.loc[inbag, "z"],
                                 categorical_feature=["series"], free_raw_data=False)
                model = lgb.train({**self.params, "objective": "quantile"}, ds,
                                  num_boost_round=self.num_rounds)
                if (~inbag).any():
                    oob_sum[~inbag] += model.predict(tr.loc[~inbag, FEATURES])
                    oob_n[~inbag] += 1
                centre += model.predict(te[FEATURES]) / self.n_boot
            target_month = tr["t"] + pd.DateOffset(months=h)
            recent = (target_month > cutoff).to_numpy() & (oob_n > 0)
            resid = tr["z"].to_numpy()[recent] - oob_sum[recent] / oob_n[recent]
            if len(resid) < 10:
                continue
            offsets = np.quantile(resid, quantiles)
            z = np.sort(centre[:, None] + offsets[None, :], axis=1)
            out = np.maximum(np.expm1(z + te["level"].to_numpy()[:, None]), 0.0)
            for r, s in enumerate(te["series"].astype(str)):
                values[(s, h, periods[h])] = {q: float(out[r, j]) for j, q in enumerate(quantiles)}
        return quantile_frame(values)
