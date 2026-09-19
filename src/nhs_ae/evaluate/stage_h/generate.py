"""Stage H step 3: every forecast, with no guarded call (design §2.1, §2.9, §4, §8).

CONTRACT (skeleton; the implementation must keep these signatures):

harness_block(ctx, model_keys, level, modes, origins) -> dict[tuple[str, str, str], Path]
    harness.generate_forecasts([MODELS[k]() ...], vintages, BacktestConfig(origins, modes,
    levels=(level,)), jobs=ctx.jobs, vintages_path=ctx.vintages_path); one parquet per
    (model_key, level, mode) under ctx.work/"forecasts".
aggregate_block(ctx, origins) -> dict[tuple[str, str, str], Path]
    Region and England for b1, b2, m1_v3_raw via stage_f._init(ctx.vintages_path, ...) and
    stage_f._agg_task, as-of.
fit_m2(ctx, origins, force_retry=frozenset()) -> tuple[Path, DataFrame]
    m2d_corr per origin through stage_e._init(ctx.vintages_path) and
    stage_e._fit_origin(..., shift): 3 workers x 4 cores, seeds year*100+month and month;
    one retry with shift 1000 on an exception; BrokenProcessPool / KeyboardInterrupt
    re-raised; returns the forecast file and the fits table (origin, attempt, shift,
    fit_seed, pred_seed, seconds, rhat_max, ess_bulk_min, ess_tail_min, divergences,
    worst_rhat_param, failed, error). ``force_retry``: origins whose first attempt is made
    to fail (dry run only, to exercise the retry path).
generate(ctx, *, vintage_sha) -> dict[tuple[str, str, str], Path]      every block of design
    §4. ``vintage_sha`` (the table's SHA-256 recorded when step 2 checked its row hash against
    the pin) is required: without it ``generate`` refuses.
qa(files, ctx, fits=None) -> DataFrame   counts, NaNs, negatives, crossed, all-zero, key sets
                                      (M2's too), horizon -> period; nothing that needs an
                                      outturn. ``fits``: the M2 fits table (default
                                      ctx.work/m2_fits.csv, if there).
forecast_hashes(files) -> DataFrame   file, sha256, row_hash, rows, origins.
d7_check(files) -> DataFrame          2025-08/09 against 2025-07 (run mode only).
p13_check(files, quarantine_file) -> DataFrame   values-only comparison (run mode only).
hash_commit(ctx, tables) -> str       write results/H-confirmatory/{HASH_FILES} (dry run:
                                      results/H-dryrun/<head>/), commit them with hooks
                                      disabled, return the new HEAD (H1).
dev_side(out_dir, jobs, vintages_path) -> dict   ``prepare --dev-side`` (through
                                      ``checks.prepare_inputs``): the DEV forecasts of design §8,
                                      on the P4 rebuild at ``vintages_path``.

How the contract is met:
- Every pool is made here (``_pool``), with the harness's, Stage F's and Stage E's own worker
  functions wrapped: each initialiser installs the tripwires, loads the table through the
  original initialiser, and hashes the file it loaded (before and after the load); every task
  returns that hash, and the parent checks it against the table's SHA-256 recorded when step 2
  checked the row hash against the pin (§2.9). An M2 fit must also report the seed shift it
  was given. The code path of each forecast is unchanged: ``harness._run_task``,
  ``stage_f._agg_task``, ``stage_e._fit_origin``. ``harness.generate_forecasts``,
  ``stage_f.generate`` and ``stage_e.run_rung`` are not called: their pools cannot carry the
  tripwires or the hash, and the last two read caches and the shared vintage table.
- The parent runs every step-3 function inside ``tripwires()`` (§2.1).
- Region and England come only from ``aggregate_block`` (the Stage F hierarchy); the M2 file
  holds all three of its levels and is keyed ("m2", "all", "asof").
"""

from __future__ import annotations

import importlib
import inspect
import logging
import os
import subprocess
import sys
import time
import types
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from contextlib import contextmanager
from datetime import date
from functools import wraps
from multiprocessing import get_context
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from nhs_ae.evaluate import harness, stage_e, stage_f
from nhs_ae.evaluate.asof import load_asof, load_vintages
from nhs_ae.evaluate.harness import KEYS, BacktestConfig
from nhs_ae.evaluate.seed_stability import MEDIAN_LIMIT, P95_LIMIT
from nhs_ae.evaluate.splits import split_origins
from nhs_ae.evaluate.stage_h.common import (
    CONF21,
    D7_FOLD,
    DEV,
    DEV_SIDE_ORIGINS,
    DEV_WINTER_H3,
    G1_BASES,
    H4_MODELS,
    HASH_FILES,
    NAMES,
    PROVIDER_MODELS,
    Context,
    file_sha,
    row_hash,
    ts,
)
from nhs_ae.features.hierarchy import current_region_map, icb_region_map
from nhs_ae.models import MODELS, m2
from nhs_ae.models.base import HORIZONS, QUANTILES

log = logging.getLogger(__name__)

COLS = stage_f.COLS                      # the forecast table contract, in order
FORECASTS = "forecasts"                  # ctx.work / FORECASTS: every step-3 forecast file
M2_JOBS, M2_CORES, M2_DRAWS, M2_TUNE = 3, 4, 1000, 1000   # frozen settings (plan §6)
RETRY_SHIFT = 1000                       # the one retry: both seeds + 1,000
DRY_FORCED_RETRY = date(2023, 8, 1)      # design §10 (not in common.py)
DIAG = ("rhat_max", "ess_bulk_min", "ess_tail_min", "divergences", "worst_rhat_param")
M2_TARGETS = ("att_type1", "att_all", "adm_via_ae")   # stage_e.panels_at's panels, M2's targets
M2_LEVELS = ("icb", "region", "england")
GROUP = ["model", "level", "mode", "origin", "target"]
P13_KEYS = ["origin", "mode", "target", "series", "horizon", "period", "quantile"]
P13_EXPECTED = {"b1": "differs: B1 is now seeded", "asof": "identical",
                "final": "identical unless the archive changed"}


