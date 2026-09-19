"""Stage H steps 4 and 5 (design §5, §6): the builds that read sealed data, and scoring. Both
run in the parent process, after the guarded call (run mode) or with token None (dry run),
and write every output to the store before anything is computed from it (§9).

Store names: step 4 holds ``members``, ``regions``, ``fr_{level}``, ``last_observed``,
``failed_{key}_{level}``, ``failed_counts`` (and ``failed_count_mismatches`` against Stage F's
counts), ``cal_d_{key}`` (Stage D population, provider), ``cal_f_{key}_{level}`` (Stage F
population), ``mint_{key}``, ``h4b_{new,dev}`` and ``m2_dev`` (F2's DEV M2 contender). Step 5
holds one scored frame per forecast table and part, ``{table}__{new|dev}``, with its
``dropped`` counts in the meta.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from nhs_ae.calibrate import g1
from nhs_ae.config import PROCESSED_DIR, PROJECT_ROOT
from nhs_ae.evaluate import harness, stage_f
from nhs_ae.evaluate.stage_h import pools, seal
from nhs_ae.evaluate.stage_h.common import (
    DEV,
    G1_BASES,
    INPUTS,
    LEVELS,
    M2_INPUT,
    P5_INPUTS,
    PROVIDER_MODELS,
    Context,
    ts,
)
from nhs_ae.evaluate.stage_h.hypotheses import h4b_components
from nhs_ae.evaluate.stage_h.store import SCORES, STEP4, Store
from nhs_ae.features.hierarchy import current_region_map, icb_region_map
from nhs_ae.models.base import HORIZONS

log = logging.getLogger(__name__)

POOL = INPUTS / "pool"                              # base_{key}_{level}.parquet: the P5 pool inputs
DEV_SIDE = INPUTS / "dev_side" / "forecasts"         # generate.dev_side's files (design §8)
M2_DEV = INPUTS / M2_INPUT
POOL_SOURCE = stage_f.WORK                          # where `prepare` copies the pool inputs from
M2_SOURCE = PROCESSED_DIR / "stage_h_prep" / "forecasts_m2d_corr.parquet"
G1_REFERENCE = PROJECT_ROOT / "results" / "F-reconciliation-G1" / "failed_counts.csv"
KEY = [*g1.KEY, "level"]
EMBARGO_FROM = ts("2024-01-01")     # §2.6's literal rule: DEV scoring drops periods from here on


def pool_name(key: str, level: str) -> str:
    return f"base_{key}_{level}.parquet"


class InputError(RuntimeError):
    """The inputs asked for are not design §8's permitted set (``P5_INPUTS``)."""


# ---- inputs (P5) -------------------------------------------------------------------------
@dataclass
class Inputs:
    """Forecasts made before the run. ``pool``: {(key, level)} for B1, B2 and M1 v3 raw, the
    P5 pool inputs. ``dev_side``: {(key, level, mode)} from ``prepare --dev-side`` (all 8 in
    run mode; the dry run may lack them). ``m2_dev``: the 69 DEV ``m2d_corr`` fits (None only
    in a dry run without them). Every frame is cut to origins before the first new origin, so
    the new forecasts never overlap them."""
    pool: dict
    dev_side: dict = field(default_factory=dict)
    m2_dev: pd.DataFrame | None = None
    source: str = ""


