"""Stage H statistics from the store (design §7, §9): every hypothesis on the new origins, its
DEV side, and each CONF value set against DEV's range (§7.13), from frames read back through
the verifying loader only. Makes no guarded call, so ``report --from-scores`` can run it after
a crash without a second unseal.

Beyond the hypotheses, ``compute`` returns:
- ``dev``: ``dev_side``'s DEV tables (coverage cells, per-season winter-h3 statistics, F2 over
  every DEV origin, H4b's DEV side) and its ``_errors``, which name every registered DEV
  statistic it could not compute;
- ``dev_flags``: ``dev_compare``'s tables, one per registered range ("h1", "h3", "h4",
  "h4_original", "f2_wis", "coverage_<name>"), each row flagged ``outside`` DEV's range or
  None with its ``reason``, and "outside": the counts and flagged rows per table; the
  primary's table is also ``primary.alongside.dev_range`` (§7.5);
- ``_errors``: every statistic that failed or is not evaluable, by name (a flag table that
  could not be made is "dev_flags.<name>").
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping

import numpy as np
import pandas as pd

from nhs_ae.evaluate import stage_f
from nhs_ae.evaluate.stage_h import hypotheses as hyp
from nhs_ae.evaluate.stage_h.common import CONF21, DEV, G1_BASES, LEVELS, NAMES, W5, Context, ts
from nhs_ae.evaluate.stage_h.store import Store

log = logging.getLogger(__name__)

F2_CONTENDERS = {"ETS + pooled": ("cal_f", "b1"), "ETS + pooled + MinT": ("mint", "b1"),
                 "M1 + pooled": ("cal_f", "m1_v3_raw"), "M1 + pooled + MinT": ("mint", "m1_v3_raw")}
F2_M2 = "M2 frozen (m2d_corr)"
H1_KEYS = ("b0", "m1", "m1_v3_raw")
H4_KEYS = ("b0", "b1", "b2", "m1", "m1_v3_raw")
MODES = ("asof", "final")
ISSUED = hyp.AS_ISSUED
ABSENT = "not computed: DEV rows absent"
SELF = "the reference itself: rel 0 by construction on both sides"

# The registered DEV ranges (§7.13). Winter-h3 statistics, one value per DEV season, as long
# tables: name -> (key columns, slice tags). The same function gives the CONF value, so the
# keys match. Coverage: each model's origin-year cells, from the same tables on both sides.
SEASONS = {
    "h1": (("model", "target"), {"level": "provider", "mode": "asof", "metric": "mase"}),
    "h3": (("base", "level"), {"mode": "asof", "metric": "wis"}),
    "h4": (("model", "target"), {"level": "provider", "mode": "final vs asof", "metric": "wis"}),
    "h4_original": (("model", "target"),
                    {"level": "provider", "mode": "final vs asof", "metric": "wis"}),
    "f2_wis": (("model", "level", "target"), {"mode": "asof", "metric": "wis"}),
}
COVERAGE = ("primary", "h2_m1", "h2_m2",
            *(f"headline_{kind}_{k}" for kind in ("raw", "pooled") for k in G1_BASES))
COVERAGE_TAGS = ("split", "origin_set", "n_origins", "level", "mode", "months", "model", "stat",
                 "g1")


class Scores:
    """Read-back access to the step-4 and step-5 stores."""

    def __init__(self, s4: Store, sc: Store):
        self.s4, self.sc = s4, sc
        self._names = set(sc.names())

    def get(self, table: str, part: str) -> pd.DataFrame | None:
        name = f"{table}__{part}"
        return self.sc.load(name) if name in self._names else None

    def cal_f(self, key: str) -> pd.DataFrame:
        return pd.concat([self.s4.load(f"cal_f_{key}_{lv}") for lv in LEVELS], ignore_index=True)


class NotEvaluable(Exception):
    """A statistic whose registered inputs are incomplete; ``_guard`` records its reason."""


def _cat(frames) -> pd.DataFrame | None:
    frames = [f for f in frames if f is not None and len(f)]
    return pd.concat(frames, ignore_index=True) if frames else None


def _front(t: pd.DataFrame, tags: dict) -> pd.DataFrame:
    t = t.copy()
    for i, (k, v) in enumerate((k, v) for k, v in tags.items() if k not in t.columns):
        t.insert(i, k, v)
    return t


def _winter_h3(rows: pd.DataFrame | None, origins) -> list:
    """The origins among ``origins`` with scored winter-h3 rows."""
    if rows is None:
        return []
    w = rows[rows["winter"].astype(bool) & (rows["horizon"] == 3)]
    have = set(pd.to_datetime(w["origin"]).unique())
    return [o for o in pd.to_datetime(pd.Index(list(origins))) if o in have]


def _winter_origins(frames: Mapping[str, pd.DataFrame | None], counted, mode: str) -> list:
    """The counted winter-h3 origins present in every frame a statistic uses. In run mode
    they must be W5 (§7.1): otherwise the statistic is not evaluable, and the reason names
    the origins missing from each table."""
    have = {name: set(_winter_h3(f, counted)) for name, f in frames.items()}
    common = set.intersection(*have.values()) if have else set()
    o = [x for x in pd.to_datetime(pd.Index(list(counted))) if x in common]
    w5 = list(pd.to_datetime(pd.Index(list(W5))))
    if mode == "run" and o != w5:
        gaps = {name: [f"{x:%Y-%m}" for x in w5 if x not in h] for name, h in have.items()}
        gaps = {name: g for name, g in gaps.items() if g}
        missing = sorted({x for g in gaps.values() for x in g})
        extra = [f"{x:%Y-%m}" for x in o if x not in w5]
        raise NotEvaluable(f"not evaluable: origins {missing} missing"
                           + (f", {extra} not in W5" if extra else "")
                           + f" (W5 must be complete in every table used: {gaps})")
    return o


def _at(rows: pd.DataFrame, origins) -> pd.DataFrame:
    return rows[pd.to_datetime(rows["origin"]).isin(pd.to_datetime(pd.Index(list(origins))))
                .to_numpy()]


def _guard(name: str, fn: Callable, out: dict) -> None:
    """Run one statistic; a failure is recorded, not raised, so one broken table cannot hide
    the rest. The run's summary lists every failure; a statistic that is not evaluable is
    recorded with its reason alone."""
    try:
        out[name] = fn()
    except NotEvaluable as e:
        log.warning("statistic %s: %s", name, e)
        out.setdefault("_errors", {})[name] = str(e)
    except Exception as e:
        log.exception("statistic %s failed", name)
        out.setdefault("_errors", {})[name] = f"{type(e).__name__}: {e}"


def _with_loo(fn: Callable, rows, origins) -> dict:
    return fn(rows, origins, loo=len(origins) >= 2)


def _reader(S: Scores, part: str) -> Callable[[str], pd.DataFrame | None]:
    """``S.get`` for one part of the scores store, each table loaded and verified once."""
    got: dict = {}

    def get(table: str) -> pd.DataFrame | None:
        if table not in got:
            got[table] = S.get(table, part)
        return got[table]

    return get


def compute(ctx: Context, s4: Store, sc: Store, files: dict, fits: pd.DataFrame) -> dict:
    """Every result of design §7 on the new origins, the DEV side, and the CONF values against
    DEV's range (§7.13)."""
    S = Scores(s4, sc)
    counted, fold = list(ctx.counted), dict(ctx.fold)
    full = list(ctx.new_origins)
    m, r = s4.load("members"), s4.load("regions")
    icb_of, region_of = dict(zip(m["series"], m["icb"])), dict(zip(r["icb"], r["region"]))
    R: dict = {"context": {"mode": ctx.mode, "counted": [str(o) for o in counted],
                           "new_origins": [str(o) for o in full]}}
    C: dict = {}        # CONF winter-h3 statistics in the DEV seasons' long form (§7.13)

    def conf_stat(name: str, stat: Callable, rows, frames: Mapping) -> None:
        def run():
            o = _winter_origins(frames, counted, ctx.mode)
            return _conf_tagged(stat(rows, o), o, name)
        _guard(name, run, C)

    new = _reader(S, "new")

    # H1 (§7.3)
    h1_t = {f"raw_{k}_provider_asof": new(f"raw_{k}_provider_asof") for k in H1_KEYS}
    h1_rows = _cat(h1_t.values())
    _guard("h1", lambda: _with_loo(hyp.h1, h1_rows, _winter_origins(h1_t, counted, ctx.mode)),
           R)
    conf_stat("h1", _h1_stat, h1_rows, h1_t)

    # primary and H2 (§7.5); the same rows give the CONF coverage cells for the flags
    cov = _coverage_rows(new)
    _guard("primary", lambda: hyp.primary(cov["primary"][1], counted, fold), R)
    _guard("h2_m1", lambda: hyp.h2_m1(cov["h2_m1"][1], counted, fold), R)
    _guard("h2_m2", lambda: hyp.h2_m2(cov["h2_m2"][1], counted, fold, fits), R)

    # descriptive headline (§7.6)
    raw = {NAMES[k]: cov[f"headline_raw_{k}"][1] for k in G1_BASES}
    pooled = {NAMES[k]: cov[f"headline_pooled_{k}"][1] for k in G1_BASES}
    _guard("headline", lambda: hyp.headline(raw, pooled, counted, fold,
                                            icb_raw_ets=new("raw_b1_icb_asof")), R)

    # H3 (§7.7)
    h3_in = {**{(k, "base"): _cat([new(f"cal_f_{k}_{lv}") for lv in LEVELS]) for k in G1_BASES},
             **{(k, "mint"): new(f"mint_{k}") for k in G1_BASES}}
    # W5 per level: a region table short of an origin must not hide behind the other levels
    h3_t = {f"{k}/{kind}/{lv}": (None if f is None else f[(f["level"] == lv).to_numpy()])
            for (k, kind), f in h3_in.items() for lv in LEVELS}
    _guard("h3", lambda: _with_loo(hyp.h3, h3_in, _winter_origins(h3_t, counted, ctx.mode)), R)
    conf_stat("h3", _h3_stat, h3_in, h3_t)

    # H4 and H4-original (§7.8, §7.9)
    h4_in = {(k, mode): new(f"raw_{k}_provider_{mode}") for k in H4_KEYS for mode in MODES}
    h4_t = {"/".join(k): f for k, f in h4_in.items()}
    _guard("h4", lambda: _with_loo(hyp.h4, h4_in, _winter_origins(h4_t, counted, ctx.mode)), R)

    def _h4o():
        if "h4" not in R:
            raise NotEvaluable(f"not computed: H4 has no result "
                               f"({(R.get('_errors') or {}).get('h4', 'failed')})")
        return hyp.h4_original(h4_in, _winter_origins(h4_t, counted, ctx.mode), R["h4"])

    _guard("h4_original", _h4o, R)
    conf_stat("h4", _h4_stat, h4_in, h4_t)
    conf_stat("h4_original", _h4o_stat, h4_in, h4_t)

    # H4b (§7.10) and H5; a store file that fails verification is refused, not recorded
    h4b_new = s4.load("h4b_new")
    _guard("h4b", lambda: hyp.h4b(h4b_new, counted, full), R)
    R["h5"] = hyp.H5_LINE

    # F2 (§7.12): CONF19, and CONF21 separately in run mode
    contenders = {label: (S.cal_f(key) if kind == "cal_f" else s4.load(f"mint_{key}"))
                  for label, (kind, key) in F2_CONTENDERS.items()}
    contenders[F2_M2] = pd.read_parquet(files[("m2", "all", "asof")])
    f2_scored = {label: h3_in[(key, "base" if kind == "cal_f" else "mint")]
                 for label, (kind, key) in F2_CONTENDERS.items()}
    f2_scored[F2_M2] = new("m2")
    failed = _f2_failed(s4)
    _guard("f2", lambda: hyp.f2(contenders, f2_scored, icb_of, region_of, counted,
                                failed=failed), R)
    if ctx.mode == "run":
        _guard("f2_conf21", lambda: hyp.f2(contenders, f2_scored, icb_of, region_of,
                                           list(CONF21), failed=failed), R)

    def f2_wis():
        # F2's WIS is over the counted origins' winter-h3 rows (§7.12), as R["f2"]["wis"]
        o = _winter_h3(_cat(f2_scored.values()), counted)
        return _conf_tagged(_f2_wis_stat(f2_scored, o), o, "f2_wis")

    _guard("f2_wis", f2_wis, C)

    # the DEV side (§7.13) and CONF against DEV's range
    R["dev"] = dev_side(S, contenders, icb_of, region_of, new_origins=full, failed=failed)
    cells: dict = {}
    for name, (_, rows) in cov.items():
        _guard(name, lambda rows=rows: _cells(rows, counted), cells)
    F = dev_compare(C, cells, _pooled(R), R["dev"])
    for k, v in F.pop("_errors", {}).items():
        R.setdefault("_errors", {})[f"dev_flags.{k}"] = v
    R["dev_flags"] = F
    if isinstance(R.get("primary"), dict) and "coverage_primary" in F:
        R["primary"]["alongside"]["dev_range"] = F["coverage_primary"]

    R["failed_counts"] = s4.load("failed_counts")
    if "failed_count_mismatches" in s4.names():
        R["failed_count_mismatches"] = s4.load("failed_count_mismatches")
    R["m2_fits"] = fits
    return R