# ---- tripwires (design §2.1) -------------------------------------------------------------
class SealTripwire(BaseException):
    """A step-3 call that reads outturns, first releases or scores, or plots (design §2.1). A
    BaseException, so neither a model's ``except Exception`` nor the M2 retry can absorb it."""


TRIPWIRES: dict[str, tuple[str, ...] | None] = {     # None: every function the module defines
    "nhs_ae.evaluate.asof": ("load_truth",),
    "nhs_ae.evaluate.harness": ("truth_long", "score_forecasts", "score_against_truth"),
    "nhs_ae.evaluate.metrics": ("score_rows", "pinball", "wis_interval_form", "pit", "summarise",
                                "paired_bootstrap"),
    "nhs_ae.evaluate.splits": ("assert_not_sealed",),
    "nhs_ae.evaluate.stage_e": ("icb_truth", "agg_truth", "score"),
    "nhs_ae.evaluate.stage_f": ("truth_all", "first_release_level", "_median_errors", "score"),
    "nhs_ae.calibrate.online": ("first_release", "calibrate"),
    "nhs_ae.calibrate.g1": ("last_observed", "mark"),
    "nhs_ae.evaluate.audit": None,
}


def _stub(label: str):
    def tripped(*args, **kwargs):
        raise SealTripwire(f"{label} called during step 3 (design §2.1)")
    tripped.tripwire = label
    return tripped


def _swap(swaps: dict[int, tuple]) -> None:
    """In every loaded ``nhs_ae`` module, replace each attribute that is some ``swaps`` entry's
    first object by its second (so ``from x import f`` aliases are covered too)."""
    for mod in list(sys.modules.values()):
        if isinstance(mod, types.ModuleType) and mod.__name__.split(".")[0] == "nhs_ae":
            for attr, val in list(vars(mod).items()):
                hit = swaps.get(id(val))
                if hit is not None and hit[0] is val:
                    setattr(mod, attr, hit[1])


def install_tripwires():
    """Make every function in ``TRIPWIRES``, each alias of it in a loaded ``nhs_ae`` module,
    and matplotlib's ``Figure`` raise ``SealTripwire``. Idempotent. Returns the function that
    undoes this call (worker processes never call it)."""
    swaps = {}
    for name, attrs in TRIPWIRES.items():
        mod = importlib.import_module(name)
        if attrs is None:
            attrs = [a for a, f in vars(mod).items()
                     if inspect.isfunction(f) and f.__module__ == name]
        for a in attrs:
            f = getattr(mod, a)
            if not hasattr(f, "tripwire"):
                swaps[id(f)] = (f, _stub(f"{name}.{a}"))
    _swap(swaps)
    figure = None
    try:
        from matplotlib.figure import Figure
    except ImportError:
        Figure = None
    if Figure is not None and not hasattr(Figure.__init__, "tripwire"):
        figure = Figure.__init__
        Figure.__init__ = _stub("matplotlib.figure.Figure")

    def undo() -> None:
        _swap({id(s): (s, f) for f, s in swaps.values()})
        if figure is not None:
            Figure.__init__ = figure
    return undo


@contextmanager
def tripwires():
    """The parent's step-3 tripwires, removed on exit (step 4 needs those functions)."""
    undo = install_tripwires()
    try:
        yield
    finally:
        undo()


def _step3(fn):
    @wraps(fn)
    def run(*args, **kwargs):
        with tripwires():
            return fn(*args, **kwargs)
    return run


# ---- workers (design §2.1, §2.9) ---------------------------------------------------------
_WORKER: dict = {}
CHANGED = "changed while loading"


def _load(init, vpath, *args) -> None:
    """Run a worker's own initialiser on ``vpath`` and keep the SHA-256 of the file it loaded,
    taken before and after the load, so a file replaced meanwhile cannot pass (design §2.9)."""
    before = file_sha(vpath)
    init(vpath, *args)
    _WORKER["sha"] = before if file_sha(vpath) == before else CHANGED


def _harness_init(vpath, models, cfg):
    install_tripwires()
    _load(harness._init_worker, vpath, models, cfg)


def _harness_task(task):
    return harness._run_task(task), _WORKER["sha"]


def _agg_init(vpath, models):
    """``stage_f._init`` with the models built in the parent, as the harness path passes them
    (the same registry and constructors; it lets a test inject stub models)."""
    install_tripwires()
    _load(stage_f._init, vpath, ())
    stage_f._W["models"] = list(models)


def _agg_task(origin):
    return stage_f._agg_task(origin), _WORKER["sha"]


def _m2_init(vpath):
    install_tripwires()
    _load(stage_e._init, vpath)


def _m2_task(fit, args, shift, force_fail):
    """One fit attempt. An Exception is a fit failure, returned as a result; anything else
    (KeyboardInterrupt, SealTripwire) propagates as a crash."""
    t0 = time.perf_counter()
    try:
        if force_fail:
            raise RuntimeError("first attempt failed on purpose (dry-run retry check)")
        fc, diag = fit(args, shift=shift)
    except Exception as e:  # noqa: BLE001 - a failed fit is a result, recorded as such
        first = (str(e).splitlines() or [""])[0]      # later lines can print fitted values
        return {"ok": False, "error": f"{type(e).__name__}: {first}"[:200],
                "seconds": time.perf_counter() - t0, "sha": _WORKER["sha"]}
    return {"ok": True, "fc": fc, "diag": diag, "seconds": time.perf_counter() - t0,
            "sha": _WORKER["sha"]}


@contextmanager
def _pool(ctx: Context, workers: int, initializer, initargs: tuple):
    """Every step-3 pool: spawned workers whose initargs start with the run's vintage path
    (§2.9); on any exit the queued tasks are cancelled."""
    if Path(initargs[0]) != Path(ctx.vintages_path):
        raise ValueError("a step-3 pool must load the run's vintage table (design §2.9)")
    pool = ProcessPoolExecutor(max_workers=max(1, workers), mp_context=get_context("spawn"),
                               initializer=initializer, initargs=initargs)
    try:
        yield pool
    finally:
        pool.shutdown(wait=True, cancel_futures=True)