def load_inputs(ctx: Context) -> Inputs:
    """Run mode reads ``stage_h/inputs``, checked against the pins in step 2, and refuses (a
    backstop to check 11) unless every one of design §8's 21 inputs is there. The dry run reads
    it if ``prepare`` has filled it, else the Stage F base files and the ``stage_h_prep`` M2
    file in place, read only; a DEV-side or M2 file it lacks is left out, and the DEV side
    names what it could not compute. Either mode refuses a file outside ``P5_INPUTS``, and a
    missing pool file. Raises ``InputError``. Reads no sealed data, so ``run`` calls it before
    the unseal."""
    first = ts(ctx.new_origins[0])
    prepared = POOL.is_dir()
    if ctx.mode == "run" and not prepared:
        raise InputError(f"{POOL} is missing: run `prepare --dev-side` before the tag")
    pool_dir = POOL if prepared else POOL_SOURCE
    m2_path = M2_DEV if prepared else M2_SOURCE
    pool_paths = {f"pool/{pool_name(k, lv)}": pool_dir / pool_name(k, lv)
                  for k in G1_BASES for lv in LEVELS}
    dev_paths = ({f"dev_side/forecasts/{p.name}": p for p in sorted(DEV_SIDE.glob("*.parquet"))}
                 if DEV_SIDE.is_dir() else {})
    names = {*(n for n, p in pool_paths.items() if p.is_file()), *dev_paths,
             *([M2_INPUT] if m2_path.is_file() else [])}
    outside = sorted(names - P5_INPUTS)
    if outside:
        raise InputError(f"inputs outside design §8's permitted set: {outside[:5]}")
    missing = sorted(P5_INPUTS - names)
    if ctx.mode == "run" and missing:
        raise InputError(f"{len(missing)} of design §8's {len(P5_INPUTS)} inputs are missing: "
                         f"{missing[:5]}; pin and check 11 require them all")
    no_pool = sorted(set(pool_paths) - names)
    if no_pool:
        raise InputError(f"the pool inputs {no_pool[:5]} are missing from {pool_dir}: every "
                         "calibration and reconciliation needs them")

    def cut(f: pd.DataFrame) -> pd.DataFrame:
        return f[pd.to_datetime(f["origin"]) < first].reset_index(drop=True)

    pool = {(k, lv): cut(pd.read_parquet(pool_paths[f"pool/{pool_name(k, lv)}"]))
            for k in G1_BASES for lv in LEVELS}
    dev_side = {}
    for p in dev_paths.values():
        k, lv, mode = p.stem.rsplit("_", 2)
        dev_side[(k, lv, mode)] = cut(pd.read_parquet(p))
    m2_dev = cut(pd.read_parquet(m2_path)) if m2_path.is_file() else None
    return Inputs(pool, dev_side, m2_dev, "stage_h/inputs" if prepared else "source files (dry run)")


# ---- step 4 ------------------------------------------------------------------------------
def step4(ctx: Context, token, files: dict, inputs: Inputs, vintages: pd.DataFrame) -> Store:
    """First releases, joined base tables, G1, both calibration populations, MinT over every
    DEV and new origin, and H4b's windows (design §5), each put in the step-4 store at once."""
    st = Store(ctx.work / STEP4)
    region_map, regions = current_region_map(vintages), icb_region_map()
    members = stage_f.members(vintages)
    icb_of, region_of = members.to_dict(), regions.to_dict()
    st.put("members", pd.DataFrame({"series": list(icb_of), "icb": list(icb_of.values())}))
    st.put("regions", pd.DataFrame({"icb": list(region_of), "region": list(region_of.values())}))

    fr = pools.first_release_tables(vintages, ctx.end, region_map, regions, token)
    for lv, f in fr.items():
        st.put(f"fr_{lv}", f)
    bases = {(k, lv): pools.join_inputs(inputs.pool[(k, lv)], pd.read_parquet(files[(k, lv, "asof")]),
                                        end=ctx.end)
             for k in G1_BASES for lv in LEVELS}
    last = pools.last_observed(vintages, ctx.end, region_map, regions, token)
    st.put("last_observed", last)
    failed = pools.failed_tables(bases, last)
    for (k, lv), f in failed.items():
        st.put(f"failed_{k}_{lv}", f)
    counts = pools.failed_counts(failed)
    st.put("failed_counts", counts)
    if G1_REFERENCE.is_file():
        st.put("failed_count_mismatches",
               pools.failed_count_mismatches(counts, pd.read_csv(G1_REFERENCE)))
    log.info("step 4: first releases, G1 and %d base tables done", len(bases))

    mint_origins = sorted({*DEV, *ctx.new_origins})
    for k in G1_BASES:
        st.put(f"cal_d_{k}", pools.calibrate_population(
            bases[(k, "provider")], fr["provider"], failed[(k, "provider")], "stage_d", "provider",
            None, token))
        cal_f = {}
        for lv in LEVELS:
            cal_f[lv] = pools.calibrate_population(bases[(k, lv)], fr[lv], failed[(k, lv)],
                                                   "stage_f", lv, members, token)
            st.put(f"cal_f_{k}_{lv}", cal_f[lv])
        st.put(f"mint_{k}", pools.reconcile(cal_f, fr, {lv: failed[(k, lv)] for lv in LEVELS},
                                            mint_origins, icb_of, region_of, token))
        log.info("step 4: %s calibrated and reconciled", k)
    st.put("h4b_new", h4b_components(vintages, ctx.new_origins, end=ctx.end))
    st.put("h4b_dev", h4b_components(vintages, DEV, end=ctx.end))
    if inputs.m2_dev is not None:
        st.put("m2_dev", inputs.m2_dev)               # F2's DEV contender (coherence gaps)
    st.seal_sums()
    return st


