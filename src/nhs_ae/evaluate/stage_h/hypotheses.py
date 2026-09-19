"""Stage H hypotheses (design §7): H1, H2 (M1 and M2 clauses), the primary comparison, the
descriptive headline, H3, H4, H4-original, H4b, H5 and F2, each with its DEV side.

All functions are pure: they take scored frames (``harness.score_forecasts`` output read back
from the store, with a boolean ``failed`` column from ``g1.mark`` where G1 applies) and return
dicts of DataFrames and verdict dicts. They never score, never read files, never call
``assert_not_sealed``. Every two-forecast comparison goes through ``stats.compare``; every
coverage interval through ``stats.two_way``.

CONTRACT (skeleton; the implementation must keep these signatures):

variants(frame) -> list[tuple[str, DataFrame]]
    [("as_issued", frame), ("failed_dropped", frame[~frame.failed])]; a frame without a
    ``failed`` column gives only as_issued.

h1(scored, origins) -> dict
    scored: provider, as-of rows for b0_seasonal_naive, m1_lightgbm and m1_lightgbm_v3_raw
    (any origins/horizons; the function keeps winter & horizon == 3 & origin in ``origins``).
    §7.3: per (tested model, target) compare(B0 rows, model rows, "mase") -> verdict
    ("confirmed" | "not confirmed (refuted, as registered)"), qualifier, plus a pooled-targets
    row; overall verdict per tested model (default M1 decides; M1 v3 raw alongside); LOO
    over ``origins`` with the per-target, qualifier and composite (max over targets of
    rel_hi) fragility rules and the full-sample-differs extension; the subsets that flip.
    Returns {"table", "overall", "loo"}.

coverage_by_horizon(rows, counted, fold, stat="cov90", cells=("horizon",)) -> DataFrame
    Two-way table over CONF19 (fold={}) or CONF21 (fold=D7_FOLD) for one model/level slice.
origin_year_cells(rows, stat="cov90") -> DataFrame
    ``stage_d.coverage_cells``-style cells (origin-year x horizon, 0.87-0.93 met or not).

primary(rows, counted, fold) -> dict
    rows: M1 v3 raw + pooled (Stage D population) + G1, provider, as-of, all months, marked.
    §7.5: two-way cov90 by horizon (CONF19), verdict_primary, and every "reported alongside"
    item: point estimates, provider-only intervals, pooled cov50 and per-target cov90/cov50
    with two-way intervals, the 0.87-0.93 cells (CONF19, and CONF21 separately), both G1
    variants. Returns {"table", "verdict", "alongside": {...}}.

h2_m1(rows, counted, fold) -> dict      default M1, provider, as-of, all months (§7.5).
h2_m2(rows, counted, fold, fits) -> dict
    m2d_corr ICB rows; ``fits``: one row per attempted fit (origin, attempt, failed, rhat_max,
    ess_bulk_min, divergences, ...). Not evaluable if >= M2_FAIL_LIMIT counted units failed.

headline(raw, pooled, counted, fold, icb_raw_ets=None) -> dict
    raw, pooled: {model_name: rows} for b1_ets, b2_stl_arima, m1_lightgbm_v3_raw at provider
    level (Stage D population), G1-marked. On common rows: two-way cov90 raw and pooled, gaps
    to nominal in pp, pooled - raw via two_way_diff, by horizon and by origin-year; the ICB
    raw-ETS coverage table separately (§7.6).

h3(scored, origins) -> dict
    scored: {(base, kind): rows}, base in ("b1", "b2", "m1_v3_raw"), kind in ("base", "mint"),
    Stage F population, all four levels, winter-h3 rows kept inside. §7.7 via
    ``stage_f.h3_table`` (inputs checked as ``stats.compare`` checks them); England interval
    n/a; region caution; headline = m1_v3_raw; LOO verdict-per-subset fragility; the note
    "R2 not tested (phase 1b)". Both G1 variants.

h4(scored, origins) -> dict
    scored: {(model_key, mode): rows} for b0, b1, b2, m1 (m1_v3_raw alongside), provider,
    modes "asof" and "final". §7.8: 2% clause per model x target, common-row ranking per
    target by mean of per-series means, verdict, LOO fragility, G1 variants for b1/b2/m1_v3_raw.
h4_original(scored, origins, h4_result) -> dict   §7.9.

h4b_components(vintages, origins, window=12) -> DataFrame
    Per origin x target: V, L, Wd, sum_asof, sum_final, lost_originals (count, final sum),
    E_o (as-of end month). Window = the 12 months ending at the as-of end month (P14).
    Provider rows only (``~is_total``); England total = sum of provider rows. Keyword
    ``end`` = E (§2.4; default RUN_END, the orchestrator passes ctx.end): an origin beyond it
    raises, and no period after the last origin's M-1 is read.
h4b(components, counted, full) -> dict   §7.10 verdicts: the 19-origin table as "table", the
    21-origin one as "conf21": {"table"} when it differs (never one table for both).
h4b_dev(components, origins) -> dict      the DEV side: counts and components, no verdict.

H5_LINE: str

f2(contenders, scored, icb_of, region_of, origins, *, failed=None) -> dict
    ``stage_f.f2_table``-based (with ``origins=``), plus cov50 by horizon, origin-year cells,
    per-target WIS intervals (England n/a), the "median non-additivity" label for m2d_corr,
    both G1 variants. The coherence gap leaves out G1-failed forecasts and aggregate medians
    that are not positive, and counts them (``coherence_gaps``; ``stage_f`` is unchanged).
f2_wis(scored, origins) -> DataFrame
    F2's winter-h3 WIS table alone, as issued: the statistic of its DEV seasons (§7.13).

dev_seasons(stat_fn, rows, **tags) -> DataFrame
    Apply a winter-h3 statistic per DEV winter season (stats.season of the target period);
    marks the 2023/24 fragment (excluded from min/max); slice columns in front.
dev_origin_years(rows, stat="cov90") -> DataFrame
    Coverage per assessable DEV origin-year x horizon (stage_d.coverage_cells, assessed only).

Conventions and additions beyond the skeleton:
- Each result holds the as-issued variant (the decisive one) at its top level, and the
  failed-dropped variant under "failed_dropped" (None without a ``failed`` column); primary
  keeps both under "alongside". Every table carries its slice as columns (split, origin_set,
  n_origins, model/level/mode when single, g1, and stat/months/horizons where they apply).
- h1, h3 and h4 take a keyword ``loo=True``; ``loo=False`` skips leave-one-origin-out (for
  the per-season DEV tables).
- M1 v3 raw is a registered alongside item of H1, H4 and H4-original: h1, h4 and h4_original
  raise without its rows (both modes for H4). Their keyword ``alongside=False`` lets a caller
  that deliberately omits it leave them out; rows given are still used, and H4 frames in
  one mode only always raise.
- Every frame holding a G1 base's rows (B1, B2, M1 v3 raw; raw, + pooled or + MinT) must
  carry the ``failed`` column from ``g1.mark``; without it the function raises, since the
  failed-dropped variant and the failed counts would otherwise be silently wrong.
- H3's "table" and F2's "table", "wis" and "cells" hold every level in one frame with a
  ``level`` column: report.py writes one file per level (§7.1: provider and ICB never share
  a table). H3's "verdicts" (one row per base) joins the ICB and provider clauses by design.
- h1_label(rel, rel_hi) -> (verdict, qualifier): §7.3's per-target rule on its own.
- dev_flags(conf, dev, keys=("stat",), value="value", absent=...) -> DataFrame: a CONF
  winter-h3 value against the DEV range over the seasons in range (§7.13); ``dev`` None keeps
  the CONF rows with ``outside`` None and a ``reason``.
- dev_coverage_flags(conf_cells, dev_cells, pooled=None, absent=...) -> DataFrame: CONF
  origin-year cells against the DEV minimum and maximum at each horizon; the pooled CONF
  value beside them, unflagged (§7.13); ``dev_cells`` None as for dev_flags.
- slice_tags(origins) -> dict: split, origin set and origin count of a table (§7.1).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping

import numpy as np
import pandas as pd

from nhs_ae.evaluate import stage_d, stage_f
from nhs_ae.evaluate.asof import METRICS_NEEDED, TARGETS, as_of_date, last_period
from nhs_ae.evaluate.stage_h import stats
from nhs_ae.evaluate.stage_h.common import (
    CELL_BAND,
    CONF19,
    CONF21,
    DEV,
    DRY,
    G1_BASES,
    H1_BAR,
    H3_PROVIDER_TOL,
    H4_MODELS,
    H4_ORIGINAL_PP,
    H4_TOL,
    H4B_MIN_COUNT,
    K5,
    M2_FAIL_LIMIT,
    NAMES,
    RUN_END,
    W5,
    ts,
)

TARGET_ORDER = tuple(TARGETS)            # att_all, att_type1, adm_via_ae
AS_ISSUED, FAILED_DROPPED = "as_issued", "failed_dropped"
POOLED = "pooled"                        # H1's pooled-targets row (descriptive)
NOMINAL = 0.90
M2_FAIL_SHARE = 0.2                      # §4: H2's M2 clause needs more than 20% failed units
FRAGMENT_SEASON = "2023/24"              # DEV's last winter, cut by the seal: origin 2023-10 only
H4_MODES = ("asof", "final")
H1_REF, H1_DECIDES, H1_ALONGSIDE = NAMES["b0"], NAMES["m1"], NAMES["m1_v3_raw"]
PRIMARY_MODEL = f"{NAMES['m1_v3_raw']}+pooled"

# ---- registered labels and notes ---------------------------------------------------------
NOT_CONFIRMED = "not confirmed (refuted, as registered)"
QUALIFIER_BOUNDS = {"point estimate meets the bar": (H1_BAR,),
                    "partial support": (H1_BAR, 0.0),
                    "no improvement": (0.0,)}
S9_CAVEAT = ("§9 applied to CONF (amendment of 2026-09-10): H1 and H2 are evaluated on CONF with "
             "the caveat that a bootstrap over providers within one winter does not capture "
             "between-winter variation (DEV's per-year coverage ranged from 0.51 to 0.96 for "
             "ETS).")
H2_M2_PHASE = ("a phase-1b test at ICB level, under the §9 fallback: M2 was never sampled at "
               "provider level, so the clause registered as pooled across providers is tested "
               "at ICB level, in Stage H, by an amendment that overrides the freeze-time "
               "deferral")
TEXT_A = ("M2 sampling diagnostics degrade monotonically with origin date. Across the 69 DEV "
          "origins, median max R-hat rises from 1.015 (2018-19) to 1.069 (2023) and median min "
          "bulk ESS falls from 199 to 63 (Spearman 0.77 and -0.82). CONF and the live origin "
          "both lie after 2023, so the fits carrying the H2 M2 clause are expected to be the "
          "worst sampled in the project. **No fit is excluded on diagnostics**; the plan's rule "
          "(report everything, fail only on crashes) stands. A seed-stability check "
          "pre-specified at the three worst late DEV origins found forecast quantiles stable "
          "across seeds within the registered threshold. The H2 M2-clause verdict therefore "
          "stands as reported, with the sampling trend stated as a limitation.")
TEXT_A_NOTES = ("the pattern is a trend, not a monotone sequence",
                "the 2018-19 ESS figure is 224, not 199",
                ("'the worst sampled' holds for the frozen M2's own fits, since M2f-r4's DEV "
                 "fits already sample worse"))
# Plan §6: m2d_corr's sampling on the 69 DEV origins, by origin year (results/E-m2-rerun69/)
M2_DEV_TREND = pd.DataFrame({"oyear": [2018, 2019, 2020, 2021, 2022, 2023],
                             "rhat_max_median": [1.015, 1.015, 1.026, 1.047, 1.052, 1.069],
                             "ess_bulk_min_median": [199.0, 229.0, 167.0, 84.0, 79.0, 63.0]})
R2_NOTE = "R2 not tested (phase 1b)"
ENGLAND_NA = "interval n/a (one series)"
MEDIAN_NON_ADDITIVITY = "median non-additivity"
H4_NOTE = "exploratory on CONF (amendment '§9 applied to CONF')"
H4B_LABEL = "seen"
H5_LINE = ("H5 (cold start): not evaluable on CONF, and never testable on a sealed split after "
           "Stage H. M2 exists only at ICB level, the current 36-ICB mapping is applied to the "
           "whole history so no ICB series has a cold start, and a provider-level M2 was never "
           "built.")


def _fail_limit(n: int) -> int:
    """Failed counted units that make H2's M2 clause not evaluable: M2_FAIL_LIMIT of 19, and
    more than 20% of ``n`` for another count (the dry run's six)."""
    return M2_FAIL_LIMIT if n == 19 else int(np.floor(M2_FAIL_SHARE * n)) + 1


def _more_than_half(n: int) -> int:
    return H4B_MIN_COUNT.get(n, n // 2 + 1)


# ---- slices, variants and small helpers --------------------------------------------------
def _ts_index(origins) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(sorted({ts(o) for o in origins}))


_SETS = {name: tuple(_ts_index(o)) for name, o in
         (("CONF19", CONF19), ("CONF21", CONF21), ("W5", W5), ("DEV", DEV), ("DRY", DRY))}


def _split(origins) -> str:
    """"conf" or "dev"; a table whose origins mix the two splits raises (§7.1)."""
    o = set(_ts_index(origins))
    if not o or o <= set(_SETS["CONF21"]):
        return "conf" if o else ""
    if o <= set(_SETS["DEV"]):
        return "dev"
    raise ValueError(f"a table mixes splits: origins {min(o):%Y-%m}..{max(o):%Y-%m} are neither "
                     "all DEV nor all CONF (§7.1)")


def _origin_set(origins) -> str:
    o = tuple(_ts_index(origins))
    for name, ref in _SETS.items():
        if o == ref:
            return name
    return f"{len(o)} origins {o[0]:%Y-%m}..{o[-1]:%Y-%m}" if o else "none"


def _single(rows: pd.DataFrame, col: str):
    vals = rows[col].dropna().unique()
    if len(vals) > 1:
        raise ValueError(f"table rows hold {len(vals)} {col}s: {sorted(map(str, vals))[:4]}")
    return vals[0] if len(vals) else None


def _tag(t: pd.DataFrame, rows: pd.DataFrame, cells: Iterable[str] = (), **extra) -> pd.DataFrame:
    """Slice columns in front of a table: split and origin set of ``rows``, model, level and
    mode when single-valued and not a cell, then ``extra``."""
    cells = set(cells)
    origins = rows["origin"].unique()
    front = {"split": _split(origins), "origin_set": _origin_set(origins),
             "n_origins": len(_ts_index(origins))}
    for c in ("model", "level", "mode"):
        if c in rows.columns and c not in cells and c not in t.columns:
            front[c] = _single(rows, c)
    front.update(extra)
    return _front(t, front)


def _front(t: pd.DataFrame, tags: dict) -> pd.DataFrame:
    """``tags`` as constant columns in front of ``t``, in order; a column ``t`` has is kept."""
    t = t.copy()
    for i, (k, v) in enumerate((k, v) for k, v in tags.items() if k not in t.columns):
        t.insert(i, k, v)
    return t


def slice_tags(origins) -> dict:
    """split, origin set and origin count of a table computed at ``origins`` (§7.1)."""
    return {"split": _split(origins), "origin_set": _origin_set(origins),
            "n_origins": len(_ts_index(origins))}


def _require(rows: pd.DataFrame, **values) -> None:
    """Refuse rows whose ``col`` holds anything but ``value`` (the registered slice)."""
    for col, value in values.items():
        if col in rows.columns:
            other = set(map(str, rows[col].dropna().unique())) - {value}
            if other:
                raise ValueError(f"expected {col} {value!r} only, found {sorted(other)[:4]}")


def variants(frame: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    out = [(AS_ISSUED, frame)]
    if "failed" in frame.columns:
        f = frame["failed"]
        if f.isna().any():
            raise ValueError(f"{int(f.isna().sum())} rows have no G1 flag")
        out.append((FAILED_DROPPED, frame[~f.astype(bool).to_numpy()]))
    return out


def _variant(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    """``name``'s rows of ``frame``; a frame without a ``failed`` column (a model outside G1's
    scope) is the same in both variants."""
    return dict(variants(frame)).get(name, frame)


def _variant_names(frames: Iterable[pd.DataFrame]) -> list[str]:
    return [AS_ISSUED, *([FAILED_DROPPED] if any("failed" in f.columns for f in frames) else [])]


def _g1_rows(frame: pd.DataFrame) -> np.ndarray:
    """Rows of a G1 base (B1, B2, M1 v3 raw; raw, + pooled or + MinT)."""
    base = frame["model"].astype(str).str.split("+").str[0]
    return base.isin([NAMES[k] for k in G1_BASES]).to_numpy()


def _need_g1(frame: pd.DataFrame, side: str) -> None:
    """A frame holding a G1 base's rows must carry ``failed`` (g1.mark)."""
    if "failed" not in frame.columns and _g1_rows(frame).any():
        raise ValueError(f"{side}: {int(_g1_rows(frame).sum())} rows of a G1 base and no failed "
                         "column (not G1-marked)")


def _g1_scope(frame: pd.DataFrame, side: str) -> pd.DataFrame:
    """Rows of models outside G1's scope (B0, default M1, m2d_corr) are never failed: a
    ``failed`` column left empty for them by a concat is set False; a G1 base without a flag
    raises."""
    _need_g1(frame, side)
    if "failed" not in frame.columns:
        return frame
    in_scope = _g1_rows(frame)
    empty = frame["failed"].isna().to_numpy()
    if (empty & in_scope).any():
        raise ValueError(f"{int((empty & in_scope).sum())} rows of a G1 base have no G1 flag")
    return frame.assign(failed=frame["failed"].where(~empty, False).astype(bool))


def _winter_h3(frame: pd.DataFrame, origins) -> pd.DataFrame:
    keep = (frame["winter"].astype(bool) & (frame["horizon"] == 3)
            & frame["origin"].isin(_ts_index(origins)))
    return frame[keep.to_numpy()]


def _restrict(rows: pd.DataFrame, counted, fold) -> pd.DataFrame:
    """The counted origins' rows (fold empty: CONF19), or the counted and folded origins'
    (fold D7_FOLD: CONF21)."""
    return rows[rows["origin"].isin(_ts_index([*counted, *(fold or {})])).to_numpy()]


def _all_zero(rows: pd.DataFrame) -> int:
    """Rows whose quantiles are all exactly zero (counted, not treated, outside G1's scope)."""
    q = [c for c in rows.columns if isinstance(c, float)]
    return int((rows[q].to_numpy(float) == 0).all(axis=1).sum()) if q and len(rows) else 0


def _n_failed(rows: pd.DataFrame) -> int:
    return int(rows["failed"].astype(bool).sum()) if "failed" in rows.columns else 0


def _true(x) -> bool:
    return x is not None and not pd.isna(x) and bool(x)


def _flag(x) -> bool | None:
    """A table's True/False/None flag as a Python bool or None."""
    return None if x is None or pd.isna(x) else bool(x)


def _range(values, threshold: float) -> bool | None:
    """stats.range_fragile, or None (n/a) for an empty LOO or a subset that is not evaluable."""
    v = pd.Series(list(values), dtype=float)
    if v.empty or v.isna().any():
        return None
    return stats.range_fragile(v, threshold)


def _extremes(g: pd.DataFrame, col: str) -> tuple:
    """(min, max, dropped origin at the min, dropped origin at the max) of a LOO column."""
    v = pd.to_numeric(g[col], errors="coerce") if len(g) else pd.Series(dtype=float)
    if v.empty or v.isna().any():
        return np.nan, np.nan, None, None
    return (float(v.min()), float(v.max()), g["dropped"].iloc[int(np.argmin(v.to_numpy()))],
            g["dropped"].iloc[int(np.argmax(v.to_numpy()))])


def _loo_tables(fn: Callable[[pd.DataFrame], pd.DataFrame], rows: pd.DataFrame,
                origins) -> pd.DataFrame:
    """stats.loo with ``fn`` returning a table per subset: one long table with ``dropped``."""
    out = stats.loo(lambda sub: {"t": fn(sub)}, rows, origins)
    if out.empty:
        return pd.DataFrame(columns=["dropped"])
    return pd.concat([t.assign(dropped=d) for d, t in zip(out["dropped"], out["t"])],
                     ignore_index=True)


def _loo_frames(fn: Callable[[dict], pd.DataFrame], frames: dict, loo: bool) -> pd.DataFrame:
    """Leave-one-origin-out over a dict of frames, dropping each origin present in any."""
    if not loo:
        return pd.DataFrame(columns=["dropped"])
    keys = list(frames)
    cols = {i: list(f.columns) for i, f in enumerate(frames.values())}
    both = pd.concat([f.assign(_k=i) for i, f in enumerate(frames.values())], ignore_index=True)

    def split(sub):
        return {k: sub.loc[(sub["_k"] == i).to_numpy(), cols[i]] for i, k in enumerate(keys)}

    return _loo_tables(lambda sub: fn(split(sub)), both, both["origin"].unique())


def _check_levels(frame: pd.DataFrame, side: str) -> None:
    """Per level, one model and one mode and unique keys, as ``stats.compare`` checks them."""
    stats._one_slice(frame, side, [*K5, "level"], cells=("level",))


# ---- H1 (§7.3) ---------------------------------------------------------------------------
def h1_label(rel: float, rel_hi: float) -> tuple[str, str | None]:
    """Per target: confirmed if rel_hi < -0.15, else not confirmed with its qualifier."""
    if pd.isna(rel) or pd.isna(rel_hi):
        return "not evaluable", None
    if rel_hi < H1_BAR:
        return "confirmed", None
    if rel <= H1_BAR:
        return NOT_CONFIRMED, "point estimate meets the bar"
    return NOT_CONFIRMED, "partial support" if rel < 0 else "no improvement"


def _overall(verdicts) -> str:
    """Confirmed only if every target is."""
    v = list(verdicts)
    if v and all(x == "confirmed" for x in v):
        return "confirmed"
    return NOT_CONFIRMED if NOT_CONFIRMED in v else "not evaluable"


def _h1_compare(s: pd.DataFrame, models: list[str]) -> pd.DataFrame:
    ref = s[s["model"] == H1_REF]
    rows = []
    for m in models:
        tested = s[s["model"] == m]
        for t in (*TARGET_ORDER, POOLED):
            a, b = ((ref, tested) if t == POOLED else
                    (ref[ref["target"] == t], tested[tested["target"] == t]))
            r = stats.compare(a, b, "mase")
            v, q = ("descriptive", None) if t == POOLED else h1_label(r["rel"], r["rel_hi"])
            role = "descriptive" if t == POOLED else "decides" if m == H1_DECIDES else "alongside"
            rows.append({"model": m, "role": role, "target": t, **r, "verdict": v, "qualifier": q})
    return pd.DataFrame(rows)


def _qualifier_fragile(qualifier, rel) -> bool | None:
    if qualifier is None or pd.isna(qualifier):
        return None
    flags = [_range(rel, b) for b in QUALIFIER_BOUNDS[qualifier]]
    return None if any(f is None for f in flags) else any(flags)


def _h1_fragility(full: pd.DataFrame, lt: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in full.iterrows():
        g = lt[(lt["model"] == r["model"]) & (lt["target"] == r["target"])] if len(lt) else lt
        f = {"loo_n": len(g)}
        for col in ("rel", "rel_hi"):
            (f[f"loo_{col}_min"], f[f"loo_{col}_max"], f[f"loo_drop_at_{col}_min"],
             f[f"loo_drop_at_{col}_max"]) = _extremes(g, col)
        if r["target"] == POOLED or r["verdict"] == "not evaluable":
            f.update(fragile_range=None, fragile_differs=None, fragile=None, qualifier_fragile=None)
        else:
            rng = _range(g.get("rel_hi", []), H1_BAR)
            differs = None if g.empty else bool((g["verdict"] != r["verdict"]).any())
            f.update(fragile_range=rng, fragile_differs=differs,
                     fragile=None if rng is None else bool(rng or differs),
                     qualifier_fragile=_qualifier_fragile(r["qualifier"], g.get("rel", [])))
        rows.append(f)
    return pd.concat([full.reset_index(drop=True), pd.DataFrame(rows)], axis=1)


def _composite(rel_hi) -> float:
    v = pd.Series(list(rel_hi), dtype=float)
    return float(v.max()) if len(v) and v.notna().all() else np.nan


def _h1_overall(full: pd.DataFrame, lt: pd.DataFrame, model: str) -> dict:
    per = full[(full["model"] == model) & (full["target"] != POOLED)]
    verdict = _overall(per["verdict"])
    out = {"model": model, "role": "decides" if model == H1_DECIDES else "alongside",
           "verdict": verdict, "composite": _composite(per["rel_hi"])}
    g = lt[(lt["model"] == model) & (lt["target"] != POOLED)] if len(lt) else lt
    if g.empty:
        return {**out, "loo_min": np.nan, "loo_max": np.nan, "drop_at_min": None,
                "drop_at_max": None, "fragile_range": None, "fragile_differs": None,
                "fragile": None, "flips": [], "subsets": pd.DataFrame()}
    sub = pd.DataFrame([{"dropped": d, "composite": _composite(x["rel_hi"]),
                         "verdict": _overall(x["verdict"])} for d, x in g.groupby("dropped")])
    rng = _range(sub["composite"], H1_BAR)
    flips = sub.loc[sub["verdict"] != verdict, "dropped"].tolist()
    lo, hi, at_lo, at_hi = _extremes(sub, "composite")
    return {**out, "loo_min": lo, "loo_max": hi, "drop_at_min": at_lo, "drop_at_max": at_hi,
            "fragile_range": rng, "fragile_differs": bool(flips),
            "fragile": None if rng is None else bool(rng or flips), "flips": flips,
            "subsets": sub}


def _h1_one(s: pd.DataFrame, models: list[str], loo: bool, g1: str) -> dict:
    full = _h1_compare(s, models)
    present = sorted(set(s["origin"]))
    lt = (_loo_tables(lambda sub: _h1_compare(sub, models), s, present) if loo
          else pd.DataFrame(columns=["dropped"]))
    table = _tag(_h1_fragility(full, lt), s, g1=g1, months="winter", horizons="3",
                 metric="mase")
    by_model = {m: _h1_overall(full, lt, m) for m in models}
    d = by_model[H1_DECIDES]
    overall = {"verdict": d["verdict"], "fragile": d["fragile"], "flips": d["flips"],
               "decides": H1_DECIDES, "by_model": by_model, "caveat": S9_CAVEAT,
               "loo_origins": present if loo and len(present) > 1 else [],
               "n_all_zero": {m: _all_zero(s[s["model"] == m]) for m in (H1_REF, *models)}}
    return {"table": table, "overall": overall, "loo": lt}


def h1(scored: pd.DataFrame, origins, *, loo: bool = True, alongside: bool = True) -> dict:
    s = _winter_h3(_g1_scope(scored, "H1"), origins)
    _require(s, level="provider", mode="asof")
    for m in (H1_REF, H1_DECIDES, *([H1_ALONGSIDE] if alongside else [])):
        if not (s["model"] == m).any():
            raise ValueError(f"H1 needs {m} rows at winter h3"
                             + (" (reported alongside; alongside=False omits it)"
                                if m == H1_ALONGSIDE else ""))
    models = [m for m in (H1_DECIDES, H1_ALONGSIDE) if (s["model"] == m).any()]
    other = set(s["model"]) - {H1_REF, *models}
    if other:
        raise ValueError(f"H1 rows hold other models: {sorted(other)}")
    res = {name: _h1_one(v, models, loo, name) for name, v in variants(s)}
    return {**res[AS_ISSUED], "failed_dropped": res.get(FAILED_DROPPED)}


# ---- coverage tables (§7.4, §7.5) --------------------------------------------------------
def _coverage(rows: pd.DataFrame, fold, specs, g1: str | None = None,
              series_col: str = "series") -> list[pd.DataFrame]:
    """Two-way tables sharing one set of draws (§7.4): ``specs`` = [(stat, cells), ...]. The
    units are the origin units present in ``rows``, the series the series present."""
    uo = stats.origin_units(_ts_index(rows["origin"].unique()), fold)
    draws = stats.make_draws(rows[series_col], uo.values())
    extra = {"g1": g1} if g1 else {}
    return [_tag(stats.two_way(rows, list(cells), stat, draws, uo, series_col), rows, cells,
                 stat=stat, months="all", **extra) for stat, cells in specs]


def coverage_by_horizon(rows: pd.DataFrame, counted, fold, stat: str = "cov90",
                        cells=("horizon",)) -> pd.DataFrame:
    return _coverage(_restrict(rows, counted, fold), fold, [(stat, cells)])[0]


def origin_year_cells(rows: pd.DataFrame, stat: str = "cov90") -> pd.DataFrame:
    """``met`` is the 0.87-0.93 criterion, for cov90 only."""
    c = stage_d.coverage_cells(rows if "model" in rows.columns else rows.assign(model=""))
    met = c["cov90"].between(*CELL_BAND) if stat == "cov90" else pd.Series(pd.NA, index=c.index)
    c = c.assign(stat=stat, value=c[stat], met=met)
    cols = ["model", "oyear", "horizon", "region", "stat", "value", "n", "origins", "assessed",
            "met"]
    return _tag(c[cols].reset_index(drop=True), rows, ["model"], months="all")


def _stack(tables: list[pd.DataFrame]) -> pd.DataFrame:
    return pd.concat(tables, ignore_index=True)


def _failed_by_horizon(rows: pd.DataFrame) -> pd.DataFrame:
    f = rows.assign(failed=rows["failed"].astype(bool)) if "failed" in rows.columns \
        else rows.assign(failed=False)
    return f.groupby("horizon").agg(n_rows=("failed", "size"), n_failed=("failed", "sum")) \
        .reset_index()


# ---- primary (§7.5) ----------------------------------------------------------------------
def primary(rows: pd.DataFrame, counted, fold) -> dict:
    """The as-issued CONF19 cov90 table and verdict decide; everything else is alongside,
    per G1 variant: cov90 and cov50 by horizon and by target x horizon on one set of draws,
    the origin-year cells, the CONF21 tables (when ``fold``) and the failed counts."""
    _require(rows, level="provider", mode="asof", model=PRIMARY_MODEL)
    _need_g1(rows, "primary")
    alongside = {}
    for name, v in variants(rows):
        r19 = _restrict(v, counted, {})
        t90, t50, p90, p50 = _coverage(r19, {}, [("cov90", ["horizon"]), ("cov50", ["horizon"]),
                                                 ("cov90", ["target", "horizon"]),
                                                 ("cov50", ["target", "horizon"])], name)
        item = {"table": t90, "verdict": stats.verdict_primary(t90),
                "by_horizon": _stack([t90, t50]), "per_target": _stack([p90, p50]),
                "cells": origin_year_cells(r19).assign(g1=name),
                "failed": _failed_by_horizon(_restrict(rows, counted, {})) if name == AS_ISSUED
                else None}
        if fold:
            r21 = _restrict(v, counted, fold)
            item["conf21"] = _stack(_coverage(r21, fold, [("cov90", ["horizon"]),
                                                          ("cov50", ["horizon"])], name))
            item["cells_conf21"] = origin_year_cells(r21).assign(g1=name)
        alongside[name] = item
    return {"table": alongside[AS_ISSUED]["table"], "verdict": alongside[AS_ISSUED]["verdict"],
            "alongside": alongside}


# ---- H2 (§7.5) ---------------------------------------------------------------------------
def _h2_item(rows: pd.DataFrame, counted, fold, verdict_fn, g1: str) -> dict:
    r19 = _restrict(rows, counted, {})
    if r19.empty:
        item = {"table": None, "verdict": verdict_fn(None), "cells": None}
    else:
        t = _coverage(r19, {}, [("cov90", ["horizon"])], g1)[0]
        item = {"table": t, "verdict": verdict_fn(t), "cells": origin_year_cells(r19).assign(g1=g1)}
    item["conf21"] = None
    if fold:
        r21 = _restrict(rows, counted, fold)
        if len(r21):
            t21 = _coverage(r21, fold, [("cov90", ["horizon"])], g1)[0]
            item["conf21"] = {"table": t21, "verdict": verdict_fn(t21),
                              "cells": origin_year_cells(r21).assign(g1=g1)}
    return item


def h2_m1(rows: pd.DataFrame, counted, fold) -> dict:
    """Point estimates decide (confirmed / refuted / neither, directions named); the two-way
    intervals give the fragility label. CONF21 alongside, with its own table and verdict."""
    _require(rows, level="provider", mode="asof", model=NAMES["m1"])
    res = {name: _h2_item(v, counted, fold, stats.verdict_h2_m1, name)
           for name, v in variants(rows)}
    return {**res[AS_ISSUED], "failed_dropped": res.get(FAILED_DROPPED), "caveat": S9_CAVEAT,
            "n_all_zero": _all_zero(_restrict(rows, counted, fold))}


def _fit_status(fits: pd.DataFrame) -> pd.DataFrame:
    """Per origin: attempts, and whether any attempt succeeded."""
    f = fits.assign(origin=pd.to_datetime(fits["origin"]), failed=fits["failed"].astype(bool))
    g = f.groupby("origin")
    return pd.DataFrame({"attempts": g.size(), "ok": ~g["failed"].min().astype(bool)})


def _m2_diagnostics(fits: pd.DataFrame, counted) -> pd.DataFrame:
    """Origin-year medians of the counted origins' successful fits, set against the DEV
    trend table (plan §6). Each part carries its own split and origin set: the counted
    origins are CONF in the run and DEV in the dry run, and the trend table is the 69 DEV
    origins, so the writer never puts the two in one file."""
    f = fits.assign(origin=pd.to_datetime(fits["origin"]), failed=fits["failed"].astype(bool))
    used = f[~f["failed"] & f["origin"].isin(_ts_index(counted))]
    used = used.sort_values(["origin", "attempt"]).drop_duplicates("origin", keep="last")
    conf = used.assign(oyear=used["origin"].dt.year).groupby("oyear").agg(
        fits=("origin", "size"), rhat_max_median=("rhat_max", "median"),
        ess_bulk_min_median=("ess_bulk_min", "median"),
        divergences_median=("divergences", "median"),
        divergences_total=("divergences", "sum")).reset_index()
    return pd.concat([M2_DEV_TREND.assign(split="dev", origin_set="DEV"),
                      conf.assign(split=_split(counted), origin_set=_origin_set(counted))],
                     ignore_index=True)[["split", "origin_set", "oyear", "fits",
                                         "rhat_max_median", "ess_bulk_min_median",
                                         "divergences_median", "divergences_total"]]


def h2_m2(rows: pd.DataFrame, counted, fold, fits: pd.DataFrame) -> dict:
    """An origin failed if every attempt at it failed; its rows must be absent, and every
    other counted or folded origin must have rows. The coverage table is still shown when the
    clause is not evaluable; the verdict is then "not evaluable"."""
    _require(rows, level="icb", mode="asof", model=NAMES["m2"])
    status = _fit_status(fits)
    counted_ix, full_ix = _ts_index(counted), _ts_index([*counted, *(fold or {})])
    missing = full_ix.difference(status.index)
    if len(missing):
        raise ValueError(f"no M2 fit recorded at {[f'{o:%Y-%m}' for o in missing]}")
    failed = status.index[~status["ok"].to_numpy()]
    with_rows = _ts_index(rows["origin"].unique())
    bad = with_rows.intersection(failed)
    absent = full_ix.difference(failed).difference(with_rows)
    if len(bad) or len(absent):
        raise ValueError(f"M2 rows disagree with the fits: rows at failed origins "
                         f"{[f'{o:%Y-%m}' for o in bad]}, no rows at fitted origins "
                         f"{[f'{o:%Y-%m}' for o in absent]}")
    n_failed = len(failed.intersection(counted_ix))
    limit = _fail_limit(len(counted_ix))
    evaluable = n_failed < limit

    def verdict_fn(t):
        return stats.verdict_h2_m2(t, evaluable)

    res = {name: _h2_item(v, counted, fold, verdict_fn, name) for name, v in variants(rows)}
    f = fits.sort_values(["origin", "attempt"]).reset_index(drop=True)
    return {**res[AS_ISSUED], "failed_dropped": res.get(FAILED_DROPPED),
            "evaluable": evaluable, "fail_limit": limit,
            "failed_units": [f"{o:%Y-%m}" for o in failed.intersection(counted_ix)],
            "n_failed_counted": n_failed, "n_counted": len(counted_ix),
            "n_failed_full": len(failed.intersection(full_ix)), "n_full": len(full_ix),
            "fits": f, "diagnostics": _m2_diagnostics(fits, counted), "phase": H2_M2_PHASE,
            "limitation": TEXT_A, "limitation_notes": TEXT_A_NOTES, "caveat": S9_CAVEAT,
            "n_all_zero": _all_zero(_restrict(rows, counted, fold))}


# ---- descriptive headline (§7.6) ---------------------------------------------------------
def _common(a: pd.DataFrame, b: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    keys = a[list(K5)].merge(b[list(K5)], on=list(K5))
    return a.merge(keys, on=list(K5)), b.merge(keys, on=list(K5))


def _pp(t: pd.DataFrame, prefix: str, nominal: float | None) -> dict:
    """point, lo and hi in percentage points (minus the nominal level for a coverage)."""
    off = 0.0 if nominal is None else nominal
    return {f"{prefix}_{c}_pp": 100 * (t[c].to_numpy(float) - off) for c in ("point", "lo", "hi")}


def _gap_table(raw: pd.DataFrame, pooled: pd.DataFrame, cells: list[str], draws,
               uo) -> pd.DataFrame:
    tr = stats.two_way(raw, cells, "cov90", draws, uo, partial=True)
    tp = stats.two_way(pooled, cells, "cov90", draws, uo, partial=True)
    td = stats.two_way_diff(raw, pooled, cells, "cov90", draws, uo, partial=True)
    keep = ["point", "lo", "hi", "lo_within", "hi_within", "n_rows", "n_series", "n_units",
            "zero_den", "degenerate"]
    t = tr[cells + keep].merge(tp[cells + keep], on=cells, suffixes=("_raw", "_pooled"),
                               how="outer")
    d = td[cells + ["point", "lo", "hi", "lo_within", "hi_within", "zero_den", "degenerate"]]
    t = t.merge(d.rename(columns={c: f"{c}_diff" for c in d.columns if c not in cells}),
                on=cells, how="outer")
    raw_t, pool_t, diff_t = (t[[f"{c}_{s}" for c in ("point", "lo", "hi")]].set_axis(
        ["point", "lo", "hi"], axis=1) for s in ("raw", "pooled", "diff"))
    return t.assign(**_pp(raw_t, "raw_gap", NOMINAL), **_pp(pool_t, "pooled_gap", NOMINAL),
                    **_pp(diff_t, "diff", None))


def headline(raw: Mapping[str, pd.DataFrame], pooled: Mapping[str, pd.DataFrame], counted, fold,
             icb_raw_ets: pd.DataFrame | None = None) -> dict:
    """Per G1 variant: one set of draws for the whole table (every model, raw and pooled),
    built from the common rows of each model; gaps in pp, pooled - raw paired. CONF19 only
    (``fold`` is not used: §7.6 names CONF19). The ICB raw-ETS table has its own draws."""
    if set(raw) != set(pooled):
        raise ValueError(f"raw and pooled models differ: {sorted(set(raw) ^ set(pooled))}")
    for m in raw:
        _require(raw[m], level="provider", mode="asof", model=m)
        _require(pooled[m], level="provider", mode="asof", model=f"{m}+pooled")
        _need_g1(raw[m], f"headline {m}")
        _need_g1(pooled[m], f"headline {m}+pooled")
    if icb_raw_ets is not None:
        _require(icb_raw_ets, level="icb", mode="asof", model=NAMES["b1"])
        _need_g1(icb_raw_ets, "headline ICB raw ETS")
    out = {}
    for name in _variant_names([*raw.values(), *pooled.values()]):
        common = {m: _common(_restrict(_variant(raw[m], name), counted, {}),
                             _restrict(_variant(pooled[m], name), counted, {})) for m in raw}
        both = pd.concat([f[["series", "origin"]] for pair in common.values() for f in pair],
                         ignore_index=True)
        uo = stats.origin_units(_ts_index(both["origin"].unique()), {})
        draws = stats.make_draws(both["series"], uo.values())
        by_h, by_oy = [], []
        for m, (r, p) in common.items():
            r, p = r.assign(oyear=r["origin"].dt.year), p.assign(oyear=p["origin"].dt.year)
            by_h.append(_gap_table(r, p, ["horizon"], draws, uo).assign(model=m))
            by_oy.append(_gap_table(r, p, ["oyear", "horizon"], draws, uo).assign(model=m))
        rows_all = pd.concat([r for r, _ in common.values()], ignore_index=True)
        tag = {"g1": name, "stat": "cov90", "months": "all"}
        out[name] = {"by_horizon": _tag(_stack(by_h), rows_all, ["model"], **tag),
                     "by_origin_year": _tag(_stack(by_oy), rows_all, ["model"], **tag)}
    res = {**out[AS_ISSUED], "failed_dropped": out.get(FAILED_DROPPED), "icb_raw_ets": None}
    if icb_raw_ets is not None:
        icb = {}
        for name, v in variants(icb_raw_ets):
            r = _restrict(v, counted, {})
            r = r.assign(oyear=r["origin"].dt.year)
            h, oy = _coverage(r, {}, [("cov90", ["horizon"]), ("cov90", ["oyear", "horizon"])],
                              name)
            icb[name] = {"by_horizon": h, "by_origin_year": oy}
        res["icb_raw_ets"] = icb
    return res


# ---- H3 (§7.7) ---------------------------------------------------------------------------
H3_KINDS = ("base", "mint")


def _h3_table(frames: dict) -> pd.DataFrame:
    """stage_f.h3_table, with each base x level comparison repeated through stats.compare
    for its pair counts (and checked to give the same rel), England's interval n/a and the
    region caution."""
    t = stage_f.h3_table(frames)
    rows = []
    for b in stage_f.BASE_MODELS:
        base, mint = frames[(b, "base")], frames[(b, "mint")]
        for lv in stage_f.LEVELS:
            c = stats.compare(base[base["level"] == lv], mint[mint["level"] == lv], "wis")
            rows.append({"base": stage_f.LABELS[b], "level": lv, "rel_wrapper": c["rel"],
                         **{k: c[k] for k in ("n_pairs", "n_ref", "n_tested", "unpaired_ref",
                                              "unpaired_tested", "evaluable")}})
    t = t.merge(pd.DataFrame(rows), on=["base", "level"], validate="one_to_one")
    rel = pd.to_numeric(t["rel"], errors="coerce").to_numpy(float)
    if not np.array_equal(rel, t["rel_wrapper"].to_numpy(float), equal_nan=True):
        raise RuntimeError("stage_f.h3_table and stats.compare disagree on rel")
    t = t.drop(columns="rel_wrapper")
    eng, reg = (t["level"] == "england").to_numpy(), (t["level"] == "region").to_numpy()
    t["rel_lo"] = pd.to_numeric(t["rel_lo"], errors="coerce").mask(eng)
    t["rel_hi"] = pd.to_numeric(t["rel_hi"], errors="coerce").mask(eng)
    t["note"] = np.where(eng, ENGLAND_NA,
                         np.where(reg, [f"caution: bootstrap over {n} series"
                                        for n in t["n_series"]], ""))
    return t


def _h3_verdicts(t: pd.DataFrame) -> pd.DataFrame:
    """One row per base: the verdict and its two clause statistics."""
    lv = t.set_index(["base", "level"])
    bases = t["base"].drop_duplicates().tolist()
    return pd.DataFrame({"base": bases,
                         "H3": [lv.loc[(b, "icb"), "H3"] for b in bases],
                         "icb_rel_hi": [lv.loc[(b, "icb"), "rel_hi"] for b in bases],
                         "provider_rel": [lv.loc[(b, "provider"), "rel"] for b in bases]})


def _h3_one(frames: dict, loo: bool, g1: str) -> dict:
    full = _h3_table(frames)
    fv = _h3_verdicts(full)
    lt = _loo_frames(lambda sub: _h3_verdicts(stage_f.h3_table(sub)), frames, loo)
    rows = []
    for _, r in fv.iterrows():
        g = lt[lt["base"] == r["base"]] if len(lt) else lt
        flips = g.loc[g["H3"] != r["H3"], "dropped"].tolist() if len(g) else []
        icb = _extremes(g, "icb_rel_hi")
        prov = _extremes(g, "provider_rel")
        rows.append({**r.to_dict(),
                     "fragile": None if g.empty else bool(g["H3"].nunique() > 1 or flips),
                     "flips": flips, "loo_n": len(g),
                     "loo_icb_rel_hi_min": icb[0], "loo_icb_rel_hi_max": icb[1],
                     "icb_straddles_0": _range(g.get("icb_rel_hi", []), 0.0),
                     "loo_provider_rel_min": prov[0], "loo_provider_rel_max": prov[1],
                     "provider_straddles_2pct": _range(g.get("provider_rel", []),
                                                       H3_PROVIDER_TOL)})
    verdicts = pd.DataFrame(rows)
    rows_all = pd.concat(list(frames.values()), ignore_index=True)
    tag = {"g1": g1, "months": "winter", "horizons": "3", "metric": "wis"}
    head = verdicts.set_index("base").loc[stage_f.LABELS["m1_v3_raw"]]
    n_regions = int(full.loc[full["level"] == "region", "n_series"].max())
    return {"table": _tag(full, rows_all, ["level", "model"], **tag),
            "verdicts": _tag(verdicts, rows_all, ["level", "model"], **tag),
            "headline": {"base": stage_f.LABELS["m1_v3_raw"], "verdict": head["H3"],
                         "fragile": _flag(head["fragile"]), "flips": head["flips"]},
            "loo": lt, "notes": [R2_NOTE, f"England: {ENGLAND_NA}.",
                                 f"Region: caution, bootstrap over {n_regions} series."]}


def h3(scored: Mapping[tuple[str, str], pd.DataFrame], origins, *, loo: bool = True) -> dict:
    keys = [(b, k) for b in stage_f.BASE_MODELS for k in H3_KINDS]
    missing = [k for k in keys if k not in scored]
    if missing:
        raise ValueError(f"H3 needs every base and kind; missing {missing}")
    for k in keys:
        _need_g1(scored[k], f"H3 {'/'.join(k)}")
    res = {}
    for name in _variant_names(scored[k] for k in keys):
        frames = {k: _winter_h3(_variant(scored[k], name), origins) for k in keys}
        for k, f in frames.items():
            _require(f, mode="asof")
            _check_levels(f, "/".join(k))
        res[name] = _h3_one(frames, loo, name)
    return {**res[AS_ISSUED], "failed_dropped": res.get(FAILED_DROPPED)}


# ---- H4 and H4-original (§7.8, §7.9) -----------------------------------------------------
def _h4_frames(scored, origins, name, keys) -> dict:
    frames = {}
    for m, mode in keys:
        f = _winter_h3(_variant(scored[(m, mode)], name), origins)
        _require(f, level="provider", mode=mode, model=NAMES[m])
        stats._one_slice(f, f"{m}/{mode}", list(K5))
        frames[(m, mode)] = f
    return frames


def _h4_clause(frames: dict, models: list[str]) -> pd.DataFrame:
    rows = []
    for m in models:
        a, f = frames[(m, "asof")], frames[(m, "final")]
        for t in TARGET_ORDER:
            r = stats.compare(a[a["target"] == t], f[f["target"] == t], "wis")
            differs = (bool(r["rel_lo"] > H4_TOL or r["rel_hi"] < -H4_TOL) if r["evaluable"]
                       else None)
            rows.append({"key": m, "model": NAMES[m], "target": t,
                         "role": "decides" if m in H4_MODELS else "alongside", **r,
                         "differs": differs})
    return pd.DataFrame(rows)


def _h4_ranking(frames: dict, keys: list[str]) -> tuple[pd.DataFrame, dict]:
    """Per target, on the rows every model in ``keys`` scored in both modes: models ordered by
    the mean over series of per-series mean WIS; the ranking holds if both modes agree."""
    k5 = list(K5)
    rows, holds = [], {}
    for t in TARGET_ORDER:
        common = None
        for m in keys:
            for mode in H4_MODES:
                f = frames[(m, mode)]
                k = f.loc[((f["target"] == t) & f["wis"].notna()).to_numpy(), k5]
                common = k if common is None else common.merge(k, on=k5)
        if common is None or common.empty:
            holds[t] = None
            continue
        orders = {}
        for mode in H4_MODES:
            val = {m: frames[(m, mode)].merge(common, on=k5).groupby("series")["wis"].mean().mean()
                   for m in keys}
            orders[mode] = sorted(keys, key=lambda m: (val[m], keys.index(m)))
            rows += [{"target": t, "mode": mode, "key": m, "model": NAMES[m],
                      "mean_wis": val[m], "rank": orders[mode].index(m) + 1,
                      "n_rows": len(common), "n_series": common["series"].nunique()}
                     for m in keys]
        holds[t] = orders["asof"] == orders["final"]
    table = pd.DataFrame(rows)
    if len(table):
        table["holds"] = table["target"].map(holds)
    return table, holds


def _h4_verdict(clause: pd.DataFrame, holds: dict) -> dict:
    dec = clause[clause["role"] == "decides"]
    refuting = [f"{m} {t}" for m, t, d in zip(dec["model"], dec["target"], dec["differs"])
                if _true(d)]
    refuting += [f"ranking {t}" for t, h in holds.items() if h is False]
    if refuting:
        verdict = "refuted"
    elif dec["differs"].isna().any() or any(h is None for h in holds.values()):
        verdict = "not evaluable"
    else:
        verdict = "confirmed"
    return {"verdict": verdict, "refuting": refuting}


def _h4_loo_row(frames: dict, models: list[str]) -> pd.DataFrame:
    clause = _h4_clause(frames, models)
    _, holds = _h4_ranking(frames, list(H4_MODELS))
    c = clause[["key", "target", "rel", "rel_lo", "rel_hi", "differs"]].assign(item="clause")
    r = pd.DataFrame({"item": "ranking", "target": list(holds), "holds": list(holds.values())})
    v = pd.DataFrame({"item": ["verdict"], "verdict": [_h4_verdict(clause, holds)["verdict"]]})
    return pd.concat([c, r, v], ignore_index=True)


def _h4_one(frames: dict, models: list[str], loo: bool, g1: str) -> dict:
    clause = _h4_clause(frames, models)
    ranking, holds = _h4_ranking(frames, list(H4_MODELS))
    verdict = _h4_verdict(clause, holds)
    lt = _loo_frames(lambda sub: _h4_loo_row(sub, models), frames, loo)
    has = len(lt) > 0
    frag = []
    for _, r in clause.iterrows():
        g = lt[(lt["item"] == "clause") & (lt["key"] == r["key"]) & (lt["target"] == r["target"])] \
            if has else lt
        lo_f, hi_f = _range(g.get("rel_lo", []), H4_TOL), _range(g.get("rel_hi", []), -H4_TOL)
        lo, hi = _extremes(g, "rel_lo"), _extremes(g, "rel_hi")
        frag.append({"loo_rel_lo_min": lo[0], "loo_rel_lo_max": lo[1], "loo_rel_hi_min": hi[0],
                     "loo_rel_hi_max": hi[1],
                     "fragile": None if lo_f is None or hi_f is None else bool(lo_f or hi_f)})
    clause = pd.concat([clause, pd.DataFrame(frag)], axis=1)
    rank_frag = {}
    for t, h in holds.items():
        g = lt[(lt["item"] == "ranking") & (lt["target"] == t)] if has else lt
        rank_frag[t] = None if g.empty or h is None else bool((g["holds"] != h).any())
    if len(ranking):
        ranking["fragile"] = ranking["target"].map(rank_frag)
    gv = lt[lt["item"] == "verdict"] if has else lt
    flips = gv.loc[gv["verdict"] != verdict["verdict"], "dropped"].tolist() if has else []
    elements = [{"element": e, "fragile": _flag(
        rank_frag.get(e.split(" ", 1)[1]) if e.startswith("ranking ") else
        clause.loc[(clause["model"] + " " + clause["target"]) == e, "fragile"].iloc[0])}
        for e in verdict["refuting"]]
    rows_all = pd.concat(list(frames.values()), ignore_index=True)
    tag = {"g1": g1, "months": "winter", "horizons": "3", "metric": "wis"}
    alongside = (_h4_ranking(frames, models)[0] if len(models) > len(H4_MODELS)
                 else pd.DataFrame())
    return {"table": _tag(clause, rows_all, ["mode", "model"], **tag),
            "ranking": _tag(ranking, rows_all, ["mode", "model"], **tag),
            "ranking_alongside": (_tag(alongside, rows_all, ["mode", "model"], **tag)
                                  if len(alongside) else alongside),
            "verdict": {**verdict, "fragile": None if gv.empty else
                        bool(gv["verdict"].nunique() > 1 or flips), "flips": flips,
                        "elements": elements, "ranking_holds": holds, "note": H4_NOTE},
            "loo": lt,
            "n_failed": {f"{m}/{mode}": _n_failed(f) for (m, mode), f in frames.items()}}


def _h4_keys(scored, alongside: bool) -> list[str]:
    """H4's four models in both modes, then M1 v3 raw (alongside): required in both modes
    unless ``alongside`` is False, never in one mode only. G1 bases must be marked."""
    missing = [(m, mode) for m in H4_MODELS for mode in H4_MODES if (m, mode) not in scored]
    if missing:
        raise ValueError(f"missing scored frames {missing}")
    v3 = [("m1_v3_raw", mode) for mode in H4_MODES]
    have = [k in scored for k in v3]
    if not all(have) and (alongside or any(have)):
        raise ValueError(f"missing scored frames {[k for k, h in zip(v3, have) if not h]}: M1 "
                         "v3 raw is reported alongside, in both modes (alongside=False omits "
                         "it in both)")
    models = [*H4_MODELS, *(["m1_v3_raw"] if all(have) else [])]
    for m in models:
        for mode in H4_MODES:
            _need_g1(scored[(m, mode)], f"H4 {m}/{mode}")
    return models


def h4(scored: Mapping[tuple[str, str], pd.DataFrame], origins, *, loo: bool = True,
       alongside: bool = True) -> dict:
    models = _h4_keys(scored, alongside)
    keys = [(m, mode) for m in models for mode in H4_MODES]
    res = {name: _h4_one(_h4_frames(scored, origins, name, keys), models, loo, name)
           for name in _variant_names(scored[k] for k in keys)}
    return {**res[AS_ISSUED], "failed_dropped": res.get(FAILED_DROPPED)}


def h4_original(scored: Mapping[tuple[str, str], pd.DataFrame], origins, h4_result: dict, *,
                alongside: bool = True) -> dict:
    """Per mode, rel of B0 -> model on that mode's own pairs, with every stats.compare count
    suffixed by the mode; holds if any |Δpp| > 5 among B1, B2 and default M1 (M1 v3 raw
    alongside) or H4's ranking changes in the same variant."""
    tested = [m for m in _h4_keys(scored, alongside) if m != "b0"]
    keys = [(m, mode) for m in ("b0", *tested) for mode in H4_MODES]
    out = {}
    for name in _variant_names(scored[k] for k in keys):
        frames = _h4_frames(scored, origins, name, keys)
        rows = []
        for m in tested:
            for t in TARGET_ORDER:
                row = {"key": m, "model": NAMES[m], "target": t,
                       "role": "decides" if m in H4_MODELS else "alongside"}
                for mode in H4_MODES:
                    b0, f = frames[("b0", mode)], frames[(m, mode)]
                    r = stats.compare(b0[b0["target"] == t], f[f["target"] == t], "wis")
                    row.update({f"{k}_{mode}": v for k, v in r.items()})
                row["delta_pp"] = 100 * (row["rel_final"] - row["rel_asof"])
                row["exceeds"] = (None if pd.isna(row["delta_pp"])
                                  else bool(abs(row["delta_pp"]) > H4_ORIGINAL_PP))
                rows.append(row)
        table = pd.DataFrame(rows)
        h4v = h4_result if name == AS_ISSUED else h4_result.get(FAILED_DROPPED)
        if h4v is None:
            raise ValueError(f"h4_result has no {name} variant")
        changes = [t for t, h in h4v["verdict"]["ranking_holds"].items() if h is False]
        dec = table[table["role"] == "decides"]
        exceeds = [f"{m} {t}" for m, t, e in zip(dec["model"], dec["target"], dec["exceeds"])
                   if _true(e)]
        rows_all = pd.concat(list(frames.values()), ignore_index=True)
        out[name] = {"table": _tag(table, rows_all, ["mode", "model"], g1=name, months="winter",
                                   horizons="3", metric="wis"),
                     "verdict": {"verdict": "holds" if exceeds or changes else "does not hold",
                                 "exceeds": exceeds, "ranking_changes": changes}}
    return {**out[AS_ISSUED], "failed_dropped": out.get(FAILED_DROPPED)}


# ---- H4b (§7.10) -------------------------------------------------------------------------
def _provider_targets(sliced: pd.DataFrame) -> pd.DataFrame:
    """Target values per (period, org_code): the sum of the parts, NaN if a part is missing
    (as ``asof.targets_long``)."""
    wide = sliced.pivot_table(index=["period", "org_code"], columns="metric", values="value",
                              aggfunc="first")
    out = {t: (wide[list(parts)].sum(axis=1, min_count=len(parts))
               if all(p in wide.columns for p in parts) else pd.Series(np.nan, index=wide.index))
           for t, parts in TARGETS.items()}
    return pd.DataFrame(out, index=wide.index)


def _in_periods(frame: pd.DataFrame, lo, hi) -> pd.DataFrame:
    p = frame.index.get_level_values("period")
    return frame[(p >= lo) & (p <= hi)]


def h4b_components(vintages: pd.DataFrame, origins, window: int = 12, *,
                   end=RUN_END) -> pd.DataFrame:
    """E_o is the last period with a provider version available at o's as-of date, never
    beyond M-1 (``asof.load_asof``'s last_period). V is summed over provider-months in both
    slices, L over final-only, Wd over as-of-only; the lost originals are the final
    provider-months in periods E_o < p <= M-1. Bounded by ``end`` (E, never later than
    RUN_END; §2.4): an origin beyond it raises, and rows of periods after the last origin's
    M-1 are cut before any value is read, which changes nothing in the output."""
    o_ix = _ts_index(origins)
    lim = min(ts(end), ts(RUN_END))
    if o_ix.empty:
        raise ValueError("H4b needs at least one origin")
    if o_ix.max() > lim:
        raise ValueError(f"origins run to {o_ix.max():%Y-%m}, beyond E = {lim:%Y-%m} (§2.4)")
    keep = (~vintages["is_total"].astype(bool) & vintages["metric"].isin(METRICS_NEEDED)
            & (pd.to_datetime(vintages["period"]) <= last_period(o_ix.max().date())))
    v = vintages[keep.to_numpy()]
    v = v.assign(period=pd.to_datetime(v["period"]), snapshot=pd.to_datetime(v["snapshot"]))
    v = v.sort_values("snapshot", kind="stable")
    keys = ["period", "org_code", "metric"]
    final = _provider_targets(v.drop_duplicates(keys, keep="last"))
    first_seen = v.groupby("period")["snapshot"].min()
    rows = []
    for o in o_ix:
        m1, cut = last_period(o.date()), as_of_date(o.date())
        avail = first_seen[(first_seen.index <= m1) & (first_seen <= cut)]
        if avail.empty:
            raise ValueError(f"no provider data at origin {o:%Y-%m}")
        e = avail.index.max()
        start = e - pd.DateOffset(months=window - 1)
        w = v[(v["period"] >= start) & (v["period"] <= e) & (v["snapshot"] <= cut)]
        asof = _provider_targets(w.drop_duplicates(keys, keep="last"))
        fin = _in_periods(final, start, e)
        lost = _in_periods(final, e + pd.DateOffset(months=1), m1)
        for t in TARGET_ORDER:
            a, b = asof[t].dropna(), fin[t].dropna()
            both, late = a.index.intersection(b.index), b.index.difference(a.index)
            gone = a.index.difference(b.index)
            lo = lost[t].dropna()
            rows.append({"origin": o, "target": t, "last_period": m1, "E_o": e,
                         "window_start": start, "truncated": bool(e < m1),
                         "n_both": len(both), "n_late": len(late), "n_withdrawn": len(gone),
                         "V": float((b.loc[both] - a.loc[both]).sum()),
                         "L": float(b.loc[late].sum()), "Wd": float(a.loc[gone].sum()),
                         "sum_asof": float(a.sum()),
                         "sum_final": float(b.sum()), "lost_originals_n": len(lo),
                         "lost_originals_final": float(lo.sum())})
    return pd.DataFrame(rows)


def _h4b_components(components: pd.DataFrame, *origin_sets) -> tuple:
    """The components with ``late_larger``, and each origin set as an index; an origin
    without components raises."""
    c = components.assign(origin=pd.to_datetime(components["origin"]),
                          late_larger=components["L"].abs() > components["V"].abs())
    ixs = [_ts_index(o) for o in origin_sets]
    missing = _ts_index([o for ix in ixs for o in ix]).difference(c["origin"].unique())
    if len(missing):
        raise ValueError(f"no H4b components at {[f'{o:%Y-%m}' for o in missing]}")
    return (c, *ixs)


def _h4b_per_origin(c: pd.DataFrame, ix: pd.DatetimeIndex) -> tuple[pd.DataFrame, pd.DataFrame]:
    per_origin = _front(c[c["origin"].isin(ix)].reset_index(drop=True),
                        {"split": _split(ix), "origin_set": _origin_set(ix)})
    return per_origin, per_origin[per_origin["lost_originals_n"] > 0].reset_index(drop=True)


def _h4b_table(c: pd.DataFrame, ix: pd.DatetimeIndex) -> pd.DataFrame:
    """One origin set: per target, the late_larger count against more than half of it."""
    need = _more_than_half(len(ix))
    rows = []
    for t in TARGET_ORDER:
        k = int(c.loc[(c["target"] == t).to_numpy() & c["origin"].isin(ix).to_numpy(),
                      "late_larger"].sum())
        rows.append({"target": t, "late_larger": k, "need": need,
                     "verdict": "confirmed" if k >= need else "not confirmed"})
    return _front(pd.DataFrame(rows), slice_tags(ix)).assign(label=H4B_LABEL)


def h4b(components: pd.DataFrame, counted, full) -> dict:
    """late_larger = |L| > |V| per origin; per target confirmed if it holds at more than half
    of ``counted`` (19: at least 10). Overall confirmed only if every target is (19-origin
    version). The ``full`` version (21: at least 11) is its own table under "conf21" when it
    differs from ``counted`` (§7.1: CONF19 and CONF21 never share a table); its overall
    verdict is ``verdict_full``."""
    c, counted_ix, full_ix = _h4b_components(components, counted, full)

    def overall(t):
        return "confirmed" if (t["verdict"] == "confirmed").all() else "not confirmed"

    table = _h4b_table(c, counted_ix)
    per_origin, lost = _h4b_per_origin(c, full_ix)
    out = {"table": table,
           "overall": {"verdict": overall(table), "verdict_full": overall(table),
                       "per_target": dict(zip(table["target"], table["verdict"])),
                       "label": H4B_LABEL},
           "per_origin": per_origin, "lost_originals": lost}
    if not full_ix.equals(counted_ix):
        t21 = _h4b_table(c, full_ix)
        out["conf21"] = {"table": t21}
        out["overall"]["verdict_full"] = overall(t21)
        out["overall"]["per_target_full"] = dict(zip(t21["target"], t21["verdict"]))
    return out


H4B_DEV_NOTE = ("H4b's DEV side (§7.10): every DEV origin given, shown side by side with CONF. "
                "Descriptive: H4b has no registered DEV range, so there is no DEV verdict and "
                "no flag (§7.13).")


def h4b_dev(components: pd.DataFrame, origins) -> dict:
    """H4b on DEV origins: the late_larger count and share per target, and the per-origin
    components, with no verdict."""
    _dev_only(origins)
    c, ix = _h4b_components(components, origins)
    rows = []
    for t in TARGET_ORDER:
        k = int(c.loc[(c["target"] == t).to_numpy() & c["origin"].isin(ix).to_numpy(),
                      "late_larger"].sum())
        rows.append({"target": t, "late_larger": k, "share": k / len(ix) if len(ix) else np.nan})
    table = _front(pd.DataFrame(rows), slice_tags(ix)).assign(label=H4B_LABEL,
                                                               role="descriptive")
    per_origin, lost = _h4b_per_origin(c, ix)
    return {"table": table, "per_origin": per_origin, "lost_originals": lost,
            "note": H4B_DEV_NOTE}


# ---- F2 (§7.12) --------------------------------------------------------------------------
def _is_m2(fc: pd.DataFrame, label: str) -> bool:
    return NAMES["m2"] in label or ("model" in fc.columns and set(fc["model"]) == {NAMES["m2"]})


FAILED_KEY = ("origin", "target", "series", "horizon", "level")   # g1.KEY + level
GAP_KEY = ["origin", "target", "horizon", "parent"]
GAP_FAILED, GAP_NONPOSITIVE = "failed", "median not positive"
GAP_COUNTS = ("coh_gap_n", "coh_gap_excluded_failed", "coh_gap_excluded_nonpositive")


def _ns(origins) -> pd.Series:
    return pd.to_datetime(origins).astype("datetime64[ns]")


def coherence_gaps(fc: pd.DataFrame, icb_of: dict, region_of: dict,
                   failed: pd.DataFrame | None = None) -> pd.DataFrame:
    """``stage_f.coherence_gaps`` with its inputs and exclusions shown: per aggregate forecast,
    the aggregate median ``agg``, the sum of its children's medians, ``excluded`` and the gap
    |agg - children| / agg. ``excluded`` is "failed" when the aggregate or any child is a
    G1-failed forecast (``failed``: their origin, target, series, horizon and level), "median
    not positive" when agg is not above 0 (the gap would be infinite or undefined), and ""
    otherwise; the gap is NaN wherever a forecast is excluded, so it is left out of the gap."""
    med = fc.loc[(fc["quantile"] == 0.5).to_numpy(),
                 ["level", "series", "origin", "target", "horizon", "value"]]
    med = med.assign(origin=_ns(med["origin"]))
    if failed is not None and len(failed):
        f = failed[list(FAILED_KEY)].assign(origin=_ns(failed["origin"])).drop_duplicates()
        med = med.merge(f.assign(_failed=True), on=list(FAILED_KEY), how="left")
        med["_failed"] = med["_failed"].eq(True)
    else:
        med = med.assign(_failed=False)
    rows = []
    for level, child, parent_of in (("icb", "provider", icb_of), ("region", "icb", region_of),
                                    ("england", "region", None)):
        ch, par = med[med["level"] == child], med[med["level"] == level]
        if ch.empty or par.empty:
            continue
        ch = ch.assign(parent=ch["series"].map(parent_of) if parent_of else "ENGLAND")
        sums = ch.groupby(GAP_KEY).agg(children=("value", "sum"), child_failed=("_failed", "any"))
        agg = par.rename(columns={"series": "parent", "value": "agg"}).set_index(GAP_KEY)
        j = agg[["agg", "_failed"]].join(sums, how="inner").reset_index()
        why = np.where(j["_failed"] | j["child_failed"], GAP_FAILED,
                       np.where(j["agg"] > 0, "", GAP_NONPOSITIVE))
        gap = ((j["agg"] - j["children"]).abs() / j["agg"]).where(why == "")
        rows.append(j[GAP_KEY + ["agg", "children"]].assign(level=level, gap=gap, excluded=why))
    cols = ["level", *GAP_KEY, "agg", "children", "gap", "excluded"]
    return pd.concat(rows, ignore_index=True)[cols] if rows else pd.DataFrame(columns=cols)


def _gap_summary(gaps: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """Per contender and level: the gap's mean and max over the forecasts it is defined for,
    their count, and the counts left out (G1-failed; non-positive aggregate median)."""
    rows = []
    for label, g in gaps.items():
        for lv, gl in g.groupby("level", sort=False):
            ok = gl.loc[(gl["excluded"] == "").to_numpy(), "gap"].astype(float)
            rows.append({"model": label, "level": lv,
                         "coh_gap_mean": ok.mean() if len(ok) else np.nan,
                         "coh_gap_max": ok.max() if len(ok) else np.nan,
                         "coh_gap_n": len(ok),
                         "coh_gap_excluded_failed": int((gl["excluded"] == GAP_FAILED).sum()),
                         "coh_gap_excluded_nonpositive":
                             int((gl["excluded"] == GAP_NONPOSITIVE).sum())})
    return pd.DataFrame(rows, columns=["model", "level", "coh_gap_mean", "coh_gap_max",
                                       *GAP_COUNTS])


def _with_gaps(table: pd.DataFrame, gaps: pd.DataFrame) -> pd.DataFrame:
    """``stage_f.f2_table``'s coherence gap replaced by the one over defined forecasts only
    (the excluded counts after it), so an all-zero G1-failed aggregate cannot make it
    infinite."""
    if "coh_gap_max" not in table.columns:
        return table
    g = gaps.set_index(["model", "level"])
    key = pd.MultiIndex.from_arrays([table["model"], table["level"]])
    t = table.copy()
    for c in ("coh_gap_mean", "coh_gap_max"):
        t[c] = g[c].reindex(key).to_numpy(float)
    at = t.columns.get_loc("coh_gap_max") + 1
    for i, c in enumerate(GAP_COUNTS):
        t.insert(at + i, c, g[c].reindex(key).fillna(0).astype(int).to_numpy())
    return t


def _failed_keys(scored: Mapping[str, pd.DataFrame], failed) -> dict:
    """G1's failed forecasts per contender: ``failed[label]`` where given, else the rows the
    scored frame flags (a forecast whose target is not scored is then missed, but an
    all-zero one still drops out of the gap through its median)."""
    out = dict(failed or {})
    for label, f in scored.items():
        if label not in out and "failed" in f.columns:
            out[label] = f.loc[f["failed"].eq(True).to_numpy(), list(FAILED_KEY)]
    return out


F2_LEVELS = ("icb", "region", "england")


def _f2_wis_rows(sc: Mapping[str, pd.DataFrame], labels, o: pd.DatetimeIndex) -> pd.DataFrame:
    """Per contender in ``labels`` and level it has rows at: winter-h3 WIS per target against
    the reference (England's interval n/a, region's caution), then the geometric mean."""
    ref = _winter_h3(sc[stage_f.F2_REFERENCE], o)
    wis = []
    for label in labels:
        s = sc[label][sc[label]["origin"].isin(o)]
        sw = _winter_h3(s, o)
        for lv in F2_LEVELS:
            if not (s["level"] == lv).any():
                continue
            sl, rl = sw[sw["level"] == lv], ref[ref["level"] == lv]
            rels = []
            for t in TARGET_ORDER:
                r = stats.compare(rl[rl["target"] == t], sl[sl["target"] == t], "wis")
                if lv == "england":
                    r = {**r, **dict.fromkeys(("diff_lo", "diff_hi", "rel_lo", "rel_hi"), np.nan)}
                note = (ENGLAND_NA if lv == "england" else
                        f"caution: bootstrap over {r['n_units']} series" if lv == "region" else "")
                wis.append({"model": label, "level": lv, "target": t, **r, "note": note})
                rels.append(r["rel"])
            wis.append({"model": label, "level": lv, "target": "geometric mean",
                        "rel": float(np.exp(np.mean(np.log1p(rels))) - 1)})
    return pd.DataFrame(wis)


def _f2_wis_tagged(wis: pd.DataFrame, sc: Mapping[str, pd.DataFrame], o, g1: str) -> pd.DataFrame:
    scored_all = pd.concat([s[s["origin"].isin(o)] for s in sc.values()], ignore_index=True)
    return _tag(wis, scored_all, ["model", "level"], months="winter", horizons="3",
                metric="wis", reference=stage_f.F2_REFERENCE, g1=g1)


def _f2_one(contenders, sc, icb_of, region_of, o, g1: str, gaps: pd.DataFrame) -> dict:
    table = _with_gaps(stage_f.f2_table(contenders, sc, icb_of, region_of, origins=o), gaps)
    cov50 = []
    for label in table["model"].unique():
        s = sc[label][sc[label]["origin"].isin(o)]
        for lv in table.loc[table["model"] == label, "level"]:
            sl = s[s["level"] == lv]
            cov50.append({"model": label, "level": lv,
                          **{f"cov50_h{h}": sl.loc[sl["horizon"] == h, "cov50"].mean()
                             for h in stats.HORIZONS}})
    table = table.merge(pd.DataFrame(cov50), on=["model", "level"], how="left")
    table.insert(2, "gap_label", [MEDIAN_NON_ADDITIVITY if _is_m2(contenders[m], m)
                                  else "coherence gap" for m in table["model"]])
    labels = [label for label in sc if label in contenders]
    cells = []
    for label in labels:
        s = sc[label][sc[label]["origin"].isin(o)]
        for lv in F2_LEVELS:
            cl = s[s["level"] == lv]
            if cl.empty:
                continue
            cl = cl.assign(model=label)
            cells += [origin_year_cells(cl, st).assign(level=lv) for st in ("cov90", "cov50")]
    scored_all = pd.concat([s[s["origin"].isin(o)] for s in sc.values()], ignore_index=True)
    tag = {"g1": g1}
    return {"table": _tag(table, scored_all, ["model", "level"], months="all", **tag),
            "wis": _f2_wis_tagged(_f2_wis_rows(sc, labels, o), sc, o, g1),
            "cells": _stack(cells).assign(**tag) if cells else pd.DataFrame()}


def f2_wis(scored: Mapping[str, pd.DataFrame], origins) -> pd.DataFrame:
    """F2's winter-h3 WIS (§7.12) on the rows as issued at ``origins``: per contender, level
    and target, rel against M1 + pooled with its interval (England n/a), and the geometric
    mean over targets. The statistic of F2's "wis" table, so a DEV season (§7.13) and the
    CONF value it is flagged against come from one function."""
    if stage_f.F2_REFERENCE not in scored:
        raise ValueError(f"F2 needs the reference {stage_f.F2_REFERENCE!r}")
    for label, f in scored.items():
        _need_g1(f, f"F2 {label}")
        _require(f, mode="asof")
        _check_levels(f, label)
    o = _ts_index(origins)
    return _f2_wis_tagged(_f2_wis_rows(scored, list(scored), o), scored, o, AS_ISSUED)


def f2(contenders: Mapping[str, pd.DataFrame], scored: Mapping[str, pd.DataFrame], icb_of: dict,
       region_of: dict, origins, *, failed: Mapping[str, pd.DataFrame] | None = None) -> dict:
    """At the ``origins`` given (CONF19, CONF21 or DEV, each a separate call). The coherence
    gap is on forecasts, so both G1 variants share it; it leaves out every aggregate forecast
    that is G1-failed or has a G1-failed child, or whose median is not positive, and counts
    them (``coherence_gaps``). ``failed``: {label: G1's failed forecasts} (step 4's failed
    tables); a label without one takes the rows its scored frame flags."""
    if stage_f.F2_REFERENCE not in scored:
        raise ValueError(f"F2 needs the reference {stage_f.F2_REFERENCE!r}")
    missing = set(contenders) - set(scored)
    if missing:
        raise ValueError(f"contenders without scores: {sorted(missing)}")
    for label, f in scored.items():
        _need_g1(f, f"F2 {label}")
    o = _ts_index(origins)
    fk = _failed_keys(scored, failed)
    gaps = _gap_summary({label: coherence_gaps(fc[fc["origin"].isin(o).to_numpy()], icb_of,
                                               region_of, fk.get(label))
                         for label, fc in contenders.items()})
    res = {}
    for name in _variant_names(scored.values()):
        sc = {label: _variant(f, name) for label, f in scored.items()}
        for label, f in sc.items():
            _require(f, mode="asof")
            _check_levels(f, label)
        res[name] = _f2_one(contenders, sc, icb_of, region_of, o, name, gaps)
    return {**res[AS_ISSUED], "failed_dropped": res.get(FAILED_DROPPED),
            "notes": [(f"The gap for {NAMES['m2']} measures {MEDIAN_NON_ADDITIVITY}: its "
                       "aggregates are sums of joint draws, coherent as distributions."),
                      f"WIS relative to {stage_f.F2_REFERENCE}; England {ENGLAND_NA}."]}


# ---- DEV side by side (§7.13) ------------------------------------------------------------
def _dev_only(origins) -> None:
    if _split(origins) not in ("dev", ""):
        raise ValueError("the DEV side takes DEV origins only")


def _seasons(periods: pd.Series) -> np.ndarray:
    labels = {p: stats.season(p) for p in pd.to_datetime(periods).unique()}
    return pd.to_datetime(periods).map(labels).to_numpy()


def dev_seasons(stat_fn: Callable, rows, **tags) -> pd.DataFrame:
    """``rows``: a scored frame, or a dict of them (as h3, h4 and f2 take); each is cut to its
    winter-h3 rows and split by season. ``stat_fn`` gets the season's rows (same type) and
    returns a dict {stat: value} (long: columns stat, value) or a table. ``fragment`` marks
    the one-origin 2023/24 fragment, which ``in_range`` leaves out of the DEV min and max.
    The table carries its slice in front (§7.1): split, the origin set of every season's
    origins, months "winter", horizons "3", then ``tags`` (level, mode, g1, metric, as the
    caller states them; a column the statistic returns is kept)."""
    is_dict = isinstance(rows, Mapping)
    frames = dict(rows) if is_dict else {None: rows}
    frames = {k: f[(f["winter"].astype(bool) & (f["horizon"] == 3)).to_numpy()]
              for k, f in frames.items()}
    every = pd.concat([f["origin"] for f in frames.values()]).unique()
    _dev_only(every)
    labels = {k: _seasons(f["period"]) for k, f in frames.items()}
    out = []
    for s in sorted(set().union(*(set(x) for x in labels.values()))):
        sub = {k: f[labels[k] == s] for k, f in frames.items()}
        res = stat_fn(sub if is_dict else sub[None])
        res = (res.reset_index(drop=True) if isinstance(res, pd.DataFrame) else
               pd.DataFrame({"stat": list(res), "value": list(res.values())}))
        origins = set().union(*(set(f["origin"]) for f in sub.values()))
        res.insert(0, "season", s)
        res.insert(1, "n_origins", len(origins))
        res.insert(2, "fragment", s == FRAGMENT_SEASON)
        res.insert(3, "in_range", s != FRAGMENT_SEASON)
        out.append(res)
    t = _stack(out) if out else pd.DataFrame(columns=["season", "n_origins", "fragment",
                                                       "in_range"])
    return _front(t, {"split": _split(every), "origin_set": _origin_set(every),
                      "months": "winter", "horizons": "3", **tags})


NO_DEV_TABLE, NO_DEV_ROWS = "no DEV table", "the DEV table has no rows"
NO_DEV_VALUE, NO_CONF_VALUE = "no DEV value", "no CONF value"


def _reasons(conf_values, lo, hi, absent: str | None) -> tuple[list, list]:
    """``outside`` per row, and why it is None: the DEV table is absent, or a side has no
    value (a flag is never guessed: stats.outside raises on NaN)."""
    flags, why = [], []
    for x, a, b in zip(conf_values, lo, hi):
        if absent is not None or pd.isna(x) or pd.isna(a) or pd.isna(b):
            flags.append(None)
            why.append(absent if absent is not None else NO_CONF_VALUE if pd.isna(x)
                       else NO_DEV_VALUE)
        else:
            flags.append(stats.outside(x, a, b))
            why.append("")
    return flags, why


def dev_flags(conf, dev: pd.DataFrame | None, keys=("stat",), value: str = "value",
              absent: str = NO_DEV_TABLE) -> pd.DataFrame:
    """A CONF winter-h3 statistic against [min, max] over the DEV seasons in range; ``conf``
    is a table with ``keys`` and ``value``, or a dict {stat: value}. ``dev`` None (the DEV
    table is absent) keeps every CONF row, with ``outside`` None and ``absent`` as its
    reason, and so does a DEV table without rows; a row without a value on either side
    reads None with its reason too."""
    keys = list(keys)
    if isinstance(conf, Mapping):
        conf = pd.DataFrame({"stat": list(conf), value: list(conf.values())})
    t = conf[[*keys, value]].rename(columns={value: "conf"}).reset_index(drop=True)
    why = absent if dev is None else NO_DEV_ROWS if (
        dev.empty or not {*keys, value} <= set(dev.columns)) else None
    if why is not None:
        t = t.assign(dev_min=np.nan, dev_max=np.nan, n_seasons=0)
    else:
        d = dev[dev["in_range"].astype(bool)] if "in_range" in dev.columns else dev
        rng = d.groupby(keys)[value].agg(dev_min="min", dev_max="max", n_seasons="count")
        t = t.merge(rng.reset_index(), on=keys, how="left")
        t["n_seasons"] = t["n_seasons"].fillna(0).astype(int)
    t["outside"], t["reason"] = _reasons(t["conf"], t["dev_min"], t["dev_max"], why)
    return t


def dev_origin_years(rows: pd.DataFrame, stat: str = "cov90") -> pd.DataFrame:
    _dev_only(rows["origin"].unique())
    c = origin_year_cells(rows, stat)
    return c[c["assessed"].astype(bool)].drop(columns="met").reset_index(drop=True)


def dev_coverage_flags(conf_cells: pd.DataFrame, dev_cells: pd.DataFrame | None,
                       pooled: pd.DataFrame | None = None,
                       absent: str = NO_DEV_TABLE) -> pd.DataFrame:
    """Each CONF origin-year cell against the DEV minimum and maximum at its horizon; the
    pooled CONF value (a coverage_by_horizon table) beside them as context, unflagged.
    ``dev_cells`` None (the DEV table is absent) keeps every CONF cell, with ``outside``
    None and ``absent`` as its reason."""
    if dev_cells is not None:
        for col in ("stat", "model", "level"):
            if col in conf_cells.columns and col in dev_cells.columns:
                a, b = set(conf_cells[col].dropna()), set(dev_cells[col].dropna())
                if a != b or len(a) > 1:
                    raise ValueError(f"CONF and DEV cells hold different {col}s: {a} and {b}")
    cols = ["oyear", "horizon", "value", *(["origins"] if "origins" in conf_cells.columns else [])]
    t = conf_cells[cols].rename(columns={"value": "conf", "origins": "conf_origins"})
    if dev_cells is None:
        t = t.assign(dev_min=np.nan, dev_max=np.nan, dev_cells=0)
    else:
        rng = dev_cells.groupby("horizon")["value"].agg(dev_min="min", dev_max="max",
                                                        dev_cells="count").reset_index()
        t = t.merge(rng, on="horizon", how="left")
        t["dev_cells"] = t["dev_cells"].fillna(0).astype(int)
    t["outside"], t["reason"] = _reasons(t["conf"], t["dev_min"], t["dev_max"],
                                         None if dev_cells is not None else absent)
    if pooled is not None:
        t = t.merge(pooled[["horizon", "point"]].rename(columns={"point": "conf_pooled"}),
                     on="horizon", how="left")
    return t
