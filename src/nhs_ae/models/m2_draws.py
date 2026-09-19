"""Fit one M2 origin and keep its draws (WO-A step 2; the live command uses the same function).

The fit is ``stage_e._fit_origin``'s, unchanged: the same data preparation, model, sampler and
seeds (fit seed year × 100 + month, predictive seed month). Besides the quantile rows it keeps:

* the **posterior predictive sample paths**: one path per posterior draw, integer counts, as an
  array ``(draw, icb, horizon)`` per target. Draw ``c × 1000 + d`` is chain ``c``, draw ``d``
  (``m2._post``'s stacking). Region and England paths are sums of ICB paths by the region map.
* the **posterior draws of every quantity** ``m2.predictive_draws`` **reads**: scalar parameters
  in full, and for any variable whose last axis is time, its final month (all draws) and its
  posterior-mean path. With the predictive seed this regenerates the paths exactly.

The full latent paths are not stored (about 32 GB over the 69 DEV origins); a fit is
bit-reproducible from its seeds, code and data, so they can be regenerated per origin.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from nhs_ae.models import m2


def fit_with_draws(origin: date, rung: m2.Rung, panels: dict, regions: pd.Series, draws: int = 1000,
                   tune: int = 1000, cores: int = 4):
    """(quantile rows, diagnostics, trace, predictive paths, posterior subset, months)."""
    d = m2.prepare(panels, region_of=regions, clean=rung.clean_data)
    model = m2.build_model(d, rung)
    trace, secs = m2.fit(model, draws=draws, tune=tune, cores=cores, seed=origin.year * 100 + origin.month)
    diag = {"origin": pd.Timestamp(origin), "rung": rung.name, "seconds": secs, **m2.diagnostics(trace, rung)}
    fut, sims = m2.predictive_draws(trace, d, m2.HORIZONS, seed=origin.month, rung=rung)
    fc = m2._quantile_rows(sims, d.icbs, m2.HORIZONS, fut, m2.QUANTILES).assign(level="icb")
    if rung.shared_factor or rung.corr_innov or rung.name.endswith("_agg"):   # region / England
        fc = pd.concat([fc, m2.aggregate_forecast(sims, d, regions, m2.HORIZONS, fut)], ignore_index=True)
    fc["origin"] = pd.Timestamp(origin)
    paths = integer_paths(sims)
    post = posterior_subset(trace, len(d.months))
    meta = {"icbs": np.array(d.icbs), "periods": np.array([f"{p:%Y-%m}" for p in fut]),
            "horizons": np.array(m2.HORIZONS), "months": np.array([f"{m:%Y-%m}" for m in d.months]),
            "regions": regions.reindex(d.icbs).fillna("?").to_numpy().astype(str)}
    return fc, diag, trace, paths, post, meta


def integer_paths(sims: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Negative-binomial draws are integer counts held as floats: store them exactly as int32."""
    out = {}
    for t, x in sims.items():
        if not np.array_equal(x, np.round(x)) or x.min() < 0 or x.max() >= 2 ** 31:
            raise ValueError(f"{t}: predictive draws are not non-negative int32 counts")
        out[t] = x.astype(np.int32)
    return out


def posterior_subset(trace, n_months: int) -> dict[str, np.ndarray]:
    """Scalars in full; time-indexed variables as final month (all draws) and posterior-mean path."""
    out = {}
    for name, da in trace.posterior.data_vars.items():
        x = np.asarray(da.values, dtype=np.float64)          # (chain, draw, ...)
        if x.ndim > 2 and x.shape[-1] == n_months:
            out[f"{name}__last"] = x[..., -1]
            out[f"{name}__mean_path"] = x.mean(axis=(0, 1))
        else:
            out[name] = x
    return out


def save_npz(path: Path, arrays: dict[str, np.ndarray]) -> int:
    """Compressed, written atomically; returns the file size in bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + ".tmp.npz")
    np.savez_compressed(tmp, **arrays)
    os.replace(tmp, path)
    return path.stat().st_size
