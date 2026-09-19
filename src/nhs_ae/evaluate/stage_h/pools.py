"""Stage H step 4: first-release tables, joined base tables, G1, calibration and MinT
(design §2.4-§2.5, §5). Runs only in the parent process, only after the guarded call (run
mode) or with token None (dry run), and never beyond the context's end origin E (§2.4): every
origin set a builder reads (the as-of origins of the tables, the calibration and MinT origins)
is refused beyond RUN_END and, with token None, if sealed, which stops the dry run at 2023-12;
join_inputs takes E as ``end``. Every call into online and stage_f passes the token on as
``unseal_token`` (P11), so their own guards see it; the runner-side guards here stay.

CONTRACT (the implementation keeps these signatures):

guard_first_releases(merged, token) -> None
    Runner-side sealed-period guard (§2.5): splits.assert_not_sealed(
    merged.loc[merged["y_first"].notna(), ["period"]], token). Called before every calibrate
    and every _median_errors. With token None it raises SealedOriginError if any row carrying
    a first release has a sealed period.

first_release_tables(vintages, end, region_map, regions, token) -> dict[str, DataFrame]
    Provider and ICB: online.first_release(vintages, month_range(FR_START, end),
    since=INPUT_START, level=..., region_map=region_map, unseal_token=token); EXCLUDE dropped
    at ICB. Region and England: aggregate_first_release(icb, regions, level). Asserts every
    table has resolved <= end and period < end (and, with token None, no sealed period).

aggregate_first_release(fr_icb, regions, level) -> DataFrame
    §5.2 completeness rule: an aggregate (region via ``regions`` ICB->region map, or
    "ENGLAND") has a first release for (target, period) only once every mapped ICB beneath it
    has one; y_first = sum, resolved = max. Columns: target, series, period, y_first, resolved.

join_inputs(inputs, new, *, end=None) -> DataFrame
    Concatenate a P5 input table and the new forecasts for one model x level; refuse (raise)
    if their origin sets overlap, their origins are not both tz-naive datetime64, an origin
    lies beyond ``end`` (the orchestrator passes ctx.end; default RUN_END), or their
    model/level/mode differ.

failed_tables(bases, last) -> dict[tuple[str, str], DataFrame]
    bases: {(model_key, level): forecasts}. g1.failed_forecasts per entry.

calibrate_population(fc, fr, failed, population, level, members, token) -> DataFrame
    Pooled conformal with G1 (online.calibrate(..., methods=("pooled",), failed=...,
    unseal_token=token)).
    population "stage_d": every provider code (Stage D); "stage_f": hierarchy members at
    provider level (``members`` index), non-EXCLUDE series at aggregate levels (Stage F).
    Bounds the population's origins (§2.4), then calls guard_first_releases on the merge of fc
    and fr.

reconcile(cal, fr, failed, origins, icb_of, region_of, token) -> DataFrame
    MinT via stage_f.reconcile_frames (cal/fr/failed: {level: frame}) over ``origins``
    (every DEV and new origin up to E, §5.6); ``origins`` and the calibrated frames' origins
    bounded (§2.4); guard_first_releases before the median errors; ``unseal_token=token``.

pool_origins(fc, fr, target, horizon, t, failed=None, token=None) -> list[pd.Timestamp]
    The origin set of the pooled-conformal pool used at origin t (from the online trace),
    for the P3 tests.

Added beyond the skeleton:
last_observed(vintages, end, region_map, regions, token)  G1's last observed values at every
    origin INPUT_START..E and every level (§5.4), bounded and guarded like the tables.
pool_trace(fc, fr, failed=None, token=None) -> dict       every pool's origin set at once.
failed_counts(failed) / failed_count_mismatches(counts, reference)   §5.4's DEV check of the
    G1 counts against ``G1_COUNTS``.
"""

from __future__ import annotations

import multiprocessing

import numpy as np
import pandas as pd

from nhs_ae.calibrate import g1, online
from nhs_ae.config import PROJECT_ROOT
from nhs_ae.evaluate import splits, stage_f
from nhs_ae.evaluate.stage_h.common import DEV, FR_START, INPUT_START, LEVELS, RUN_END, ts
from nhs_ae.ingest.recover import month_range

