"""Rolling-origin backtest (pre-registration §4).

For every origin month and every mode (as-of, final) the harness loads the training
data with ``load_asof``, builds one panel per (target, level), asks each model for
quantile forecasts at horizons 1–6, and scores them against the latest revised
outturn. Both modes go through exactly this code path; nothing else differs.

Forecast table contract (every model, every stage downstream reads only this)::

    origin      month start of the origin
    mode        'asof' | 'final'
    model       model name
    level       'provider' | 'region' | 'england'
    target      'att_all' | 'att_type1' | 'adm_via_ae'
    series      provider code, region name, or 'ENGLAND'
    horizon     1..6
    period      target month
    quantile    0.025 .. 0.975
    value       forecast
    scale       MASE denominator for this series at this origin (training data only)

Scores are one row per (origin, mode, model, level, target, series, horizon, period)
with the quantile values as columns, ``y`` (outturn), and the per-row metrics from
``metrics.score_rows``. Four kinds of row are dropped and counted rather than scored:
no outturn (the provider is absent from the final data for that month), no forecast
(the model returned NaN), a *degenerate* series whose training values never
changed (``scale == 0``, typically a Type 3 provider scored on a Type 1 target), for
which any model forecasting a constant is trivially perfect, and *embargoed* rows whose
target month lies in the sealed confirmatory window (``evaluate.splits``). Series with
too little history for a scale (cold starts) are kept; their MASE is NaN, their WIS is
valid. The default origins are the DEV split; scoring a CONF origin raises unless the
confirmatory run supplies the unseal token.
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from nhs_ae.evaluate.asof import LEVELS, TARGETS, AsOfData, load_asof, load_truth
from nhs_ae.evaluate.metrics import mase_scale, score_rows
from nhs_ae.evaluate.splits import DEV, assert_not_sealed, sealed_mask
from nhs_ae.features.hierarchy import current_region_map
from nhs_ae.ingest.recover import month_range
from nhs_ae.models.base import HORIZONS, QUANTILES, Forecaster

log = logging.getLogger(__name__)

KEYS = ["origin", "mode", "model", "level", "target", "series", "horizon", "period"]
WINTER_MONTHS = (12, 1, 2, 3)


@dataclass
class BacktestConfig:
    origins: list[date] = field(default_factory=lambda: month_range(*DEV))
    modes: tuple[str, ...] = ("asof", "final")
    targets: tuple[str, ...] = tuple(TARGETS)
    levels: tuple[str, ...] = LEVELS
    horizons: tuple[int, ...] = HORIZONS
    quantiles: tuple[float, ...] = QUANTILES
    min_train_months: int = 24


def forecast_origin(data: AsOfData, models: list[Forecaster], cfg: BacktestConfig) -> pd.DataFrame:
    frames = []
    for target in cfg.targets:
        for level in cfg.levels:
            panel = data.panel(target, level)
            # forecast only series seen in the last 12 months; defunct codes stay in the
            # panel for history but would only produce NaN rows
            active = panel.iloc[-12:].notna().any()
            panel = panel.loc[:, active[active].index]
            if len(panel) < cfg.min_train_months:
                log.warning("%s %s %s/%s: only %d months of training data, skipped",
                            data.origin.date(), data.mode, target, level, len(panel))
                continue
            scale = mase_scale(panel)
            for model in models:
                fc = model.fit_predict(panel, cfg.horizons, cfg.quantiles)
                fc["scale"] = fc["series"].map(scale)
                fc["origin"], fc["mode"], fc["model"] = data.origin, data.mode, model.name
                fc["level"], fc["target"] = level, target
                frames.append(fc)
    if not frames:
        return pd.DataFrame(columns=[*KEYS, "quantile", "value", "scale"])
    return pd.concat(frames, ignore_index=True)[[*KEYS, "quantile", "value", "scale"]]


def truth_long(truth: AsOfData, levels: tuple[str, ...], targets: tuple[str, ...]) -> pd.DataFrame:
    rows = []
    for target in targets:
        for level in levels:
            p = truth.panel(target, level)
            long = p.stack(future_stack=True).rename("y").reset_index()
            long.columns = ["period", "series", "y"]
            long["target"], long["level"] = target, level
            rows.append(long)
    return pd.concat(rows, ignore_index=True)


def score_forecasts(forecasts: pd.DataFrame, truth: pd.DataFrame,
                    unseal_token: str | None = None) -> tuple[pd.DataFrame, dict]:
    """Wide scored frame and counts of the rows that could not be scored.

    Without ``unseal_token``: forecasts from a sealed (CONF) origin raise; forecasts from
    an unsealed origin whose target period is sealed (a late-2023 DEV origin reaching
    into 2024) are dropped and counted as ``embargoed`` (see ``evaluate.splits``).
    """
    embargoed = 0
    if unseal_token is None:
        keys = forecasts[["origin"]].drop_duplicates()
        assert_not_sealed(keys["origin"])   # raises on any CONF origin
        sealed = sealed_mask(forecasts)
        embargoed = int(forecasts.loc[sealed, KEYS].drop_duplicates().shape[0])
        forecasts = forecasts[~sealed]
    # unstack, not pivot_table(dropna=False): the latter builds the cartesian product of
    # every key level and ran out of memory on the full grid.
    wide = forecasts.set_index([*KEYS, "scale", "quantile"])["value"].unstack("quantile").reset_index()
    wide.columns = [c if not isinstance(c, float) else float(c) for c in wide.columns]
    scored = wide.merge(truth, on=["target", "level", "series", "period"], how="left")
    qcols = [c for c in scored.columns if isinstance(c, float)]
    no_forecast = scored[qcols].isna().any(axis=1)
    no_outturn = scored["y"].isna() & ~no_forecast
    degenerate = ~(no_forecast | no_outturn) & ~(scored["scale"] > 0) & scored["scale"].notna()
    dropped = {"no_forecast": int(no_forecast.sum()), "no_outturn": int(no_outturn.sum()),
               "degenerate_series": int(degenerate.sum()), "embargoed": embargoed}
    scored = scored[~(no_forecast | no_outturn | degenerate)]
    scored = score_rows(scored, unseal_token)
    scored["winter"] = scored["period"].dt.month.isin(WINTER_MONTHS)
    return scored, dropped


# --- parallel generation ------------------------------------------------------------------
# One task per (origin, mode). Workers are started with "spawn" (the macOS default and the
# only start method safe with BLAS threads), so each worker loads the vintage table once in
# its initialiser rather than receiving a 1M-row frame per task.
_WORKER: dict = {}


def _init_worker(vintages_path, models, cfg):
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[var] = "1"
    from nhs_ae.evaluate.asof import load_vintages
    v = load_vintages(vintages_path)
    _WORKER.update(vintages=v, region_map=current_region_map(v), models=models, cfg=cfg)


def _run_task(task):
    origin, mode = task
    w = _WORKER
    data = load_asof(origin, mode, w["vintages"], w["region_map"])
    return forecast_origin(data, w["models"], w["cfg"])


def generate_forecasts(models: list[Forecaster], vintages: pd.DataFrame,
                       cfg: BacktestConfig, region_map: pd.Series | None = None,
                       jobs: int = 1, vintages_path=None) -> pd.DataFrame:
    """Forecasts for every (origin, mode). ``jobs > 1`` runs passes in parallel processes;
    that needs ``vintages_path`` so workers can load the table themselves."""
    tasks = [(o, m) for o in cfg.origins for m in cfg.modes]
    frames = []
    if jobs > 1 and vintages_path is not None:
        with ProcessPoolExecutor(max_workers=jobs, initializer=_init_worker,
                                 initargs=(vintages_path, models, cfg)) as pool:
            for (origin, mode), fc in zip(tasks, pool.map(_run_task, tasks)):
                log.info("origin %s %-5s: %d forecast rows", origin.strftime("%Y-%m"), mode, len(fc))
                frames.append(fc)
        return pd.concat(frames, ignore_index=True)
    region_map = current_region_map(vintages) if region_map is None else region_map
    for origin, mode in tasks:
        data = load_asof(origin, mode, vintages, region_map)
        fc = forecast_origin(data, models, cfg)
        log.info("origin %s %-5s: %d forecast rows", origin.strftime("%Y-%m"), mode, len(fc))
        frames.append(fc)
    return pd.concat(frames, ignore_index=True)


def score_against_truth(forecasts: pd.DataFrame, vintages: pd.DataFrame, cfg: BacktestConfig,
                        region_map: pd.Series | None = None,
                        unseal_token: str | None = None) -> tuple[pd.DataFrame, dict]:
    region_map = current_region_map(vintages) if region_map is None else region_map
    truth = truth_long(load_truth(vintages, region_map), cfg.levels, cfg.targets)
    return score_forecasts(forecasts, truth, unseal_token)


def run_backtest(models: list[Forecaster], vintages: pd.DataFrame,
                 cfg: BacktestConfig | None = None) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Returns (forecasts, scores, info). The CLI calls the two halves separately so the
    forecasts are on disk before scoring starts."""
    cfg = cfg or BacktestConfig()
    region_map = current_region_map(vintages)
    forecasts = generate_forecasts(models, vintages, cfg, region_map)
    scores, dropped = score_against_truth(forecasts, vintages, cfg, region_map)
    info = {"origins": len(cfg.origins), "forecast_rows": len(forecasts),
            "scored": len(scores), **dropped}
    return forecasts, scores, info