STEP2_SHA = "the vintage table's SHA-256 recorded when step 2 checked its row hash against the pin"


def _expected_sha(ctx: Context, vintage_sha: str | None) -> str:
    """The SHA-256 every worker hash must equal (§2.9): step 2's. Only a block called on its own
    outside run mode (a test) may take it from the file as it is now."""
    if vintage_sha is not None:
        return vintage_sha
    if ctx.mode == "run":
        raise ValueError(f"run mode needs {STEP2_SHA} (design §2.9)")
    return file_sha(ctx.vintages_path)


def _check_shas(shas, expected: str, block: str) -> None:
    bad = set(shas) - {expected}
    if bad:
        raise RuntimeError(f"{block}: {len(bad)} worker hash(es) differ from the run's vintage "
                           "table (design §2.9)")


# ---- files -------------------------------------------------------------------------------
def forecast_path(ctx: Context, key: str, level: str, mode: str) -> Path:
    return ctx.work / FORECASTS / f"{key}_{level}_{mode}.parquet"


def _refuse(paths) -> None:
    there = [str(p) for p in paths if Path(p).exists()]
    if there:
        raise FileExistsError(f"step 3 never overwrites its outputs: {there[:3]}")


def _write(frame: pd.DataFrame, path: Path) -> None:
    _refuse([path])
    path.parent.mkdir(parents=True, exist_ok=True)
    frame[COLS].to_parquet(path, index=False)


def _origins(ctx: Context, origins) -> list[date]:
    origins = list(origins)
    if not origins or max(ts(o) for o in origins) > ts(ctx.end):
        raise ValueError(f"step 3 needs origins, none after E = {ctx.end:%Y-%m} (design §2.4)")
    return origins


# ---- blocks (design §4) ------------------------------------------------------------------
@_step3
def harness_block(ctx: Context, model_keys, level: str, modes, origins, *,
                  vintage_sha: str | None = None) -> dict[tuple[str, str, str], Path]:
    """Provider or ICB forecasts, one file per (model_key, level, mode), through the harness's
    worker functions. ``vintage_sha``: step 2's SHA-256 of the table (outside run mode, default:
    taken now)."""
    if level not in ("provider", "icb"):
        raise ValueError(f"{level!r}: region and England come from aggregate_block")
    origins = _origins(ctx, origins)
    expected = _expected_sha(ctx, vintage_sha)
    models = [MODELS[k]() for k in model_keys]
    names = dict(zip(model_keys, (m.name for m in models)))
    if len(set(names.values())) != len(names):
        raise ValueError(f"model keys {list(model_keys)} share a model name")
    paths = {(k, level, m): forecast_path(ctx, k, level, m) for k in model_keys for m in modes}
    _refuse(paths.values())
    cfg = BacktestConfig(origins=origins, modes=tuple(modes), levels=(level,))
    tasks = [(o, m) for o in cfg.origins for m in cfg.modes]
    initargs = (ctx.vintages_path, models, cfg)
    with _pool(ctx, min(ctx.jobs, len(tasks)), _harness_init, initargs) as pool:
        out = list(pool.map(_harness_task, tasks))
    _check_shas([s for _, s in out], expected, f"{level} block")
    fc = pd.concat([f for f, _ in out], ignore_index=True)
    for (k, _, m), path in paths.items():
        _write(fc[(fc["model"] == names[k]) & (fc["mode"] == m)], path)
    log.info("%s %s: %d tasks, %d forecast rows", level, "+".join(model_keys), len(tasks),
             len(fc))
    return paths


@_step3
def aggregate_block(ctx: Context, origins, *,
                    vintage_sha: str | None = None) -> dict[tuple[str, str, str], Path]:
    """Region and England base forecasts (b1, b2, m1_v3_raw), as-of, from the Stage F
    hierarchy (``stage_f.SummedView``) through ``stage_f._agg_task``."""
    origins = _origins(ctx, origins)
    expected = _expected_sha(ctx, vintage_sha)
    keys = stage_f.BASE_MODELS
    models = [MODELS[k]() for k in keys]
    names = dict(zip(keys, (m.name for m in models)))
    paths = {(k, lv, "asof"): forecast_path(ctx, k, lv, "asof")
             for k in keys for lv in stage_f.AGG_LEVELS}
    _refuse(paths.values())
    with _pool(ctx, min(ctx.jobs, len(origins)), _agg_init, (ctx.vintages_path, models)) as pool:
        out = list(pool.map(_agg_task, origins))
    _check_shas([s for _, s in out], expected, "aggregate block")
    fc = pd.concat([f for f, _ in out], ignore_index=True)
    for (k, lv, _), path in paths.items():
        _write(fc[(fc["model"] == names[k]) & (fc["level"] == lv)], path)
    log.info("region+england %s: %d origins, %d forecast rows", "+".join(keys), len(origins),
             len(fc))
    return paths


def _fit_row(origin, attempt: int, shift: int, r: dict) -> dict:
    o, diag = ts(origin), r.get("diag") or {}
    return {"origin": o, "attempt": attempt, "shift": shift,
            "fit_seed": o.year * 100 + o.month + shift, "pred_seed": o.month + shift,
            "seconds": round(r["seconds"], 1), **{k: diag.get(k, np.nan) for k in DIAG},
            "failed": not r["ok"], "error": r.get("error", "")}


