"""Revision audit: what did NHS England actually change after first publication?

Two tables, both computed from the vintage parquet and provider rows only:

``revision_audit``  one row per (period, measure). Compares the *first* archived
    version of the period with the *latest*. Measures are the three targets and their
    six component metrics. Columns: number of versions, first and last availability
    dates, providers in first and latest, late submitters (present later, absent at
    first), withdrawn (the reverse), providers whose value changed, the national total
    in each version and its relative change, the largest absolute provider change, and
    the median relative change among changed providers.

``training_leakage``  one row per (origin, measure). For the periods in the twelve
    months before the origin, how different is the as-of training data from the final
    data: share of provider-months whose value differs, mean absolute relative
    difference over provider-months present in both, and the number of provider-months
    present only in the final data (late submitters the as-of forecaster never saw).

The first table is the descriptive result the pre-registration's H4 rests on; the
second says how much of that difference a forecaster at each origin was exposed to.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from nhs_ae.evaluate.asof import METRICS_NEEDED, TARGETS, as_of_date, last_period

MEASURES: dict[str, tuple[str, ...]] = {**TARGETS, **{m: (m,) for m in METRICS_NEEDED}}


def _measures_wide(rows: pd.DataFrame) -> pd.DataFrame:
    """org_code × measure for one version of one period (targets NaN if a part is missing)."""
    wide = rows.pivot_table(index="org_code", columns="metric", values="value", aggfunc="first")
    out = {}
    for name, parts in MEASURES.items():
        cols = [c for c in parts if c in wide.columns]
        out[name] = wide[cols].sum(axis=1, min_count=len(parts)) if len(cols) == len(parts) else np.nan
    return pd.DataFrame(out, index=wide.index)


def _versions(rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, list]:
    snaps = sorted(rows["snapshot"].unique())
    first = _measures_wide(rows[rows["snapshot"] == snaps[0]])
    latest = _measures_wide(rows.sort_values("snapshot").drop_duplicates(["org_code", "metric"], keep="last"))
    return first, latest, snaps


def revision_audit(vintages: pd.DataFrame) -> pd.DataFrame:
    prov = vintages[~vintages["is_total"]]
    out = []
    for period, rows in prov.groupby("period"):
        first, latest, snaps = _versions(rows)
        for measure in MEASURES:
            a, b = first[measure].dropna(), latest[measure].dropna()
            common = a.index.intersection(b.index)
            d = b[common] - a[common]
            changed = d[d != 0]
            rel = (changed.abs() / a[changed.index].replace(0, np.nan)).dropna()
            out.append({
                "period": period, "measure": measure, "n_versions": len(snaps),
                "first_available": pd.Timestamp(snaps[0]).date(), "last_available": pd.Timestamp(snaps[-1]).date(),
                "providers_first": len(a), "providers_latest": len(b),
                "late_submitters": len(b.index.difference(a.index)),
                "withdrawn": len(a.index.difference(b.index)),
                "providers_changed": len(changed),
                "national_first": a.sum(), "national_latest": b.sum(),
                "national_rel_change": b.sum() / a.sum() - 1 if a.sum() else np.nan,
                "max_abs_change": changed.abs().max() if len(changed) else 0.0,
                "median_rel_change_changed": rel.median() if len(rel) else np.nan,
            })
    return pd.DataFrame(out)


def training_leakage(vintages: pd.DataFrame, origins: list[date], window: int = 12) -> pd.DataFrame:
    prov = vintages[~vintages["is_total"]]
    final = (prov.sort_values("snapshot").drop_duplicates(["period", "org_code", "metric"], keep="last"))
    out = []
    for origin in origins:
        upto = last_period(origin)
        start = upto - pd.DateOffset(months=window - 1)
        cut = as_of_date(origin)
        recent = prov[(prov["period"] >= start) & (prov["period"] <= upto) & (prov["snapshot"] <= cut)]
        asof = recent.sort_values("snapshot").drop_duplicates(["period", "org_code", "metric"], keep="last")
        fin = final[(final["period"] >= start) & (final["period"] <= upto)]
        for measure in MEASURES:
            a = pd.concat({p: _measures_wide(r)[measure] for p, r in asof.groupby("period")}) if len(asof) else pd.Series(dtype=float)
            b = pd.concat({p: _measures_wide(r)[measure] for p, r in fin.groupby("period")})
            a, b = a.dropna(), b.dropna()
            common = a.index.intersection(b.index)
            d = (b[common] - a[common])
            rel = (d.abs() / a[common].replace(0, np.nan)).dropna()
            out.append({
                "origin": pd.Timestamp(origin), "measure": measure,
                "provider_months": len(common),
                "share_changed": float((d != 0).mean()) if len(d) else np.nan,
                "mean_abs_rel_diff": float(rel.mean()) if len(rel) else np.nan,
                "only_in_final": len(b.index.difference(a.index)),
                "only_in_asof": len(a.index.difference(b.index)),
            })
    return pd.DataFrame(out)


def summarise_audit(audit: pd.DataFrame) -> pd.DataFrame:
    """By financial year: mean providers changed, late submitters, national change."""
    fy = audit["period"].dt.year - (audit["period"].dt.month < 4)
    g = audit.assign(fy=fy).groupby(["measure", "fy"])
    return g.agg(periods=("period", "size"), versions=("n_versions", "mean"),
                 providers_changed=("providers_changed", "mean"),
                 late_submitters=("late_submitters", "mean"),
                 abs_national_rel_change=("national_rel_change", lambda s: s.abs().mean()),
                 max_national_rel_change=("national_rel_change", lambda s: s.abs().max())).reset_index()