def _coverage_rows(get: Callable[[str], pd.DataFrame | None]
                   ) -> dict[str, tuple[str, pd.DataFrame | None]]:
    """name -> (store table, rows) behind each registered coverage range, ``get`` reading one
    part of the scores store: the CONF and DEV cells come from the same tables by the same
    code."""
    m2 = get("m2")
    out = {"primary": ("cal_d_m1_v3_raw", get("cal_d_m1_v3_raw")),
           "h2_m1": ("raw_m1_provider_asof", get("raw_m1_provider_asof")),
           "h2_m2": ("m2", None if m2 is None else m2[(m2["level"] == "icb").to_numpy()])}
    for kind, table in (("raw", "raw_{}_provider_asof"), ("pooled", "cal_d_{}")):
        for k in G1_BASES:
            out[f"headline_{kind}_{k}"] = (table.format(k), get(table.format(k)))
    return out


def _cells(rows: pd.DataFrame | None, counted) -> pd.DataFrame:
    """The CONF origin-year cells of one coverage range: its counted origins' rows, as
    issued."""
    if rows is None or rows.empty:
        raise NotEvaluable("no CONF rows")
    return hyp.origin_year_cells(_at(rows, counted)).assign(g1=ISSUED)


def _pooled(R: dict) -> dict:
    """The pooled CONF19 value by horizon beside each coverage range (context, unflagged)."""
    out = {}
    for name in ("primary", "h2_m1", "h2_m2"):
        t = (R.get(name) or {}).get("table")
        if isinstance(t, pd.DataFrame):
            out[name] = t
    h = (R.get("headline") or {}).get("by_horizon")
    if isinstance(h, pd.DataFrame):
        for k in G1_BASES:
            hk = h[(h["model"] == NAMES[k]).to_numpy()]
            for kind in ("raw", "pooled"):
                out[f"headline_{kind}_{k}"] = hk[["horizon", f"point_{kind}"]].rename(
                    columns={f"point_{kind}": "point"})
    return out


