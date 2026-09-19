"""Post-hoc calibration of a backtest's quantile forecasts, origin by origin (Stage D).

Methods (design fixed in the pre-registration amendment of 2026-09-10, Stage D):

* ``pooled``  split conformal on the model's own out-of-sample forecasts: the CQR score
  ``max(L_lo − Y, Y − L_hi)`` (log1p scale) of every provider's forecast from the 12 most
  recent *resolved* forecast origins at that horizon, one widening per horizon and
  central interval at the ``(1 − a)(1 + 1/n)`` empirical quantile.
* ``series``  the same with each provider's own scores over its 36 most recent resolved
  origins, used only when ``n ≥ ⌈1/a⌉`` and shrunk towards the pooled value:
  ``e = (n·ê + κ·e_pool) / (n + κ)``, κ = 12.
* ``dtaci``   Dynamically-tuned Adaptive Conformal Inference (Gibbs & Candès,
  arXiv:2208.08401): per provider × horizon × interval, eight ACI experts with step
  sizes γ ∈ {0.001, …, 0.128}, each updated ``α ← α + γ(a − err)``; weights updated by
  exponential weighting of the pinball loss ``ℓ(β, α) = a(β − α) − min(0, β − α)`` of
  ``β = sup{b : Y ∈ C(b)}``, mixed with ``σ = 1/(2I)``; the paper's adaptive η over the
  last I = 60 origins; output is the weighted average of the experts (the deterministic
  variant). The interval at level α reads the pooled score distribution at
  ``clip(1 − α, 0, 1)``, so DtACI adapts, per provider, *where* the pooled scores are read.

Delayed feedback. A forecast from origin t′ for month P is *resolved* at the first origin
whose as-of data contain P (``first_release``); only resolved forecasts, with their
first-published outturn, feed any method. At horizon h that is origin t′ + h at the
earliest, so the adaptive methods learn with an h-month lag, as they would in operation.

Seal (P11). ``first_release`` checks the table it has built, and ``calibrate`` every forecast
row that carries a first release before it scores any, with ``splits.assert_not_sealed``:
without the unseal token neither returns anything that holds a sealed period, until the seal
lifts after ``conf-run-v1`` (``splits``' post-run state).
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable

import numpy as np
import pandas as pd

from nhs_ae.calibrate.g1 import mask
from nhs_ae.evaluate import splits
from nhs_ae.evaluate.asof import TARGETS, load_asof
from nhs_ae.features.hierarchy import current_region_map
from nhs_ae.models.base import QUANTILES
from nhs_ae.models.gbm import _pairs

log = logging.getLogger(__name__)

POOLED_WINDOW = 12      # resolved forecast origins in the pooled calibration set
SERIES_WINDOW = 36      # resolved forecast origins per provider
KAPPA = 12.0            # shrinkage towards the pooled widening, in pseudo-observations
MIN_POOLED = 10         # fewer pooled scores than this: no adjustment (burn-in only)
GAMMAS = (0.001, 0.002, 0.004, 0.008, 0.016, 0.032, 0.064, 0.128)
DTACI_I = 60
METHODS = ("pooled", "series", "dtaci")
KEYS = ["origin", "series", "horizon", "period", "scale"]


def first_release(vintages: pd.DataFrame, origins: Iterable, targets=tuple(TARGETS),
                  region_map: pd.Series | None = None, since=None,
                  level: str = "provider", unseal_token: str | None = None) -> pd.DataFrame:
    """``target, series, period, y_first, resolved``: for every provider-month, the first
    origin whose as-of data contain it and the value as then published. Late submitters
    resolve late; months never published stay absent. Raises ``SealedOriginError`` if the
    table holds a sealed period, unless ``unseal_token`` is valid or the seal has lifted
    (``splits``' post-run state)."""
    region_map = current_region_map(vintages) if region_map is None else region_map
    frames = []
    for o in origins:
        d = load_asof(o, "asof", vintages, region_map)
        for target in targets:
            p = d.panel(target, level)
            if since is not None:
                p = p.loc[p.index >= pd.Timestamp(since)]
            long = p.stack(future_stack=True).dropna().rename("y_first").reset_index()
            long.columns = ["period", "series", "y_first"]
            long["target"], long["resolved"] = target, pd.Timestamp(o)
            frames.append(long)
    fr = pd.concat(frames, ignore_index=True).sort_values("resolved", kind="stable")
    fr = fr.drop_duplicates(["target", "series", "period"], keep="first").reset_index(drop=True)
    splits.assert_not_sealed(fr[["period"]], unseal_token)
    return fr


def _conf_q(scores: np.ndarray, a: float) -> float:
    n = len(scores)
    return float(np.quantile(scores, min(1.0, (1 - a) * (1 + 1 / n)))) if n else float("nan")


class DtACI:
    """DtACI state for one (horizon, interval), vectorised over providers."""

    def __init__(self, n_series: int, a: float, gammas=GAMMAS, interval: int = DTACI_I):
        self.a, self.g, self.k, self.interval = a, np.asarray(gammas), len(gammas), interval
        self.alpha = np.full((n_series, self.k), a)
        self.w = np.ones((n_series, self.k))
        self.sigma = 1 / (2 * interval)
        self.c = math.log(self.k * interval) + 2
        self.sq_hist: list[np.ndarray] = []

    def level(self, sids: np.ndarray) -> np.ndarray:
        p = self.w[sids] / self.w[sids].sum(axis=1, keepdims=True)
        return (p * self.alpha[sids]).sum(axis=1)

    def update(self, sids: np.ndarray, beta: np.ndarray) -> None:
        """One resolved step for the providers ``sids`` (unique), with realised ``beta``."""
        al, w = self.alpha[sids], self.w[sids]
        p = w / w.sum(axis=1, keepdims=True)
        diff = beta[:, None] - al
        loss = self.a * diff - np.minimum(0.0, diff)
        err = (al > beta[:, None]).astype(float)            # expert's set missed Y
        sq = np.full(len(self.alpha), np.nan)
        sq[sids] = (p * loss ** 2).sum(axis=1)
        self.sq_hist.append(sq)
        denom = np.nansum(np.asarray(self.sq_hist[-self.interval:])[:, sids], axis=0)
        eta = np.where(denom > 0, np.sqrt(self.c / np.where(denom > 0, denom, 1.0)), 0.0)
        wbar = w * np.exp(-eta[:, None] * (loss - loss.min(axis=1, keepdims=True)))
        mixed = (1 - self.sigma) * wbar + wbar.sum(axis=1, keepdims=True) * self.sigma / self.k
        self.w[sids] = mixed / mixed.sum(axis=1, keepdims=True)
        self.alpha[sids] = al + self.g[None, :] * (self.a - err)


def _realised_beta(s: np.ndarray, pool: np.ndarray) -> np.ndarray:
    """β = 1 − (level at which the pooled score distribution first reaches s)."""
    levels = np.linspace(0.0, 1.0, len(pool))
    return 1.0 - np.interp(s, pool, levels)


def _calibrate_target(g: pd.DataFrame, fr: pd.DataFrame, methods,
                      failed: pd.DataFrame | None = None,
                      trace: dict | None = None,
                      unseal_token: str | None = None) -> dict[str, pd.DataFrame]:
    """``failed`` (origin, series, horizon rows; guard G1): kept out of every pool, DtACI
    updates included, and issued unadjusted. ``trace`` (a dict) receives the origin set of
    the pooled window consulted at each issuing origin t and horizon h, as
    ``trace[(target, t, h)]`` = sorted origins; it changes nothing else. ``unseal_token``
    goes to the seal check of every row that carries a first release."""
    qs = sorted(g["quantile"].unique())
    wide = g.set_index([*KEYS, "quantile"])["value"].unstack("quantile").reset_index()
    wide = wide.merge(fr[["series", "period", "y_first", "resolved"]], on=["series", "period"],
                      how="left").sort_values(["origin", "series", "horizon"]).reset_index(drop=True)
    # every row with a first release gets a CQR score below, before ``valid`` (resolution, G1)
    # filters any out, so the seal covers them all
    splits.assert_not_sealed(wide.loc[wide["y_first"].notna(), ["origin", "period"]], unseal_token)
    fail = mask(wide, failed, ["origin", "series", "horizon"])
    L = np.log1p(np.clip(wide[qs].to_numpy(float), 0, None))
    Y = np.log1p(wide["y_first"].to_numpy(float))
    pairs = _pairs(tuple(qs))
    alphas = [2 * qs[lo] for lo, _ in pairs]
    S = np.column_stack([np.maximum(L[:, lo] - Y, Y - L[:, hi]) for lo, hi in pairs])
    sid = pd.Categorical(wide["series"]).codes.astype(int)
    n_series = sid.max() + 1
    origin = wide["origin"].to_numpy()
    horizon = wide["horizon"].to_numpy()
    resolved = wide["resolved"].to_numpy()
    valid = ~np.isnan(S).any(axis=1) & ~pd.isna(resolved) & ~fail
    adj = {m: np.zeros_like(S) for m in methods}
    learners = {(h, j): DtACI(n_series, a) for h in np.unique(horizon)
                for j, a in enumerate(alphas)}
    issued_pool: dict[tuple, np.ndarray] = {}   # (origin, h, j) -> sorted pooled scores used
    for t in np.unique(origin):
        for h in np.unique(horizon):
            hist = valid & (horizon == h) & (resolved <= t)
            idx = np.flatnonzero(hist)
            recent = np.unique(origin[idx])[-POOLED_WINDOW:]
            pooled_idx = idx[np.isin(origin[idx], recent)]
            # per-provider window: its SERIES_WINDOW most recent resolved forecasts
            hs = pd.DataFrame({"i": idx, "sid": sid[idx], "o": origin[idx]})
            ser_idx = hs.sort_values("o").groupby("sid").tail(SERIES_WINDOW)
            # DtACI: absorb forecasts resolved exactly at t, oldest first
            new = np.flatnonzero(valid & (horizon == h) & (resolved == t))
            for t_prev in np.unique(origin[new]):
                rows = new[origin[new] == t_prev]
                for j in range(len(pairs)):
                    pool = issued_pool.get((t_prev, h, j))
                    if pool is not None:
                        learners[(h, j)].update(sid[rows], _realised_beta(S[rows, j], pool))
            issue = np.flatnonzero((origin == t) & (horizon == h))
            if not len(issue):
                continue
            if trace is not None:
                trace[(g["target"].iloc[0], pd.Timestamp(t), int(h))] = list(pd.to_datetime(recent))
            for j, a in enumerate(alphas):
                pool = np.sort(S[pooled_idx, j])
                if len(pool) < MIN_POOLED:
                    continue
                issued_pool[(t, h, j)] = pool
                e_pool = _conf_q(pool, a)
                if "pooled" in methods:
                    adj["pooled"][issue, j] = e_pool
                if "series" in methods:
                    n_min = math.ceil(1 / a)
                    e_ser = {}
                    for s_id, grp in ser_idx.groupby("sid"):
                        sc = S[grp["i"].to_numpy(), j]
                        n = len(sc)
                        e_ser[s_id] = ((n * _conf_q(sc, a) + KAPPA * e_pool) / (n + KAPPA)
                                       if n >= n_min else e_pool)
                    adj["series"][issue, j] = [e_ser.get(s, e_pool) for s in sid[issue]]
                if "dtaci" in methods:
                    lv = np.clip(1 - learners[(h, j)].level(sid[issue]), 0.0, 1.0)
                    adj["dtaci"][issue, j] = np.quantile(pool, lv)
    for m in methods:
        adj[m][fail, :] = 0.0                     # G1: a failed forecast is issued as produced
    out = {}
    base = wide[KEYS]
    for m in methods:
        Lc = L.copy()
        for j, (lo, hi) in enumerate(pairs):
            Lc[:, lo] -= adj[m][:, j]
            Lc[:, hi] += adj[m][:, j]
        vals = np.maximum(np.expm1(np.sort(Lc, axis=1)), 0.0)
        vals[np.isnan(L).any(axis=1)] = np.nan
        frame = pd.concat([base, pd.DataFrame(vals, columns=qs)], axis=1)
        out[m] = frame.melt(id_vars=KEYS, var_name="quantile", value_name="value")
    return out


def calibrate(fc: pd.DataFrame, fr: pd.DataFrame, methods=METHODS,
              failed: pd.DataFrame | None = None, trace: dict | None = None,
              unseal_token: str | None = None) -> pd.DataFrame:
    """Calibrated copies of one model's long forecast table (single mode, provider level).

    Returns the harness forecast contract with ``model`` renamed ``<model>+<method>``.
    ``failed`` (``calibrate.g1.failed_forecasts`` rows) applies guard G1; None leaves it off.
    ``trace`` (a dict) records each pooled window's origin set (``_calibrate_target``).
    Raises ``SealedOriginError``, before any score, if a forecast row that carries a first
    release has a sealed origin or period, unless ``unseal_token`` is valid or the seal has
    lifted (``splits``' post-run state).
    """
    models = fc["model"].unique()
    if len(models) != 1 or fc["mode"].nunique() != 1 or fc["level"].nunique() != 1:
        raise ValueError("calibrate one model, one mode, one level at a time")
    frames = []
    for target, g in fc.groupby("target"):
        f_t = None if failed is None else failed[failed["target"] == target]
        res = _calibrate_target(g, fr[fr["target"] == target], methods, f_t, trace, unseal_token)
        for m, frame in res.items():
            frame["target"], frame["model"] = target, f"{models[0]}+{m}"
            frames.append(frame)
        log.info("calibrated %s %s", models[0], target)
    out = pd.concat(frames, ignore_index=True)
    out["mode"], out["level"] = fc["mode"].iloc[0], fc["level"].iloc[0]
    out["quantile"] = out["quantile"].astype(float)
    return out[["origin", "mode", "model", "level", "target", "series", "horizon", "period",
                "quantile", "value", "scale"]]


__all__ = ["METHODS", "QUANTILES", "DtACI", "calibrate", "first_release"]