EXCLUDE = stage_f.EXCLUDE
AGG_LEVELS = stage_f.AGG_LEVELS
POPULATIONS = ("stage_d", "stage_f")
G1_COUNTS = PROJECT_ROOT / "results" / "F-reconciliation-G1" / "failed_counts.csv"   # §5.4 reference
FR_KEY = ["target", "series", "period"]


def _check_caller(token) -> None:
    """Step 4 runs in the parent process; a token is used only once the guarded call has
    logged it (so no call here can write the first log line)."""
    if multiprocessing.parent_process() is not None:
        raise RuntimeError("Stage H step 4 runs only in the parent process")
    if token is not None and token not in splits._logged_tokens:
        raise RuntimeError("a token reached step 4 before the guarded call")


def _refuse_beyond(origins: pd.DatetimeIndex, end=None) -> None:
    """Raise if an origin lies beyond ``end`` (default RUN_END; never later than RUN_END)."""
    lim = ts(RUN_END) if end is None else min(ts(end), ts(RUN_END))
    if len(origins) and origins.max() > lim:
        raise ValueError(f"origins run to {origins.max():%Y-%m}, beyond E = {lim:%Y-%m}")


def _bound(origins, token) -> None:
    """§2.4 for one origin set, before anything is computed on it: refused beyond RUN_END and,
    without a token, if any origin is sealed (so the dry run stops at 2023-12 = DRY_END)."""
    _check_caller(token)
    o = pd.DatetimeIndex(pd.to_datetime(pd.Index(list(origins)))).unique()
    _refuse_beyond(o)
    splits.assert_not_sealed(o, token)


def _bounded_origins(start, end, token) -> list:
    """month_range(start, end), refused before any data are read if ``end`` lies beyond E or,
    without a token, if an origin or an as-of period in range is sealed."""
    origins = month_range(ts(start).date(), ts(end).date())
    _bound(origins, token)
    splits.assert_not_sealed(pd.DataFrame({"period": [ts(end) - pd.DateOffset(months=1)]}), token)
    return origins


def guard_first_releases(merged: pd.DataFrame, token) -> None:
    """§2.5: no row that carries a first release may have a sealed period, unless unsealed."""
    _check_caller(token)
    splits.assert_not_sealed(merged.loc[merged["y_first"].notna(), ["period"]], token)


def _merged(fc: pd.DataFrame, fr: pd.DataFrame) -> pd.DataFrame:
    """The forecast keys with the first releases ``online.calibrate`` would attach to them."""
    return fc[FR_KEY].drop_duplicates().merge(fr[[*FR_KEY, "y_first"]], on=FR_KEY, how="left")


# ---- first releases (§5.2) ---------------------------------------------------------------
def first_release_tables(vintages: pd.DataFrame, end, region_map: pd.Series, regions: pd.Series,
                         token) -> dict[str, pd.DataFrame]:
    """§5.2: {level: target, series, period, y_first, resolved}, built over origins FR_START..E."""
    origins = _bounded_origins(FR_START, end, token)
    fr = {lv: online.first_release(vintages, origins, region_map=region_map, since=INPUT_START, level=lv,
                                   unseal_token=token)
          for lv in ("provider", "icb")}
    fr["icb"] = fr["icb"][~fr["icb"]["series"].isin(EXCLUDE)].reset_index(drop=True)
    for lv in AGG_LEVELS:
        fr[lv] = aggregate_first_release(fr["icb"], regions, lv)
    for lv, t in fr.items():
        if len(t) and (t["resolved"].max() > ts(end) or t["period"].max() >= ts(end)):
            raise RuntimeError(f"{lv} first releases reach beyond E = {ts(end):%Y-%m}")
        guard_first_releases(t, token)
    return fr


