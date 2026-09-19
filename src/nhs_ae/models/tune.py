"""M1 hyperparameter search on pre-evaluation origins (pre-registration amendment of
2026-09-09).

The search space, the origin range and the selection criterion are fixed in the
amendment; this module only executes them. Each configuration is run through the
ordinary harness (as-of mode, provider level, all targets, horizons 1–6) on origins
before the evaluation window, scored, and summarised by mean WIS across targets. The
winner is written to ``m1_tuned.json`` next to the models, which ``LightGBMQuantile``
reads when constructed with ``tuned=True`` (registered as ``m1_tuned``).
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from nhs_ae.evaluate.harness import BacktestConfig, generate_forecasts, score_against_truth
from nhs_ae.ingest.recover import month_range
from nhs_ae.models.gbm import LightGBMQuantile

log = logging.getLogger(__name__)

SPACE = {
    "learning_rate": (0.03, 0.05, 0.1),
    "num_leaves": (15, 31, 63),
    "min_data_in_leaf": (20, 50, 100),
    "num_rounds": (200, 400, 800),
    "lambda_l2": (1.0, 10.0),
    "feature_fraction": (0.7, 0.9),
    "calibration_months": (12, 24),
}
TUNED_PATH = Path(__file__).with_name("m1_tuned.json")


def draw_configs(n: int = 16, seed: int = 0) -> list[dict]:
    """Deterministic random search draws (no duplicates)."""
    rng = np.random.default_rng(seed)
    seen, out = set(), []
    while len(out) < n:
        c = {k: v[rng.integers(len(v))] for k, v in SPACE.items()}
        key = tuple(sorted((k, float(v)) for k, v in c.items()))
        if key not in seen:
            seen.add(key)
            out.append({k: (int(v) if isinstance(v, (np.integer, int)) else float(v)) for k, v in c.items()})
    return out


def model_from_config(cfg: dict) -> LightGBMQuantile:
    params = {k: cfg[k] for k in ("learning_rate", "num_leaves", "min_data_in_leaf", "lambda_l2",
                                  "feature_fraction")}
    return LightGBMQuantile(params=params, num_rounds=cfg["num_rounds"],
                            calibration_months=cfg["calibration_months"])


def run_search(vintages: pd.DataFrame, vintages_path, origins: list[date], n_configs: int = 16,
               jobs: int = 1, seed: int = 0) -> pd.DataFrame:
    base = BacktestConfig(origins=origins, modes=("asof",), levels=("provider",))
    rows = []
    for i, cfg in enumerate(draw_configs(n_configs, seed)):
        model = model_from_config(cfg)
        model.name = f"m1_cfg{i:02d}"
        fc = generate_forecasts([model], vintages, base, jobs=jobs, vintages_path=vintages_path)
        scores, _dropped = score_against_truth(fc, vintages, base)
        by_target = scores.groupby("target").agg(wis=("wis", "mean"), mase=("mase", "mean"),
                                                 cov90=("cov90", "mean"))
        row = {"config": i, **cfg, "wis_mean": by_target["wis"].mean(),
               "mase_mean": by_target["mase"].mean(), "cov90_mean": by_target["cov90"].mean(),
               "scored_rows": len(scores), **{f"wis_{t}": v for t, v in by_target["wis"].items()}}
        log.info("config %02d: mean WIS %.2f, MASE %.3f, cov90 %.3f  %s", i, row["wis_mean"],
                 row["mase_mean"], row["cov90_mean"], cfg)
        rows.append(row)
    return pd.DataFrame(rows).sort_values("wis_mean").reset_index(drop=True)


def save_winner(table: pd.DataFrame, path: Path = TUNED_PATH) -> dict:
    best = table.iloc[0]
    cfg = {k: (int(best[k]) if k in ("num_leaves", "min_data_in_leaf", "num_rounds", "calibration_months")
               else float(best[k])) for k in SPACE}
    cfg["_selected_on"] = "mean WIS across targets, provider level, as-of, origins before 2019-09"
    cfg["_wis_mean"] = float(best["wis_mean"])
    path.write_text(json.dumps(cfg, indent=1))
    return cfg


def default_origins() -> list[date]:
    return month_range(date(2018, 4, 1), date(2019, 8, 1))


__all__ = [
    "SPACE",
    "TUNED_PATH",
    "default_origins",
    "draw_configs",
    "model_from_config",
    "replace",
    "run_search",
    "save_winner",
]