def _f2_failed(s4: Store) -> dict[str, pd.DataFrame]:
    """G1's failed forecasts behind each F2 contender's base (step 4), for the coherence gap."""
    names, by_key, out = set(s4.names()), {}, {}
    for label, (_, key) in F2_CONTENDERS.items():
        parts = [f"failed_{key}_{lv}" for lv in LEVELS]
        if all(p in names for p in parts):
            if key not in by_key:
                by_key[key] = pd.concat([s4.load(p) for p in parts], ignore_index=True)
            out[label] = by_key[key]
    return out


# ---- the DEV side (§7.13) ----------------------------------------------------------------
def dev_side(S: Scores, contenders: dict, icb_of: dict, region_of: dict, *, new_origins=(),
             failed: Mapping[str, pd.DataFrame] | None = None) -> dict:
    """The same statistics on DEV origins (§7.13): coverage per assessable DEV origin-year,
    each winter-h3 statistic per DEV season, F2 over every DEV origin and H4b's DEV side
    (every DEV origin but ``new_origins``). A registered statistic whose DEV rows are absent
    is named in ``_errors`` ("not computed: DEV rows absent (<tables>)"), never skipped, and
    a failure inside the coverage or season groups is lifted there as "<group>.<name>"."""
    D: dict = {"coverage": {}, "seasons": {}}
    errors: dict = {}
    dev = _reader(S, "dev")

    def absent(tables: Mapping) -> str | None:
        gone = [f"{t}__dev" for t, f in tables.items() if f is None or f.empty]
        return f"{ABSENT} ({', '.join(gone)})" if gone else None

    def season(name: str, stat: Callable, rows, tables: Mapping) -> None:
        why = absent(tables)
        if why:
            errors[f"seasons.{name}"] = why
            return
        _guard(name, lambda: hyp.dev_seasons(stat, rows, g1=ISSUED, **SEASONS[name][1]),
               D["seasons"])

    # coverage per assessable DEV origin-year
    for name, (table, rows) in _coverage_rows(dev).items():
        why = absent({table: rows})
        if why:
            errors[f"coverage.{name}"] = why
        else:
            _guard(name, lambda rows=rows: hyp.dev_origin_years(rows, "cov90").assign(g1=ISSUED),
                   D["coverage"])

    # winter-h3 statistics per DEV season
    h1_t = {f"raw_{k}_provider_asof": dev(f"raw_{k}_provider_asof") for k in H1_KEYS}
    season("h1", _h1_stat, _cat(h1_t.values()), h1_t)
    h3_t = {**{f"cal_f_{k}_{lv}": dev(f"cal_f_{k}_{lv}") for k in G1_BASES for lv in LEVELS},
            **{f"mint_{k}": dev(f"mint_{k}") for k in G1_BASES}}
    h3_in = {**{(k, "base"): _cat([h3_t[f"cal_f_{k}_{lv}"] for lv in LEVELS]) for k in G1_BASES},
             **{(k, "mint"): h3_t[f"mint_{k}"] for k in G1_BASES}}
    season("h3", _h3_stat, h3_in, h3_t)
    h4_t, h4_in = {}, {}
    for k in H4_KEYS:
        for mode in MODES:
            t = ("raw_b1_provider_asof_seeded" if (k, mode) == ("b1", "asof")
                 else f"raw_{k}_provider_{mode}")
            h4_t[t] = h4_in[(k, mode)] = dev(t)
    season("h4", _h4_stat, h4_in, h4_t)
    season("h4_original", _h4o_stat, h4_in, h4_t)

    # F2 over every DEV origin, and its winter-h3 WIS per season
    f2_t, f2_scored = {}, {}
    for label, (kind, key) in F2_CONTENDERS.items():
        parts = [f"cal_f_{key}_{lv}" for lv in LEVELS] if kind == "cal_f" else [f"mint_{key}"]
        f2_t.update({p: dev(p) for p in parts})
        f2_scored[label] = _cat([f2_t[p] for p in parts])
    f2_contenders = {label: contenders[label] for label in f2_scored}
    if dev("m2") is None:
        errors["f2.m2"] = f"{ABSENT} (m2__dev): {F2_M2} left out of the DEV F2"
    elif "m2_dev" not in S.s4.names():
        errors["f2.m2"] = (f"not computed: {F2_M2}'s DEV forecasts are not in the step-4 store "
                           "(m2_dev): left out of the DEV F2")
    else:
        f2_scored[F2_M2], f2_contenders[F2_M2] = dev("m2"), S.s4.load("m2_dev")
    why = absent(f2_t)
    if why:
        errors["f2"] = why
    else:
        dev_ix = {ts(o) for o in DEV}
        origins = [o for o in _origins_in(f2_scored) if o in dev_ix]
        _guard("f2", lambda: hyp.f2(f2_contenders, f2_scored, icb_of, region_of, origins,
                                    failed=failed), D)

    season("f2_wis", _f2_wis_stat, f2_scored, f2_t)

    # H4b's DEV side: shown side by side, no range and no verdict (§7.10)
    if "h4b_dev" in S.s4.names():
        new = {ts(o) for o in new_origins}
        dev_o = [o for o in DEV if ts(o) not in new]
        comp = S.s4.load("h4b_dev")
        _guard("h4b", lambda: hyp.h4b_dev(comp, dev_o), D)
    else:
        errors["h4b"] = ("not computed: H4b's DEV components are not in the step-4 store "
                         "(h4b_dev)")

    for group in ("coverage", "seasons"):
        errors.update({f"{group}.{k}": v for k, v in D[group].pop("_errors", {}).items()})
    errors.update(D.pop("_errors", {}))
    if errors:
        D["_errors"] = errors
    return D


