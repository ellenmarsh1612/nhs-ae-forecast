"""Scoring rules for quantile forecasts (pre-registration §6).

All functions take a *wide* scored frame: one row per (forecast keys), one column per
quantile level named by the level (0.025 ... 0.975) plus ``y`` for the outturn. The
harness produces that frame; ``score_rows`` adds the per-row metrics.

* Pinball loss at level τ:  τ(y−q) if y ≥ q else (1−τ)(q−y).
* Weighted interval score (Bracher et al. 2021) over K central intervals plus the
  median. For a symmetric quantile set it equals 2 × the mean pinball loss over the
  set; ``wis_interval_form`` computes it the long way so the identity can be tested.
* Coverage of the 50% and 90% central intervals.
* MASE: |y − median| / scale, where ``scale`` is the in-sample mean absolute seasonal
  (lag-12) difference of the training series at the origin, so it is comparable across
  models fitted on the same data.
* PIT: the forecast CDF evaluated at y, by linear interpolation between the quantile
  values (0 below the lowest, 1 above the highest). Coarse but adequate for histograms.
* Paired bootstrap over series for the difference in a metric between two models.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def pinball(y: np.ndarray, q: np.ndarray, tau: float) -> np.ndarray:
    d = y - q
    return np.where(d >= 0, tau * d, (tau - 1) * d)


def _levels(frame: pd.DataFrame) -> list[float]:
    return sorted(c for c in frame.columns if isinstance(c, float))


def wis_interval_form(frame: pd.DataFrame) -> np.ndarray:
    levels = _levels(frame)
    y = frame["y"].to_numpy(float)
    alphas = sorted({round(2 * t, 6) for t in levels if t < 0.5})
    total = 0.5 * np.abs(y - frame[0.5].to_numpy(float))
    for a in alphas:
        lo, hi = frame[a / 2].to_numpy(float), frame[1 - a / 2].to_numpy(float)
        interval = (hi - lo) + (2 / a) * (lo - y) * (y < lo) + (2 / a) * (y - hi) * (y > hi)
        total = total + (a / 2) * interval
    return total / (len(alphas) + 0.5)


def pit(frame: pd.DataFrame) -> np.ndarray:
    levels = _levels(frame)
    q = frame[levels].to_numpy(float)
    y = frame["y"].to_numpy(float)
    out = np.empty(len(y))
    for i in range(len(y)):
        out[i] = np.interp(y[i], q[i], levels, left=0.0, right=1.0) if np.all(np.isfinite(q[i])) else np.nan
    return out


def score_rows(frame: pd.DataFrame, unseal_token: str | None = None) -> pd.DataFrame:
    """Add wis, abs_err, mase (if ``scale`` present), cov50, cov90, pit columns.

    Every scoring path ends here, so this is where the confirmatory seal is enforced
    (``evaluate.splits``): rows whose origin or target period is sealed raise
    ``SealedOriginError`` unless ``unseal_token`` is valid.
    """
    from nhs_ae.evaluate.splits import assert_not_sealed
    if {"origin", "period"} & set(frame.columns):
        assert_not_sealed(frame, unseal_token)
    levels = _levels(frame)
    y = frame["y"].to_numpy(float)
    losses = np.column_stack([pinball(y, frame[t].to_numpy(float), t) for t in levels])
    out = frame.copy()
    out["wis"] = 2 * losses.mean(axis=1)
    out["abs_err"] = np.abs(y - frame[0.5].to_numpy(float))
    if "scale" in frame.columns:
        scale = frame["scale"].to_numpy(float)
        out["mase"] = np.where(scale > 0, out["abs_err"] / np.where(scale > 0, scale, 1.0), np.nan)
    out["cov50"] = (frame[0.25] <= frame["y"]) & (frame["y"] <= frame[0.75])
    out["cov90"] = (frame[0.05] <= frame["y"]) & (frame["y"] <= frame[0.95])
    out["pit"] = pit(frame)
    return out


def mase_scale(panel: pd.DataFrame, m: int = 12) -> pd.Series:
    """Per series: mean |y_t − y_{t−m}| over the training panel (NaN if < 2 pairs)."""
    d = (panel - panel.shift(m)).abs()
    n = d.notna().sum()
    return d.mean().where(n >= 2)


def summarise(scores: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Mean metrics per group. MASE is the mean of per-row ratios, as pre-registered."""
    agg = {"wis": "mean", "abs_err": "mean", "cov50": "mean", "cov90": "mean", "y": "size"}
    if "mase" in scores.columns:
        agg["mase"] = "mean"
    out = scores.groupby(by, observed=True).agg(agg).rename(columns={"y": "n"})
    return out.reset_index()


def paired_bootstrap(a: pd.DataFrame, b: pd.DataFrame, metric: str = "wis",
                     unit: str = "series", n: int = 1000, seed: int = 0,
                     keys: tuple[str, ...] = ("series", "origin", "horizon", "period")) -> dict:
    """Bootstrap over ``unit`` (default: series) of mean(b − a) and of the relative change.

    Rows are paired on ``keys``; a pair scores only if both models scored it. Returns
    the point estimate and the 2.5/97.5 percentiles for the absolute difference and
    for the relative change (b − a) / a. Negative means ``b`` is better.
    """
    keys = list(keys)
    m = a[[*keys, metric]].merge(b[[*keys, metric]], on=keys, suffixes=("_a", "_b"))
    m = m.dropna(subset=[f"{metric}_a", f"{metric}_b"])  # e.g. MASE is NaN for cold starts
    per_unit = m.groupby(unit)[[f"{metric}_a", f"{metric}_b"]].mean()
    if per_unit.empty:
        return {"n_units": 0}
    rng = np.random.default_rng(seed)
    ua, ub = per_unit[f"{metric}_a"].to_numpy(), per_unit[f"{metric}_b"].to_numpy()
    idx = rng.integers(0, len(ua), size=(n, len(ua)))
    diff = (ub[idx] - ua[idx]).mean(axis=1)
    rel = (ub[idx].mean(axis=1) - ua[idx].mean(axis=1)) / ua[idx].mean(axis=1)
    return {"n_units": len(ua), "n_pairs": len(m),
            "diff": float((ub - ua).mean()), "diff_lo": float(np.percentile(diff, 2.5)),
            "diff_hi": float(np.percentile(diff, 97.5)),
            "rel": float(ub.mean() / ua.mean() - 1), "rel_lo": float(np.percentile(rel, 2.5)),
            "rel_hi": float(np.percentile(rel, 97.5))}
