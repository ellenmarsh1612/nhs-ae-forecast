"""M2f-r4 on all 69 DEV origins with draws saved (WO-A step 2).

The D1 pre-commitments were committed first (``docs/d1_precommitments.md``, 93704d0). DEV only;
no token. Every origin is refitted, the 35 even-month ones included, because the fits at
``b77430e`` saved no draws. The fits use ``m2_draws.fit_with_draws`` (``stage_e._fit_origin``'s
fit, same seeds). No fit is excluded on its diagnostics.

Outputs, all new paths:
* ``data/processed/m2f_69/m2f_r4/<origin>.parquet`` / ``.diag.csv`` / ``.fam.csv``: quantile
  rows, sampling diagnostics (with wall-clock time and draw-file sizes), and R-hat/ESS by variable;
* ``data/processed/m2f_69/draws/predictive/<origin>.npz``: posterior predictive sample paths,
  int32 counts ``(4000 draws, 36 ICBs, 6 horizons)`` per target, with ICB, region and period labels;
* ``data/processed/m2f_69/draws/posterior/<origin>.npz``: float64 posterior draws of every
  quantity the forecast reads (see ``m2_draws``).
"""

from __future__ import annotations

import logging
import os
import time
from datetime import date

import pandas as pd

from nhs_ae.config import PROCESSED_DIR, PROJECT_ROOT
from nhs_ae.evaluate import stage_e
from nhs_ae.evaluate.asof import VINTAGES_PATH
from nhs_ae.evaluate.seed_stability import family_diagnostics
from nhs_ae.evaluate.splits import split_origins
from nhs_ae.models import m2
from nhs_ae.models.m2_draws import fit_with_draws, save_npz

log = logging.getLogger(__name__)

RUNG = m2.M2F_R4
WORK = PROCESSED_DIR / "m2f_69"
PART = WORK / RUNG.name
DRAWS = WORK / "draws"
RESULTS = PROJECT_ROOT / "results" / "E-m2f-69"


def _fit(args):
    origin, cores = args
    t0 = time.time()
    fc, diag, trace, paths, post, meta = fit_with_draws(
        origin, RUNG, stage_e.panels_at(origin, stage_e._W["v"]), stage_e._W["regions"], cores=cores)
    fam = family_diagnostics(trace).assign(origin=pd.Timestamp(origin), rung=RUNG.name)
    del trace
    key = f"{origin:%Y-%m}"
    pb = save_npz(DRAWS / "predictive" / f"{key}.npz", {**paths, **meta})
    qb = save_npz(DRAWS / "posterior" / f"{key}.npz", {**post, "months": meta["months"]})
    diag.update(wall_seconds=time.time() - t0, predictive_bytes=pb, posterior_bytes=qb)
    return fc, diag, fam


def run_fits(origins: list[date] | None = None, jobs: int = 3, cores: int = 4) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Resumable: each origin's files are written as it finishes; a failed fit is recorded."""
    from concurrent.futures import ProcessPoolExecutor, as_completed
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    origins = origins or split_origins("dev")
    PART.mkdir(parents=True, exist_ok=True)
    todo = [o for o in origins if not (PART / f"{o:%Y-%m}.parquet").exists()]
    with ProcessPoolExecutor(max_workers=jobs, initializer=stage_e._init, initargs=(VINTAGES_PATH,)) as pool:
        futs = {pool.submit(_fit, (o, cores)): o for o in todo}
        for fut in as_completed(futs):
            o = futs[fut]
            try:
                fc, diag, fam = fut.result()
            except Exception as e:  # noqa: BLE001 - a failed fit is a result, recorded as such
                log.error("%s %s: fit failed: %s", RUNG.name, o, str(e).splitlines()[0])
                pd.DataFrame([{"origin": pd.Timestamp(o), "rung": RUNG.name, "error": str(e)[:300]}]).to_csv(
                    PART / f"{o:%Y-%m}.failed.csv", index=False)
                continue
            log.info("%s %s: %.0fs (wall %.0fs) rhat %.3f ess %.0f div %d", RUNG.name, o, diag["seconds"],
                     diag["wall_seconds"], diag["rhat_max"], diag["ess_bulk_min"], diag["divergences"])
            fc.to_parquet(PART / f"{o:%Y-%m}.parquet", index=False)
            pd.DataFrame([diag]).to_csv(PART / f"{o:%Y-%m}.diag.csv", index=False)
            fam.to_csv(PART / f"{o:%Y-%m}.fam.csv", index=False)
    names = {f"{o:%Y-%m}" for o in origins}
    fc = pd.concat([pd.read_parquet(f) for f in sorted(PART.glob("*.parquet")) if f.stem in names], ignore_index=True)
    fc["mode"], fc["model"], fc["scale"] = "asof", RUNG.name, float("nan")
    dg = pd.concat([pd.read_csv(f, parse_dates=["origin"]) for f in sorted(PART.glob("*.diag.csv"))
                    if f.name.split(".")[0] in names], ignore_index=True)
    if len(origins) == len(split_origins("dev")) and fc["origin"].nunique() == len(origins):
        fc.to_parquet(WORK / f"forecasts_{RUNG.name}_69.parquet", index=False)
        dg.to_csv(WORK / f"diagnostics_{RUNG.name}_69.csv", index=False)
    return fc, dg


def main(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="python -m nhs_ae.evaluate.m2f_69")
    p.add_argument("--jobs", type=int, default=3)
    p.add_argument("--cores", type=int, default=4)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    fc, dg = run_fits(jobs=args.jobs, cores=args.cores)
    print(f"FITS DONE: {fc['origin'].nunique()} origins, {len(dg)} diagnostics rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