# ---- winter-h3 statistics, the same on both sides (§7.13) --------------------------------
def _long(t: pd.DataFrame, keys, col: str) -> pd.DataFrame:
    """A result table in the long form the DEV seasons use: key columns, stat, value."""
    out = t[list(keys)].reset_index(drop=True)
    return out.assign(stat=col, value=pd.to_numeric(t[col], errors="coerce").to_numpy(float))


def _origins_in(rows) -> list:
    """Every origin in a frame, or in a dict of frames (a DEV season's origins)."""
    frames = rows.values() if isinstance(rows, Mapping) else [rows]
    return sorted(set().union(*(set(pd.to_datetime(f["origin"])) for f in frames
                                if f is not None)))


def _conf_tagged(t: pd.DataFrame, origins, name: str) -> pd.DataFrame:
    """A CONF statistic's long table with its slice in front, as dev_seasons tags DEV's."""
    return _front(t, {**hyp.slice_tags(origins), "months": "winter", "horizons": "3",
                      "g1": ISSUED, **SEASONS[name][1]})


def _h1_stat(rows: pd.DataFrame, origins=None) -> pd.DataFrame:
    """H1's rel per tested model (default M1 and, when present, M1 v3 raw) and target, at
    ``origins`` (default: every origin in ``rows``, a DEV season)."""
    o = _origins_in(rows) if origins is None else origins
    t = hyp.h1(rows, o, loo=False, alongside=NAMES["m1_v3_raw"] in set(rows["model"]))["table"]
    return _long(t, SEASONS["h1"][0], "rel")