def aggregate_first_release(fr_icb: pd.DataFrame, regions: pd.Series, level: str) -> pd.DataFrame:
    """ICBs the map does not place go to region "?" and count towards England, as in Stage F;
    a mapped ICB with no first release at any period raises, since its aggregates could never
    resolve."""
    fr = fr_icb[~fr_icb["series"].isin(EXCLUDE)]
    if fr.duplicated(FR_KEY).any():
        raise ValueError("the ICB first releases hold a (target, series, period) twice")
    mapped = regions[~regions.index.isin(EXCLUDE)]
    seen = pd.Index(fr["series"].unique())
    if len(missing := mapped.index.difference(seen)):
        raise ValueError(f"mapped ICBs with no first release at any period: {list(missing)}")
    icbs = mapped.index.union(seen)
    if level == "region":
        parent = mapped.reindex(icbs).fillna("?")
    elif level == "england":
        parent = pd.Series("ENGLAND", index=icbs)
    else:
        raise ValueError(f"no aggregate level {level!r}")
    need = parent.value_counts()
    g = fr.assign(series=fr["series"].map(parent)).groupby(FR_KEY)
    out = g.agg(y_first=("y_first", "sum"), resolved=("resolved", "max"), n=("y_first", "size")).reset_index()
    full = out["n"].to_numpy() == out["series"].map(need).to_numpy()
    return out.loc[full, [*FR_KEY, "y_first", "resolved"]].reset_index(drop=True)


# ---- base tables and G1 (§5.3, §5.4) -----------------------------------------------------
def join_inputs(inputs: pd.DataFrame, new: pd.DataFrame, *, end=None) -> pd.DataFrame:
    """§5.3: one model x level table, the P5 input followed by the new forecasts, with no
    origin beyond ``end`` (E). Origins must be tz-naive datetime64 on both sides: a date or a
    tz-aware timestamp never matches a naive timestamp, so an overlap would go unseen."""
    for col in ("model", "level", "mode"):
        vals = set(inputs[col].unique()) | set(new[col].unique())
        if inputs[col].nunique() != 1 or new[col].nunique() != 1 or len(vals) != 1:
            raise ValueError(f"input and new forecasts must share one {col}: {sorted(map(str, vals))}")
    if set(inputs.columns) != set(new.columns):
        raise ValueError("input and new forecasts have different columns")
    if not all(pd.api.types.is_datetime64_dtype(f["origin"]) for f in (inputs, new)):
        raise ValueError(f"origins must be tz-naive datetime64 on both sides, not "
                         f"{inputs['origin'].dtype} and {new['origin'].dtype}")
    a, b = (pd.DatetimeIndex(f["origin"].unique()) for f in (inputs, new))
    if len(both := a.intersection(b)):
        raise ValueError(f"{len(both)} origins in both the input and the new forecasts, "
                         f"from {both.min():%Y-%m}")
    _refuse_beyond(a.union(b), end)
    return pd.concat([inputs, new[list(inputs.columns)]], ignore_index=True)


def last_observed(vintages: pd.DataFrame, end, region_map: pd.Series, regions: pd.Series,
                  token) -> pd.DataFrame:
    """``g1.last_observed`` at every origin INPUT_START..E and every level."""
    origins = _bounded_origins(INPUT_START, end, token)
    return g1.last_observed(vintages, origins, LEVELS, regions=regions, region_map=region_map)


def failed_tables(bases: dict[tuple[str, str], pd.DataFrame],
                  last: pd.DataFrame) -> dict[tuple[str, str], pd.DataFrame]:
    """§5.4: G1's failed forecasts per (model_key, level), from ``last_observed``."""
    out = {}
    for (key, level), fc in bases.items():
        if fc["model"].nunique() != 1 or set(fc["level"].unique()) != {level}:
            raise ValueError(f"{key}/{level}: one model at level {level} expected")
        out[(key, level)] = g1.failed_forecasts(fc, last)
    return out


def failed_counts(failed: dict[tuple[str, str], pd.DataFrame]) -> pd.DataFrame:
    """Failed forecasts per base and level: over the DEV input span (origins to the end of
    DEV), at DEV origins, and at later origins."""
    rows = []
    for (key, level), f in failed.items():
        o = pd.to_datetime(f["origin"])
        span = (o <= ts(DEV[-1])).to_numpy()
        rows.append({"model": stage_f.LABELS[key], "level": level, "failed": int(span.sum()),
                     "failed_dev_origins": int((span & (o >= ts(DEV[0])).to_numpy()).sum()),
                     "failed_new_origins": int((~span).sum())})
    return pd.DataFrame(rows, columns=["model", "level", "failed", "failed_dev_origins",
                                       "failed_new_origins"])