@_step3
def fit_m2(ctx: Context, origins, force_retry=frozenset(), *,
           vintage_sha: str | None = None) -> tuple[Path, pd.DataFrame]:
    """``m2d_corr`` at every origin under the plan's fit policy (§6): an exception gets one retry
    with both seeds + 1,000; a second makes the origin failed and its rows absent. A broken
    pool, an interrupt or a tripwire is a crash, and so is a fit whose diagnostics report a
    shift other than the one it was given (its seeds would not be those the table records).
    ``seconds``: the attempt's time in its worker."""
    origins = _origins(ctx, origins)
    force = {ts(o) for o in force_retry}
    if force and ctx.mode == "run":
        raise ValueError("force_retry is for the dry run only")
    if not force <= {ts(o) for o in origins}:
        raise ValueError("force_retry names an origin that is not being fitted")
    path = forecast_path(ctx, "m2", "all", "asof")
    _refuse([path])
    expected = _expected_sha(ctx, vintage_sha)
    rung, fit = m2.M2D_CORR, stage_e._fit_origin      # looked up now, so a stub reaches workers
    if "shift" not in inspect.signature(fit).parameters:   # else every fit would "fail" twice
        raise TypeError("stage_e._fit_origin takes no shift: the retry rule cannot be applied")
    rows, frames, shas = [], {}, []
    omp = "OMP_NUM_THREADS" not in os.environ
    if omp:
        os.environ["OMP_NUM_THREADS"] = "1"             # for the workers, as stage_e.run_rung
    try:
        workers = min(M2_JOBS, ctx.jobs, len(origins))
        with _pool(ctx, workers, _m2_init, (ctx.vintages_path,)) as pool:
            todo = [(o, 0) for o in origins]
            pending = {}
            while todo or pending:
                for o, attempt in todo:
                    args = (o, rung, M2_DRAWS, M2_TUNE, M2_CORES)
                    fut = pool.submit(_m2_task, fit, args, attempt * RETRY_SHIFT,
                                      attempt == 0 and ts(o) in force)
                    pending[fut] = (o, attempt)
                todo = []
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for fut in done:
                    o, attempt = pending.pop(fut)
                    r = fut.result()    # BrokenProcessPool, KeyboardInterrupt, SealTripwire: raised
                    shift = attempt * RETRY_SHIFT
                    if r["ok"] and (r["diag"] or {}).get("shift") != shift:
                        raise RuntimeError(f"m2 {o:%Y-%m} attempt {attempt} was given shift {shift} "
                                           f"but reports {(r['diag'] or {}).get('shift')!r}: its "
                                           "seeds are not those m2_fits.csv would record")
                    shas.append(r["sha"])
                    rows.append(_fit_row(o, attempt, shift, r))
                    if r["ok"]:
                        frames[ts(o)], d = r["fc"], r["diag"]
                        log.info("m2 %s attempt %d: %.0fs rhat %.3f ess %.0f div %d", f"{o:%Y-%m}",
                                 attempt, r["seconds"], d["rhat_max"], d["ess_bulk_min"],
                                 d["divergences"])
                    else:
                        log.error("m2 %s attempt %d failed: %s", f"{o:%Y-%m}", attempt, r["error"])
                        if attempt == 0:
                            todo.append((o, 1))
    finally:
        if omp:
            os.environ.pop("OMP_NUM_THREADS", None)
    _check_shas(shas, expected, "M2 block")
    fc = (pd.concat([frames[o] for o in sorted(frames)], ignore_index=True) if frames
          else pd.DataFrame(columns=[c for c in COLS if c not in ("mode", "model", "scale")]))
    fc = fc.assign(mode="asof", model=rung.name, scale=np.nan)
    fc["level"] = fc["level"].fillna("icb")
    _write(fc, path)
    fits = pd.DataFrame(rows).sort_values(["origin", "attempt"]).reset_index(drop=True)
    log.info("m2: %d of %d origins fitted, %d retried", len(frames), len(origins),
             int((fits["attempt"] == 1).sum()))
    return path, fits


def _nrows(path: Path) -> int:
    return pq.ParquetFile(path).metadata.num_rows


@_step3
def generate(ctx: Context, *, vintage_sha: str | None = None) -> dict[tuple[str, str, str], Path]:
    """Every block of design §4, one at a time, M2 last; writes ``m2_fits.csv`` and
    ``timings.csv`` to ``ctx.work``. In the dry run, M2's first attempt at 2023-08 is made to
    fail (design §10). ``vintage_sha``, required: the table's SHA-256 recorded when step 2
    checked its row hash against the pin. The file must still have it, and every worker's hash
    must equal it (§2.9)."""
    if vintage_sha is None:
        raise ValueError(f"generate needs {STEP2_SHA} (design §2.9)")
    if file_sha(ctx.vintages_path) != vintage_sha:
        raise RuntimeError(f"{ctx.vintages_path} is no longer the file step 2 checked (design §2.9)")
    sides = [ctx.work / "m2_fits.csv", ctx.work / "timings.csv"]
    _refuse(sides)
    if any((ctx.work / FORECASTS).glob("*")):
        raise FileExistsError(f"{ctx.work / FORECASTS} is not empty: step 3 starts from nothing")
    sha, new = vintage_sha, ctx.new_origins
    blocks = [(f"provider {k}", harness_block, (ctx, (k,), "provider", ("asof", "final"), new))
              for k in PROVIDER_MODELS]
    blocks += [("icb", harness_block, (ctx, G1_BASES, "icb", ("asof",), new)),
               ("region+england", aggregate_block, (ctx, new))]
    force = frozenset({DRY_FORCED_RETRY} & set(new)) if ctx.mode == "dry" else frozenset()
    files, timings, fits = {}, [], None
    for block, fn, args in [*blocks, ("m2", fit_m2, (ctx, new, force))]:
        t0 = time.perf_counter()
        out = fn(*args, vintage_sha=sha)
        if block == "m2":
            out, fits = {("m2", "all", "asof"): out[0]}, out[1]
        files.update(out)
        timings.append({"block": block, "files": ";".join(p.name for p in out.values()),
                        "rows": sum(_nrows(p) for p in out.values()),
                        "seconds": round(time.perf_counter() - t0, 1), "jobs": ctx.jobs,
                        "vintage_sha": sha})
    fits.to_csv(sides[0], index=False)
    pd.DataFrame(timings).to_csv(sides[1], index=False)
    return files