def _h3_stat(frames: dict, origins=None) -> pd.DataFrame:
    """H3's rel (MinT against base) per base and level."""
    o = _origins_in(frames) if origins is None else origins
    return _long(hyp.h3(frames, o, loo=False)["table"], SEASONS["h3"][0], "rel")


def _h4_stat(frames: dict, origins=None) -> pd.DataFrame:
    """H4's rel (final against as-of) per model and target."""
    o = _origins_in(frames) if origins is None else origins
    return _long(hyp.h4(frames, o, loo=False)["table"], SEASONS["h4"][0], "rel")


def _h4o_stat(frames: dict, origins=None) -> pd.DataFrame:
    """H4-original's Δpp (rel of B0 -> model, final minus as-of) per model and target."""
    o = _origins_in(frames) if origins is None else origins
    t = hyp.h4_original(frames, o, hyp.h4(frames, o, loo=False))["table"]
    return _long(t, SEASONS["h4_original"][0], "delta_pp")


def _f2_wis_stat(scored: dict, origins=None) -> pd.DataFrame:
    """F2's winter-h3 WIS rel against M1 + pooled per contender, level and target, with the
    geometric mean over targets (§7.12)."""
    o = _origins_in(scored) if origins is None else origins
    return _long(hyp.f2_wis(scored, o), SEASONS["f2_wis"][0], "rel")