def failed_count_mismatches(counts: pd.DataFrame, reference: pd.DataFrame) -> pd.DataFrame:
    """Rows where the input-span or DEV-origin counts differ from ``reference`` (the Stage F G1
    re-run's ``failed_counts.csv``), a row missing on either side included. Reported, not a stop."""
    cols = ["failed", "failed_dev_origins"]
    m = counts[["model", "level", *cols]].merge(reference[["model", "level", *cols]], on=["model", "level"],
                                                how="outer", suffixes=("", "_ref"))
    bad = np.zeros(len(m), dtype=bool)
    for c in cols:
        bad |= m[c].ne(m[f"{c}_ref"]).to_numpy()
    return m[bad].reset_index(drop=True)


# ---- calibration (§5.5) and MinT (§5.6) --------------------------------------------------
def calibrate_population(fc: pd.DataFrame, fr: pd.DataFrame, failed: pd.DataFrame | None,
                         population: str, level: str, members: pd.Series | None, token) -> pd.DataFrame:
    """§5.5: pooled conformal plus G1 over one registered population, bounded and guarded first."""
    if population == "stage_d":
        if level != "provider":
            raise ValueError("the Stage D population is defined at provider level only")
        pop = fc
    elif population == "stage_f":
        if level == "provider" and members is None:
            raise ValueError("the Stage F provider population needs the hierarchy members")
        pop = fc[fc["series"].isin(members.index)] if level == "provider" else fc[~fc["series"].isin(EXCLUDE)]
    else:
        raise ValueError(f"population must be one of {POPULATIONS}, not {population!r}")
    if set(pop["level"].unique()) != {level}:
        raise ValueError(f"forecasts at level(s) {sorted(map(str, pop['level'].unique()))}, not {level}")
    _bound(pop["origin"].unique(), token)
    guard_first_releases(_merged(pop, fr), token)
    return online.calibrate(pop, fr, methods=("pooled",), failed=failed, unseal_token=token)


def reconcile(cal: dict[str, pd.DataFrame], fr: dict[str, pd.DataFrame],
              failed: dict[str, pd.DataFrame] | None, origins, icb_of: dict, region_of: dict,
              token) -> pd.DataFrame:
    """§5.6: MinT of one base at ``origins``. Those origins and every calibrated forecast's
    origin (the error history reads them all) are bounded; the median errors are guarded before
    they exist."""
    _bound(origins, token)
    _bound(pd.concat([c["origin"] for c in cal.values()]).unique(), token)
    return stage_f.reconcile_frames(cal, fr, failed, origins, icb_of, region_of,
                                    errs_guard=lambda merged: guard_first_releases(merged, token),
                                    unseal_token=token)


# ---- pool origin sets (P3 tests) ---------------------------------------------------------
def pool_trace(fc: pd.DataFrame, fr: pd.DataFrame, failed: pd.DataFrame | None = None,
               token=None) -> dict[tuple[str, pd.Timestamp, int], list[pd.Timestamp]]:
    """(target, t, h) -> the origins of the pooled window consulted at t, for one model's table."""
    _bound(fc["origin"].unique(), token)
    guard_first_releases(_merged(fc, fr), token)
    trace: dict = {}
    online.calibrate(fc, fr, methods=("pooled",), failed=failed, trace=trace, unseal_token=token)
    return trace


def pool_origins(fc: pd.DataFrame, fr: pd.DataFrame, target: str, horizon: int, t,
                 failed: pd.DataFrame | None = None, token=None) -> list[pd.Timestamp]:
    """KeyError if nothing is issued at (t, horizon)."""
    trace = pool_trace(fc[fc["target"] == target], fr, failed, token)
    return trace[(target, ts(t), int(horizon))]
