"""The frozen M2 (``m2d_corr``) re-run on all 69 DEV origins, on the merged code (Stage H
pre-flight P0b and P1 in docs/confirmatory_plan.md; carried into Stage H by the E0 and freeze
amendments). DEV only; no token; nothing is scored here (the Stage H runner computes the DEV
statistics with the same code path as CONF).

Two checks run on the output, and either one stops the work:

1. **Reproduction (P0b).** The 35 even-month origins were fitted at ``m2-frozen-v1`` (16d47dd).
   The merged code must reproduce them with the same seeds. STOP if any quantile differs by
   more than ``REPRO_REL_TOL`` (relative), or if the per-origin R-hat or ESS differ.
2. **Sampling (Ellie's stop condition).** "0/35 on target" must hold up on the 34 new
   odd-month fits and not degrade. Fixed before running, against the 35-fit record (max R-hat
   median 1.041, worst 1.122; min bulk ESS median 95, lowest 26; no divergences):
   STOP if any fit fails, any fit has a divergence, any fit has max R-hat above
   ``RHAT_ANY`` or min bulk ESS below ``ESS_ANY``, or the 34-fit median max R-hat exceeds
   ``RHAT_MEDIAN`` or the median min bulk ESS falls below ``ESS_MEDIAN``.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from nhs_ae.config import PROCESSED_DIR, PROJECT_ROOT
from nhs_ae.evaluate import stage_e
from nhs_ae.evaluate.splits import split_origins
from nhs_ae.models import m2

log = logging.getLogger(__name__)

WORK = PROCESSED_DIR / "stage_h_prep"
RESULTS = PROJECT_ROOT / "results" / "E-m2-rerun69"
REPRO_REL_TOL = 0.01
RHAT_ANY, ESS_ANY = 1.15, 20.0
RHAT_MEDIAN, ESS_MEDIAN = 1.05, 70.0


def reproduction(fc: pd.DataFrame, dg: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    old_fc = pd.read_parquet(stage_e.WORK / "forecasts_m2d_corr.parquet")
    old_dg = pd.read_csv(stage_e.WORK / "diagnostics_m2d_corr.csv", parse_dates=["origin"])
    keys = ["origin", "level", "target", "series", "horizon", "period", "quantile"]
    j = fc[keys + ["value"]].merge(old_fc[keys + ["value"]], on=keys, suffixes=("_new", "_old"))
    j["rel_diff"] = (j["value_new"] - j["value_old"]).abs() / j["value_old"].abs().clip(lower=1.0)
    per = j.groupby("origin")["rel_diff"].max().rename("max_rel_diff").reset_index()
    d = dg.merge(old_dg, on="origin", suffixes=("_new", "_old"))
    for c in ("rhat_max", "ess_bulk_min", "divergences"):
        per = per.merge(d[["origin", f"{c}_new", f"{c}_old"]], on="origin", how="left")
    same_diag = bool(np.allclose(d["rhat_max_new"], d["rhat_max_old"], rtol=0, atol=1e-9)
                     and np.allclose(d["ess_bulk_min_new"], d["ess_bulk_min_old"], rtol=0, atol=1e-6))
    info = {"origins_compared": int(per["origin"].nunique()), "rows_compared": len(j),
            "rows_expected": len(old_fc), "max_rel_diff": float(j["rel_diff"].max()),
            "identical_values": bool((j["rel_diff"] == 0).all()), "identical_diagnostics": same_diag,
            "stop": bool(j["rel_diff"].max() > REPRO_REL_TOL or not same_diag or len(j) != len(old_fc))}
    return per, info


def sampling(dg: pd.DataFrame, origins: list) -> dict:
    new = dg[dg["origin"].dt.month % 2 == 1]
    failed = int(new["error"].notna().sum()) if "error" in new else 0
    ok = new[new["rhat_max"].notna()] if "rhat_max" in new else new
    missing = len(origins) - len(dg)
    on_target = int(((ok["rhat_max"] < 1.01) & (ok["ess_bulk_min"] > 400) & (ok["divergences"] == 0)).sum())
    checks = {
        "failed or missing fits": (failed + max(missing, 0), 0, failed + max(missing, 0) == 0),
        "fits with a divergence": (int((ok["divergences"] > 0).sum()), 0, bool((ok["divergences"] == 0).all())),
        f"fits with max R-hat > {RHAT_ANY}": (int((ok["rhat_max"] > RHAT_ANY).sum()), 0, bool((ok["rhat_max"] <= RHAT_ANY).all())),
        f"fits with min bulk ESS < {ESS_ANY:.0f}": (int((ok["ess_bulk_min"] < ESS_ANY).sum()), 0,
                                                   bool((ok["ess_bulk_min"] >= ESS_ANY).all())),
        f"median max R-hat ≤ {RHAT_MEDIAN}": (round(float(ok["rhat_max"].median()), 4), RHAT_MEDIAN,
                                             float(ok["rhat_max"].median()) <= RHAT_MEDIAN),
        f"median min bulk ESS ≥ {ESS_MEDIAN:.0f}": (round(float(ok["ess_bulk_min"].median()), 1), ESS_MEDIAN,
                                                   float(ok["ess_bulk_min"].median()) >= ESS_MEDIAN)}
    return {"n_new": len(new), "on_target": on_target, "checks": checks,
            "worst_rhat": float(ok["rhat_max"].max()), "min_ess": float(ok["ess_bulk_min"].min()),
            "stop": not all(v[2] for v in checks.values())}


def main(argv=None) -> int:
    import argparse
    import json
    import subprocess
    p = argparse.ArgumentParser(prog="python -m nhs_ae.evaluate.rerun69")
    p.add_argument("--jobs", type=int, default=3)
    p.add_argument("--cores", type=int, default=4)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                         check=False, cwd=PROJECT_ROOT).stdout.strip()
    origins = split_origins("dev")
    fc, dg = stage_e.run_rung(m2.M2D_CORR, origins=origins, jobs=args.jobs, cores=args.cores, work=WORK)
    RESULTS.mkdir(parents=True, exist_ok=True)
    dg.to_csv(RESULTS / "diagnostics_69.csv", index=False)
    per, rep = reproduction(fc, dg)
    per.to_csv(RESULTS / "reproduction_even_origins.csv", index=False)
    smp = sampling(dg, origins)
    lines = [f"Frozen M2 (m2d_corr) re-run on 69 DEV origins at `{sha}` (merged code); DEV only, nothing scored.", "",
             (f"P0b reproduction of the 35 even-month origins (m2-frozen-v1): {rep['origins_compared']} origins, "
              f"{rep['rows_compared']} of {rep['rows_expected']} quantile rows compared; max relative difference "
              f"{rep['max_rel_diff']:.2e}; identical values {rep['identical_values']}; identical diagnostics "
              f"{rep['identical_diagnostics']} -> {'STOP' if rep['stop'] else 'PASS'}"), "",
             (f"Sampling on the {smp['n_new']} new odd-month fits (rule fixed before running): "
              f"fits on target {smp['on_target']}/{smp['n_new']}; worst max R-hat {smp['worst_rhat']:.3f}; "
              f"lowest min bulk ESS {smp['min_ess']:.1f}")]
    lines += [f"  {'PASS' if ok else 'STOP'}  {name}: {val} (limit {lim})" for name, (val, lim, ok) in smp["checks"].items()]
    lines += ["", "VERDICT: " + ("STOP - do not proceed" if rep["stop"] or smp["stop"] else "PASS - proceed")]
    text = "\n".join(lines)
    (RESULTS / "stop_rerun69.txt").write_text(text + "\n")
    (RESULTS / "run.json").write_text(json.dumps({"sha": sha, "reproduction": rep, "sampling_stop": smp["stop"],
                                                  "work": str(WORK)}, indent=1, default=str))
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