# ---- CONF against DEV's range (§7.13, plan §5) -------------------------------------------
def _tags(t: pd.DataFrame, cols) -> dict:
    """The columns of ``t`` among ``cols`` that hold one value: its slice."""
    return {c: t[c].iloc[0] for c in cols
            if c in t.columns and len(t) and t[c].nunique(dropna=False) == 1}


def _season_flags(conf: pd.DataFrame, dev: pd.DataFrame | None, keys, absent: str) -> pd.DataFrame:
    """hyp.dev_flags on the statistic's keys, with the CONF value's slice in front."""
    t = hyp.dev_flags(conf, dev, keys=(*keys, "stat"), absent=absent)
    return _front(t, _tags(conf, [c for c in conf.columns if c not in (*keys, "stat", "value")]))


def _coverage_flags(cells: pd.DataFrame, dev: pd.DataFrame | None, pooled, absent: str
                    ) -> pd.DataFrame:
    """hyp.dev_coverage_flags, with the CONF cells' slice (model, stat, G1 variant) in front."""
    return _front(hyp.dev_coverage_flags(cells, dev, pooled, absent=absent),
                  _tags(cells, COVERAGE_TAGS))


def _outside(t: pd.DataFrame, keys) -> dict:
    """How many rows of a flag table are outside DEV's range, and which; how many are not
    flagged (None, with their reason in the table)."""
    none = t["outside"].isna().to_numpy()
    out = np.array([not pd.isna(x) and bool(x) for x in t["outside"]], dtype=bool)
    return {"n": len(t), "n_outside": int(out.sum()), "n_unflagged": int(none.sum()),
            "flagged": [" ".join(str(r[k]) for k in keys) for _, r in t[out].iterrows()]}