# ---- step 5 ------------------------------------------------------------------------------
def tables(ctx: Context, files: dict, inputs: Inputs, s4: Store) -> dict[str, tuple]:
    """Every forecast table to score: name -> (frame, G1 base key or None, failed rows or None).

    Raw provider tables: the new forecasts, plus their DEV side. As-of B1, B2 and M1 v3 raw
    take the pool inputs (all DEV origins, as calibrated); B0 and default M1 as-of, and every
    final-mode table, take ``prepare --dev-side``'s files when present. The seeded as-of B1 of
    the dev side is its own DEV-only table, ``raw_b1_provider_asof_seeded``, for H4's DEV side
    (design §8). Calibrated and reconciled tables carry their base's failed set (issued as
    produced); raw tables of a G1 base get G1 applied to themselves against the as-of last
    observed month, in both modes."""
    last = s4.load("last_observed")
    failed = {k: pd.concat([s4.load(f"failed_{k}_{lv}") for lv in LEVELS], ignore_index=True)
              for k in G1_BASES}
    raw: dict[str, tuple[pd.DataFrame, str]] = {}
    for k in PROVIDER_MODELS:
        for mode in ("asof", "final"):
            parts = [pd.read_parquet(files[(k, "provider", mode)])]
            if mode == "asof" and k in G1_BASES:
                parts.append(inputs.pool[(k, "provider")])
            elif (k, "provider", mode) in inputs.dev_side:
                parts.append(inputs.dev_side[(k, "provider", mode)])
            raw[f"raw_{k}_provider_{mode}"] = (pd.concat(parts, ignore_index=True), k)
    if ("b1", "provider", "asof") in inputs.dev_side:
        raw["raw_b1_provider_asof_seeded"] = (inputs.dev_side[("b1", "provider", "asof")], "b1")
    for k in G1_BASES:
        raw[f"raw_{k}_icb_asof"] = (pd.concat([pd.read_parquet(files[(k, "icb", "asof")]),
                                               inputs.pool[(k, "icb")]], ignore_index=True), k)
    res = {name: (f, k, g1.failed_forecasts(f, last)) if k in G1_BASES else (f, None, None)
           for name, (f, k) in raw.items()}
    for k in G1_BASES:
        res[f"cal_d_{k}"] = (s4.load(f"cal_d_{k}"), k, failed[k])
        for lv in LEVELS:
            res[f"cal_f_{k}_{lv}"] = (s4.load(f"cal_f_{k}_{lv}"), k, failed[k])
        res[f"mint_{k}"] = (s4.load(f"mint_{k}"), k, failed[k])
    m2 = [pd.read_parquet(files[("m2", "all", "asof")])]
    if inputs.m2_dev is not None:
        m2.append(inputs.m2_dev)
    res["m2"] = (pd.concat(m2, ignore_index=True), None, None)
    return res


def step5(ctx: Context, token, files: dict, inputs: Inputs, s4: Store,
          vintages: pd.DataFrame) -> Store:
    """Score every table once (design §6): the new origins on the context's split (CONF with
    the token; the dry run's DEV origins without), and the DEV origins before them with no
    token. Burn-in origins are never scored. G1 marks go on before the frames are stored."""
    sc = Store(ctx.work / SCORES)
    truth = stage_f.truth_all(vintages)
    new = pd.DatetimeIndex([ts(o) for o in ctx.new_origins])
    dev = pd.DatetimeIndex([ts(o) for o in DEV]).difference(new)
    for name, (fc, key, failed) in tables(ctx, files, inputs, s4).items():
        o = pd.to_datetime(fc["origin"])
        for part, origins, split, tok in (("new", new, ctx.split, token if ctx.mode == "run" else None),
                                          ("dev", dev, "dev", None)):
            f = fc[o.isin(origins).to_numpy()]
            if f.empty:
                continue
            s, dropped = seal.score(f, truth, split, tok)
            if key is not None:
                s = g1.mark(s, failed, KEY)
            sc.put(f"{name}__{part}", s.reset_index(drop=True),
                   meta={"dropped": {k: int(v) for k, v in dropped.items()}, "split": split,
                         "g1_base": key})
        log.info("step 5: scored %s", name)
    return sc