@_step3
def step3_tables(ctx: Context, files: dict) -> dict[str, pd.DataFrame]:
    """The four tables of the hash commit (design §4), keyed by ``HASH_FILES``."""
    hashes, fits = forecast_hashes(files), pd.read_csv(ctx.work / "m2_fits.csv")
    return dict(zip(HASH_FILES, (hashes, fits, pd.read_csv(ctx.work / "timings.csv"),
                                 qa(files, ctx, fits))))


# ---- QA and hashes (design §4) -----------------------------------------------------------
def _month_number(s) -> np.ndarray:
    s = pd.to_datetime(pd.Series(s))
    return (s.dt.year * 12 + s.dt.month).to_numpy()


class _Facts:
    """The as-of data at each (origin, mode), loaded once: the training end month, the series
    the harness forecasts (seen in the last 12 months of a panel long enough to fit), and the
    series M2 forecasts."""

    def __init__(self, vintages_path):
        self.v = load_vintages(vintages_path)
        self.region_map, self.regions = current_region_map(self.v), icb_region_map()
        cfg = BacktestConfig()
        self.min_train, self.targets = cfg.min_train_months, cfg.targets
        self._data, self._active, self._m2 = {}, {}, {}

    def data(self, origin, mode):
        key = (ts(origin), mode)
        if key not in self._data:
            self._data[key] = load_asof(key[0].date(), mode, self.v, self.region_map)
        return self._data[key]

    def end(self, origin, mode) -> pd.Timestamp:
        return self.data(origin, mode).last_period

    def active(self, origin, mode, level, target) -> frozenset:
        key = (ts(origin), mode, level, target)
        if key not in self._active:
            d = self.data(origin, mode)
            src = stage_f.SummedView(d, self.regions) if level in stage_f.AGG_LEVELS else d
            p = src.panel(target, level)
            seen = p.iloc[-12:].notna().any()
            self._active[key] = (frozenset() if len(p) < self.min_train
                                 else frozenset(seen[seen].index))
        return self._active[key]

    def m2_series(self, origin, level) -> frozenset:
        """M2's series at ``origin``: the ICBs in all three as-of ICB panels bar ``m2.EXCLUDE``
        (``m2.prepare``), their regions (``m2.aggregate_forecast``), and England."""
        o = ts(origin)
        if o not in self._m2:
            d = self.data(o, "asof")
            icbs = sorted(set.intersection(*(set(d.panel(t, "icb").columns) for t in M2_TARGETS))
                          - set(m2.EXCLUDE))
            self._m2[o] = {"icb": frozenset(icbs),
                           "region": frozenset(self.regions.reindex(icbs).fillna("?")),
                           "england": frozenset({"ENGLAND"})}
        return self._m2[o].get(level, frozenset())

    def owed(self, key: str, origin, mode, level, target) -> frozenset:
        """The series a file of model key ``key`` owes at one cell."""
        return (self.m2_series(origin, level) if key == "m2"
                else self.active(origin, mode, level, target))


def _cells(key: tuple, facts: _Facts) -> list[tuple[str, str]]:
    """The (level, target) cells a file owes at each origin."""
    return ([(lv, t) for lv in M2_LEVELS for t in M2_TARGETS] if key[0] == "m2"
            else [(key[1], t) for t in facts.targets])


def _qa_counts(key: tuple, f: pd.DataFrame, facts: _Facts) -> tuple[pd.DataFrame, dict]:
    """The QA row of every (model, level, mode, origin, target) cell a file holds, with the
    series it owes (``_Facts.owed``), and the key set of each harness cell."""
    f["origin"], f["period"] = pd.to_datetime(f["origin"]), pd.to_datetime(f["period"])
    dup = f.duplicated([*KEYS, "quantile"])
    g = f[~dup]
    w = g.set_index([*KEYS, "quantile"])["value"].unstack("quantile")
    stray_q = bool(set(w.columns) - set(QUANTILES))
    n_q = g.groupby(KEYS).size().reindex(w.index).to_numpy()
    v = w.reindex(columns=list(QUANTILES)).to_numpy(float)
    r = w.index.to_frame(index=False)
    with np.errstate(invalid="ignore"):
        r["nan"], r["neg"] = np.isnan(v).any(axis=1), (v < 0).any(axis=1)
        r["crossed"], r["zero"] = (np.diff(v, axis=1) < 0).any(axis=1), (v == 0).all(axis=1)
    r["incomplete"] = n_q != len(QUANTILES)
    ends = r[["origin", "mode"]].drop_duplicates()
    ends["end_month"] = [facts.end(o, m) for o, m in zip(ends["origin"], ends["mode"])]
    r = r.merge(ends, on=["origin", "mode"], how="left")
    r["bad_period"] = (_month_number(r["period"]) - r["horizon"].to_numpy()
                       != _month_number(r["end_month"]))
    hs = r.groupby([*GROUP, "series"])["horizon"].agg(["size", "nunique", "min", "max"])
    full = ((hs["size"] == len(HORIZONS)) & (hs["nunique"] == len(HORIZONS))
            & (hs["min"] == min(HORIZONS)) & (hs["max"] == max(HORIZONS)))
    t = r.groupby(GROUP).agg(forecasts=("series", "size"), series=("series", "nunique"),
                             nan_rows=("nan", "sum"), negative_rows=("neg", "sum"),
                             crossed_rows=("crossed", "sum"), all_zero_rows=("zero", "sum"),
                             incomplete=("incomplete", "sum"), bad_periods=("bad_period", "sum"),
                             end_month=("end_month", "first"))
    t["rows"] = f.groupby(GROUP).size().reindex(t.index)
    t["duplicate_rows"] = f.loc[dup].groupby(GROUP).size().reindex(t.index, fill_value=0)
    t["grid_ok"] = (full.groupby(level=GROUP).all().reindex(t.index) & (t["incomplete"] == 0)
                    & (t["duplicate_rows"] == 0) & (not stray_q))
    t["period_ok"] = t["bad_periods"] == 0
    counts, sigs = [], {}
    for k, gk in r.groupby(GROUP):                       # same order as t's index
        exp, obs = facts.owed(key[0], k[3], k[2], k[1], k[4]), frozenset(gk["series"])
        counts.append((len(exp), len(exp - obs), len(obs - exp)))
        if key[0] != "m2":                                # M2 is not a harness model
            sigs[(key[0], *k)] = frozenset(zip(gk["series"], gk["horizon"], gk["period"]))
    t[["expected_series", "missing_series", "extra_series"]] = np.array(counts, dtype=float)
    return t.reset_index().assign(absent=False, absent_by_rule=False), sigs