def dev_compare(conf: Mapping, cells: Mapping, pooled: Mapping, D: Mapping) -> dict:
    """Each registered CONF value against DEV's range (§7.13): a winter-h3 statistic in
    ``conf`` (long, tagged; the DEV seasons' keys) against [min, max] over DEV's in-range
    seasons, the 2023/24 fragment left out; each CONF origin-year cell in ``cells`` against
    DEV's minimum and maximum at its horizon, with ``pooled``'s CONF19 value beside it. A
    range whose DEV table is absent keeps its CONF rows, flagged None with the reason; a
    missing CONF value is an ``_errors`` entry. "outside" holds each table's counts."""
    F: dict = {}
    errors: dict = {}
    dev_errors = D.get("_errors") or {}

    def no_dev(group: str, name: str) -> str:
        return f"no DEV range: {dev_errors.get(f'{group}.{name}', 'DEV table absent')}"

    for name, (keys, _) in SEASONS.items():
        if name not in conf:
            errors[name] = f"no CONF value: {(conf.get('_errors') or {}).get(name, 'not computed')}"
            continue
        dev = (D.get("seasons") or {}).get(name)
        _guard(name, lambda name=name, keys=keys, dev=dev: _season_flags(
            conf[name], dev, keys, no_dev("seasons", name)), F)
    if isinstance(F.get("f2_wis"), pd.DataFrame):          # M1 + pooled against itself
        t = F["f2_wis"]
        ref = (t["model"] == stage_f.F2_REFERENCE).to_numpy()
        t["outside"] = t["outside"].astype(object)
        t.loc[ref, "outside"], t.loc[ref, "reason"] = None, SELF
    for name in COVERAGE:
        key = f"coverage_{name}"
        if name not in cells:
            errors[key] = f"no CONF cells: {(cells.get('_errors') or {}).get(name, 'not computed')}"
            continue
        dev = (D.get("coverage") or {}).get(name)
        _guard(key, lambda name=name, dev=dev: _coverage_flags(
            cells[name], dev, pooled.get(name), no_dev("coverage", name)), F)
    F["outside"] = {name: _outside(t, (*SEASONS[name][0], "stat") if name in SEASONS
                                   else ("oyear", "horizon"))
                    for name, t in F.items() if isinstance(t, pd.DataFrame)}
    errors.update(F.pop("_errors", {}))
    if errors:
        F["_errors"] = errors
    return F