def embargo_check(ctx: Context, files: dict, inputs: Inputs, s4: Store, sc: Store) -> dict:
    """Dry run (design §2.6, §10): the seal dropped exactly what the literal rule says. Every
    scored part's ``dropped["embargoed"]`` equals its forecast rows (``harness.KEYS``, unique)
    whose period is 2024-01-01 or later; the new origins' embargoed (origin, horizon) pairs are
    exactly {(o, h): o + (h - 1) months >= 2024-01} over the horizons; and no scored row has
    such a period. Raises ``seal.SealError`` on any difference, and returns what it found."""
    if ctx.mode != "dry":
        raise ValueError("embargo_check is the dry run's: in run mode the new origins are tokened")
    new = pd.DatetimeIndex([ts(o) for o in ctx.new_origins])
    dev = pd.DatetimeIndex([ts(o) for o in DEV]).difference(new)
    meta = {r["name"]: r for r in sc.records().to_dict("records")}
    problems, counts, pairs = [], {}, set()
    for name, (fc, _, _) in tables(ctx, files, inputs, s4).items():
        o = pd.to_datetime(fc["origin"])
        for part, origins in (("new", new), ("dev", dev)):
            f = fc[o.isin(origins).to_numpy()]
            if f.empty:
                continue
            late = f[(pd.to_datetime(f["period"]) >= EMBARGO_FROM).to_numpy()]
            n = len(late[harness.KEYS].drop_duplicates())
            key = f"{name}__{part}"
            dropped = (meta.get(key) or {}).get("dropped")
            got = dropped.get("embargoed") if isinstance(dropped, dict) else None
            counts[key] = n
            if got != n:
                problems.append(f"{key}: the seal dropped {got} rows as embargoed, the rule "
                                f"(period >= {EMBARGO_FROM:%Y-%m-%d}) {n}")
            if part == "new":
                pairs |= {(ts(a), int(h)) for a, h in
                          late[["origin", "horizon"]].drop_duplicates().itertuples(index=False)}
    want = {(o, h) for o in new for h in HORIZONS
            if o + pd.DateOffset(months=h - 1) >= EMBARGO_FROM}
    if pairs != want:
        problems.append(f"embargoed pairs: {len(pairs)} found, {len(want)} expected; extra "
                        f"{sorted(pairs - want)[:3]}, missing {sorted(want - pairs)[:3]}")
    sealed_scored = 0
    for name in sc.names():
        s = sc.load(name) if name.endswith(("__new", "__dev")) else None
        if s is not None and len(s):
            sealed_scored += int((pd.to_datetime(s["period"]) >= EMBARGO_FROM).sum())
    if sealed_scored:
        problems.append(f"{sealed_scored} scored rows have a period from "
                        f"{EMBARGO_FROM:%Y-%m-%d} on")
    if problems:
        raise seal.SealError("embargo check (design §2.6): " + "; ".join(problems))
    return {"embargoed_pairs": sorted((str(o.date()), int(h)) for o, h in pairs),
            "n_embargoed_pairs": len(pairs), "embargoed_rows": counts,
            "sealed_periods_scored": sealed_scored}


def input_paths() -> dict[str, Path]:
    """The 13 files `prepare` copies into stage_h/inputs, by their P5 name (design §8); the
    other 8 of ``P5_INPUTS`` are generated there by ``prepare --dev-side``."""
    paths = {f"pool/{pool_name(k, lv)}": POOL_SOURCE / pool_name(k, lv)
             for k in G1_BASES for lv in LEVELS}
    paths[M2_INPUT] = M2_SOURCE
    outside = sorted(set(paths) - P5_INPUTS)
    if outside:
        raise InputError(f"input_paths names files outside P5_INPUTS: {outside}")
    return paths