ABSENT = {"forecasts": 0, "series": 0, "nan_rows": 0, "negative_rows": 0, "crossed_rows": 0,
          "all_zero_rows": 0, "incomplete": 0, "bad_periods": 0, "rows": 0, "duplicate_rows": 0,
          "grid_ok": False, "period_ok": True, "extra_series": 0.0, "absent": True}


def _absent(key: tuple, model, facts: _Facts, origins, present: set,
            failed: set) -> tuple[list, dict]:
    """The cells a file owes and lacks at each of ``origins`` (``_cells``, where the owed set is
    not empty): their QA rows, ``absent_by_rule`` where M2's fit failed twice (plan §6), and an
    empty key set for each harness cell."""
    mode = key[2]
    rows, sigs = [], {}
    for o in map(ts, origins):
        for level, target in _cells(key, facts):
            if (o, level, target) in present:
                continue
            exp = facts.owed(key[0], o, mode, level, target)
            if exp:
                rows.append({"model": model, "level": level, "mode": mode, "origin": o,
                             "target": target, **ABSENT, "end_month": facts.end(o, mode),
                             "expected_series": float(len(exp)), "missing_series": float(len(exp)),
                             "absent_by_rule": key[0] == "m2" and o in failed})
                if key[0] != "m2":
                    sigs[(key[0], model, level, mode, o, target)] = frozenset()
    return rows, sigs


def _qa_file(key: tuple, path: Path, facts: _Facts, origins,
             failed: set) -> tuple[pd.DataFrame, dict]:
    f = pd.read_parquet(path)
    t, sigs = _qa_counts(key, f, facts) if len(f) else (pd.DataFrame(), {})
    present = set(zip(t["origin"], t["level"], t["target"])) if len(t) else set()
    model = f["model"].iloc[0] if len(f) else NAMES.get(key[0], np.nan)
    rows, gone = _absent(key, model, facts, origins, present, failed)
    if rows:
        gap = pd.DataFrame(rows)
        t = pd.concat([t, gap], ignore_index=True) if len(t) else gap
        t = t.sort_values(GROUP, kind="stable", ignore_index=True)
        sigs |= gone
    if t.empty:
        t = pd.DataFrame([{"rows": 0, "absent": False, "absent_by_rule": False}])
    t.insert(0, "model_key", key[0])
    t.insert(0, "file", path.name)
    return t, sigs


def _failed_twice(fits: pd.DataFrame | None) -> set:
    """The origins whose M2 fit failed at both attempts (the plan's §6 rule: rows absent)."""
    if fits is None or fits.empty:
        return set()
    gone = (fits["attempt"] == 1) & fits["failed"].astype(bool)
    return {ts(o) for o in pd.to_datetime(fits.loc[gone, "origin"])}


