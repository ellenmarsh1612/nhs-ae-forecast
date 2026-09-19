"""MinT-shrink reconciliation (Stage F; design in the pre-registration amendment of 2026-09-11).

For base forecasts ŷ of every series in a hierarchy with summing matrix S (all series ×
bottom series), MinT returns S·(S′W⁻¹S)⁻¹S′W⁻¹·ŷ: the coherent forecasts closest to ŷ
in the metric W⁻¹, where W is the covariance of base forecast errors. "Shrink" is the
choice of W: sample error covariance with its correlations shrunk towards zero by the
Schäfer–Strimmer data-driven intensity [recall: Wickramasuriya, Athanasopoulos & Hyndman
2019 for MinT; Schäfer & Strimmer 2005 for the shrinkage; citations to verify before the
write-up].

Quantile forecasts are reconciled one quantile level at a time (each quantile vector is
projected, then sorted per series). That enforces additive coherence of every quantile,
which is not the same as the quantiles of a coherent joint distribution; Stage F's F2
measures what that does to calibration.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd


def summing_matrix(bottom: list[str], parents: dict[str, list[str]]) -> tuple[np.ndarray, list[str]]:
    """S (all × bottom) with aggregates first, in the order of ``parents`` (name → bottom
    members), then the bottom series. Aggregates with no members are dropped."""
    col = {b: j for j, b in enumerate(bottom)}
    rows, names = [], []
    for name, members in parents.items():
        idx = [col[m] for m in members if m in col]
        if not idx:
            continue
        r = np.zeros(len(bottom))
        r[idx] = 1.0
        rows.append(r)
        names.append(name)
    S = np.vstack([np.asarray(rows).reshape(-1, len(bottom)), np.eye(len(bottom))])
    return S, names + list(bottom)


def shrink_cov(errors: np.ndarray, fallback_var: np.ndarray, min_obs: int = 3) -> np.ndarray:
    """Schäfer–Strimmer shrinkage covariance from an (observations × series) error matrix
    with NaN for missing. Variances need ``min_obs`` errors, otherwise ``fallback_var``;
    missing standardised errors are set to zero (their correlations shrink towards zero)."""
    e = np.asarray(errors, float)
    n_obs = np.sum(np.isfinite(e), axis=0)
    with warnings.catch_warnings():             # series with 0–1 errors: replaced just below
        warnings.simplefilter("ignore", RuntimeWarning)
        mean = np.nanmean(np.where(n_obs[None, :] > 0, e, 0.0), axis=0)
        var = np.nanvar(e, axis=0, ddof=1)
    var = np.where((n_obs >= min_obs) & np.isfinite(var) & (var > 0), var, fallback_var)
    sd = np.sqrt(var)
    z = np.where(np.isfinite(e), (e - mean[None, :]) / sd[None, :], 0.0)
    n = z.shape[0]
    m = z.shape[1]
    if n < 3:
        return np.diag(var)
    w = z[:, :, None] * z[:, None, :]                                     # (n, m, m)
    r = w.mean(axis=0) * n / (n - 1)
    var_r = n / (n - 1) ** 3 * ((w - w.mean(axis=0)) ** 2).sum(axis=0)
    off = ~np.eye(m, dtype=bool)
    denom = float((r[off] ** 2).sum())
    lam = float(np.clip(var_r[off].sum() / denom, 0.0, 1.0)) if denom > 0 else 1.0
    r_star = (1 - lam) * r
    np.fill_diagonal(r_star, 1.0)
    W = r_star * sd[:, None] * sd[None, :]
    # guard against a numerically indefinite estimate
    vals, vecs = np.linalg.eigh(W)
    floor = 1e-9 * max(vals.max(), 1e-12)
    return (vecs * np.clip(vals, floor, None)) @ vecs.T


def mint(yhat: np.ndarray, S: np.ndarray, W: np.ndarray, observed: np.ndarray | None = None) -> np.ndarray:
    """Reconcile base forecasts ``yhat`` (… × all series) with MinT; returns the same shape.

    ``observed`` (bool per row of S) marks the series that have a base forecast. The
    projection then uses only those rows (W is their covariance; other entries of ``yhat``
    are ignored) and returns every row of S: an unforecast bottom series is inferred from
    its parents, which is GLS with missing observations. S restricted to the observed rows
    must have full column rank (e.g. at most one unobserved child per observed parent).
    """
    obs = np.ones(S.shape[0], bool) if observed is None else np.asarray(observed, bool)
    So = S[obs]
    Winv_S = np.linalg.solve(W, So)                                       # W⁻¹S  (obs × bottom)
    A = So.T @ Winv_S                                                     # S′W⁻¹S
    y = np.atleast_2d(yhat)[:, obs]
    bottom = np.linalg.solve(A, Winv_S.T @ y.T)                            # (bottom × …)
    out = (S @ bottom).T
    return out.reshape(np.shape(yhat))


def reconcile_quantiles(q: pd.DataFrame, S: np.ndarray, names: list[str], W: np.ndarray,
                        observed: np.ndarray | None = None) -> pd.DataFrame:
    """``q``: series (index, in ``names`` order) × quantile levels (columns). Each quantile
    column is projected with MinT, then each row is sorted to remove crossings."""
    q = q.reindex(names)
    rec = mint(np.nan_to_num(q.to_numpy()).T, S, W, observed).T             # (all × Q)
    rec = np.sort(rec, axis=1)
    return pd.DataFrame(np.maximum(rec, 0.0), index=q.index, columns=q.columns)