@_step3
def qa(files: dict, ctx: Context, fits: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per (file, model, level, mode, origin, target): rows, forecasts, series (and the
    set owed: a harness model's active series, or M2's ICBs, their regions and England, as
    ``m2.prepare`` and ``m2.aggregate_forecast`` form them), the counts of NaN, negative,
    crossed and all-zero forecasts, duplicates and incomplete grids, and the horizon -> period
    rule (period - h is the as-of end month, which truncation moves back). ``absent``: a cell
    a file owed and lacks (every file owes each origin of ``ctx.new_origins``: a harness file
    each target whose panel has active series, M2's each level and target). ``absent_by_rule``:
    an absent M2 cell at an origin whose fit failed twice, by ``fits`` (default:
    ``ctx.work/m2_fits.csv`` if it exists; without it, no cell is absent by rule).
    ``keys_match``: the (series, horizon, period) set is identical across the harness models
    of that level, mode, origin and target, an absent cell counting as empty (None for M2).
    Reads forecasts and the vintage table's as-of slices; no outturn."""
    if fits is None and (ctx.work / "m2_fits.csv").is_file():
        fits = pd.read_csv(ctx.work / "m2_fits.csv")
    failed = _failed_twice(fits)
    facts = _Facts(ctx.vintages_path)
    parts, sigs = [], {}
    for key, path in sorted(files.items()):
        t, s = _qa_file(key, Path(path), facts, ctx.new_origins, failed)
        parts.append(t)
        sigs.update(s)
    table = pd.concat(parts, ignore_index=True)
    cell: dict = {}
    for (_, _, level, mode, origin, target), sig in sigs.items():
        cell.setdefault((level, mode, origin, target), set()).add(sig)
    at = table[["model_key", "level", "mode", "origin", "target", "absent"]].itertuples(index=False)
    table["keys_match"] = [None if k == "m2" or pd.isna(lv)
                           else not gone and len(cell[(lv, md, o, t)]) == 1
                           for k, lv, md, o, t, gone in at]
    return table


@_step3
def forecast_hashes(files: dict) -> pd.DataFrame:
    """Per file: its key, name, SHA-256, canonical row hash, row count and origins (YYYY-MM;
    ";"-joined), in key order."""
    rows = []
    for (key, level, mode), path in sorted(files.items()):
        f = pd.read_parquet(path)
        origins = pd.DatetimeIndex(pd.to_datetime(f["origin"]).unique()).sort_values()
        rows.append({"model_key": key, "level": level, "mode": mode, "file": Path(path).name,
                     "sha256": file_sha(path), "row_hash": row_hash(f), "rows": len(f),
                     "origins": ";".join(origins.strftime("%Y-%m"))})
    t = pd.DataFrame(rows)
    if t["file"].duplicated().any():
        raise ValueError("two forecast files share a name")
    return t


# ---- D7 and P13 (design §4) --------------------------------------------------------------
def _join(a: pd.DataFrame, b: pd.DataFrame, keys: list[str]) -> tuple[pd.DataFrame, dict]:
    """Outer join of two forecast frames on ``keys``: the rows in both, and the counts."""
    j = a[[*keys, "value"]].merge(b[[*keys, "value"]], on=keys, how="outer",
                                  suffixes=("_a", "_b"), indicator=True)
    both = j[j["_merge"] == "both"]
    nan_a, nan_b = both["value_a"].isna(), both["value_b"].isna()
    both = both.assign(ok=~nan_a & ~nan_b, abs_diff=(both["value_b"] - both["value_a"]).abs())
    return both, {"n_a": len(a), "n_b": len(b), "n_both": len(both),
                  "only_a": int((j["_merge"] == "left_only").sum()),
                  "only_b": int((j["_merge"] == "right_only").sum()),
                  "nan_mismatch": int((nan_a != nan_b).sum())}


def _d7_pair(a: pd.DataFrame, b: pd.DataFrame, seeded: bool) -> dict:
    cell = ["target", "series", "horizon", "period"]
    both, c = _join(a, b, [*cell, "quantile"])
    d = both.loc[both["ok"], "abs_diff"]
    out = {"n_ref": c["n_a"], "n_new": c["n_b"], "only_ref": c["only_a"], "only_new": c["only_b"],
           "nan_mismatch": c["nan_mismatch"], "max_abs_diff": float(d.max()) if len(d) else np.nan}
    out["identical"] = bool(c["only_a"] == c["only_b"] == c["nan_mismatch"] == 0 and (d == 0).all())
    out["statistic"] = "seed stability" if seeded else "max abs difference (0 expected)"
    if not seeded:
        return out
    out.update(median_ratio=np.nan, p95_ratio=np.nan, median_limit=MEDIAN_LIMIT,
               p95_limit=P95_LIMIT, within_limits=None)
    if len(d):              # |dq| over the reference's 50% width, as seed_stability (plan §3)
        w = a.pivot_table(index=cell, columns="quantile", values="value")
        w50 = (w[0.75] - w[0.25]).rename("w50").reset_index()
        m = both[both["ok"]].merge(w50, on=cell, how="left")
        diff, width = m["abs_diff"].to_numpy(float), m["w50"].to_numpy(float)
        with np.errstate(invalid="ignore", divide="ignore"):
            ratio = np.where(width > 0, diff / np.where(width > 0, width, 1.0),
                             np.where(diff == 0, 0.0, np.inf))
        med, p95 = float(np.median(ratio)), float(np.quantile(np.minimum(ratio, 1e9), 0.95))
        out.update(median_ratio=med, p95_ratio=p95,
                   within_limits=bool(med < MEDIAN_LIMIT and p95 < P95_LIMIT))
    return out


@_step3
def d7_check(files: dict) -> pd.DataFrame:
    """Design §4's D7 check, reported and never a stop: each as-of file's forecasts at the
    duplicate origins (``D7_FOLD``) against their information set's first origin, per level.
    Deterministic models: the maximum absolute difference (0 expected). M2 (seeds differ by
    origin): the seed-stability statistic, median and 95th percentile of |dq| / 50% width."""
    rows = []
    for (key, _, mode), path in sorted(files.items()):
        if mode != "asof":
            continue
        f = pd.read_parquet(path, columns=["origin", "model", "level", "target", "series",
                                           "horizon", "period", "quantile", "value"])
        f["origin"] = pd.to_datetime(f["origin"])
        for dup, first in sorted(D7_FOLD.items()):
            a, b = f[f["origin"] == ts(first)], f[f["origin"] == ts(dup)]
            for lv in sorted(set(a["level"]) | set(b["level"])):
                pair = _d7_pair(a[a["level"] == lv], b[b["level"] == lv], seeded=key == "m2")
                rows.append({"model_key": key, "model": f["model"].iloc[0], "level": lv,
                             "mode": mode, "origin": ts(dup), "reference": ts(first), **pair})
    return pd.DataFrame(rows)


def _p13_frame(frame: pd.DataFrame) -> pd.DataFrame:
    conf = pd.DatetimeIndex([ts(o) for o in CONF21])
    f = frame.assign(origin=pd.to_datetime(frame["origin"]).astype("datetime64[ns]"),
                     period=pd.to_datetime(frame["period"]).astype("datetime64[ns]"),
                     horizon=frame["horizon"].astype("int64"),
                     quantile=frame["quantile"].astype(float))
    return f[f["origin"].isin(conf)]


@_step3
def p13_check(files: dict, quarantine_file) -> pd.DataFrame:
    """Design §4's P13 check, reported and never a stop: new provider forecasts of B0, B1, B2
    and default M1, both modes, against the quarantined pre-seal forecasts, on values only.
    The quarantined file is read with pyarrow filters (CONF origins, provider level, those
    models), key and value columns only; a score or summary file is refused, by name before its
    schema is read and by its columns after."""
    path = Path(quarantine_file)
    refused = ValueError(f"{path.name} is not a pre-seal forecast file; P13 reads forecasts only")
    if path.suffix != ".parquet" or "score" in path.name or "summary" in path.name:
        raise refused
    names = set(pq.read_schema(path).names)
    if {"y", "wis", "cov90"} & names or not {*P13_KEYS, "model", "level", "value"} <= names:
        raise refused
    models = {NAMES[k]: k for k in H4_MODELS}
    filters = [("origin", ">=", ts(CONF21[0])), ("origin", "<=", ts(CONF21[-1])),
               ("level", "=", "provider"), ("model", "in", list(models))]
    old = _p13_frame(pq.read_table(path, columns=[*P13_KEYS, "model", "value"],
                                   filters=filters).to_pandas())
    rows = []
    for key in H4_MODELS:
        for mode in ("asof", "final"):
            if (key, "provider", mode) not in files:
                continue
            new = pd.read_parquet(files[key, "provider", mode], columns=[*P13_KEYS, "value"])
            ref = old[(old["model"] == NAMES[key]) & (old["mode"] == mode)]
            both, c = _join(_p13_frame(new), ref, P13_KEYS)
            a, b = both["value_a"], both["value_b"]
            same = (a == b) | (a.isna() & b.isna())
            rel = both["abs_diff"][both["ok"]] / b[both["ok"]].abs().clip(lower=1.0)
            rows.append({"model_key": key, "model": NAMES[key], "mode": mode, "n_new": c["n_a"],
                         "n_old": c["n_b"], "only_new": c["only_a"], "only_old": c["only_b"],
                         "nan_mismatch": c["nan_mismatch"],
                         "share_identical": float(same.mean()) if len(both) else np.nan,
                         "median_rel_diff": float(rel.median()) if len(rel) else np.nan,
                         "max_rel_diff": float(rel.max()) if len(rel) else np.nan,
                         "identical": bool(c["only_a"] == c["only_b"] == 0 and len(both)
                                           and same.all()),
                         "expected": P13_EXPECTED["b1" if key == "b1" else mode]})
    return pd.DataFrame(rows)


# ---- the hash commit H1 (design §4) -----------------------------------------------------
def _git(cwd, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    if p.returncode:
        raise RuntimeError(f"git {' '.join(args[:3])} failed: {p.stderr.strip()}")
    return p.stdout.strip()


@_step3
def hash_commit(ctx: Context, tables: dict[str, pd.DataFrame]) -> str:
    """Write ``tables`` (keyed by ``HASH_FILES``) to ``ctx.results`` and commit exactly those
    files, hooks disabled, as a single-parent child of HEAD whose diff only adds them. The dry
    run, which is repeated, writes to ``ctx.results/<head>`` (its work directory's name), so
    each dry run's commit adds files too. Refuses a file that exists or is tracked, before
    writing anything. Returns the new HEAD (H1)."""
    if set(tables) != set(HASH_FILES):
        raise ValueError(f"the hash commit holds exactly {HASH_FILES}")
    out = ctx.results if ctx.mode == "run" else ctx.results / ctx.work.name
    out.mkdir(parents=True, exist_ok=True)
    root = Path(_git(out, "rev-parse", "--show-toplevel")).resolve()
    paths = [out / name for name in HASH_FILES]
    _refuse(paths)
    rel = [p.resolve().relative_to(root).as_posix() for p in paths]
    tracked = _git(root, "ls-files", "--", *rel).splitlines()
    if tracked:
        raise FileExistsError(f"the hash commit only adds files, and git tracks {tracked[:3]}")
    start = _git(root, "rev-parse", "HEAD")
    for name, p in zip(HASH_FILES, paths):
        tables[name].to_csv(p, index=False)
    msg = (f"Stage H: forecast hashes before the unseal ({ctx.mode})\n\n"
           "Written by the Stage H runner at the end of step 3 (design §4). Adds only:\n"
           + "".join(f"- {r}\n" for r in rel))
    _git(root, "add", "--", *rel)
    _git(root, "-c", "core.hooksPath=/dev/null", "commit", "--no-verify", "-q", "-m", msg,
         "--", *rel)
    head = _git(root, "rev-parse", "HEAD")
    parents = _git(root, "rev-list", "--parents", "-n", "1", head).split()[1:]
    changes = sorted(_git(root, "diff", "--name-status", start, head).splitlines())
    if parents != [start] or changes != sorted(f"A\t{r}" for r in rel):
        raise RuntimeError(f"hash commit {head[:12]} is not one child of {start[:12]} adding "
                           f"only {rel}")
    log.info("hash commit %s on %s", head[:12], start[:12])
    return head


# ---- the DEV side (design §8) ------------------------------------------------------------
@_step3
def dev_side(out_dir, jobs: int, vintages_path) -> dict[tuple[str, str, str], Path]:
    """``prepare --dev-side``: with the step-3 code, the DEV forecasts the pool inputs lack:
    B0 and default M1 as-of at the 69 DEV origins; final-mode B0, B1, B2, default M1 and M1 v3
    raw, and seeded as-of B1, at the DEV winter-h3 origins (origin month October to January).
    Writes ``out_dir/forecasts``, one file per ``DEV_SIDE_ORIGINS`` entry, which pin and check 11
    require (refused before any pool if the plan names other files). ``vintages_path``: the
    P4 rebuild to generate on, which ``checks.prepare_inputs`` makes outside INPUTS. There is
    no default: a rebuild under ``out_dir`` would be a 22nd file in INPUTS, which pin refuses."""
    out_dir = Path(out_dir)
    dev, winter = tuple(DEV), tuple(DEV_WINTER_H3)
    plan = [(("b0", "m1"), ("asof",), dev), (PROVIDER_MODELS, ("final",), winter),
            (("b1",), ("asof",), winter)]
    planned = {(k, "provider", m): tuple(o) for ks, ms, o in plan for k in ks for m in ms}
    pinned = {k: tuple(o) for k, o in DEV_SIDE_ORIGINS.items()}
    if planned != pinned:
        odd = sorted(set(planned) ^ set(pinned))
        moved = sorted(k for k in set(planned) & set(pinned) if planned[k] != pinned[k])
        raise ValueError(f"dev_side's plan is not the DEV_SIDE_ORIGINS that pin requires: "
                         f"files {odd} differ; origins differ for {moved}")
    if not {*dev, *winter} <= set(split_origins("dev")):
        raise ValueError("dev_side generates DEV origins only")
    ctx = Context("dev", dev, dev, {}, max(dev), out_dir, out_dir, Path(vintages_path), jobs)
    sha = file_sha(ctx.vintages_path)
    files = {}
    for ks, ms, origins in plan:
        files |= harness_block(ctx, ks, "provider", ms, origins, vintage_sha=sha)
    if set(files) != set(pinned):
        raise RuntimeError(f"dev_side wrote {sorted(files)}, not DEV_SIDE_ORIGINS' files")
    return files
