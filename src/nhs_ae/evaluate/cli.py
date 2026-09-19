"""Backtest command line.

    nhs-ae-backtest run                          # B0, DEV origins (2018-04..2023-12), both modes
    nhs-ae-backtest run --models b0 --origins 2022-09 2023-03 --levels provider england
    nhs-ae-backtest summary                      # saved scores' tables, sealed rows omitted
    nhs-ae-backtest audit                        # revision audit and training-leakage tables
    nhs-ae-backtest tune-m1 --jobs 10            # M1 search on pre-2019-09 origins (amendment)

``run`` refuses any sealed (CONF) origin, 2024-01..2025-09, whatever the seal's state: Stage H
runs only through ``python -m nhs_ae.evaluate.stage_h`` (P11).
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

import pandas as pd

from nhs_ae.config import PROCESSED_DIR, PROJECT_ROOT
from nhs_ae.evaluate.asof import LEVELS, TARGETS, VINTAGES_PATH, load_vintages
from nhs_ae.evaluate.audit import revision_audit, summarise_audit, training_leakage
from nhs_ae.evaluate.harness import BacktestConfig, generate_forecasts, score_against_truth
from nhs_ae.evaluate.metrics import paired_bootstrap, summarise
from nhs_ae.evaluate.splits import SEALED_ORIGINS, drop_sealed, split_origins
from nhs_ae.ingest.recover import month_range
from nhs_ae.models import MODELS

log = logging.getLogger("nhs_ae.evaluate")
OUT_DIR = PROCESSED_DIR / "backtest"


def print_summary(scores: pd.DataFrame) -> None:
    pd.set_option("display.width", 200)
    pd.set_option("display.float_format", lambda x: f"{x:,.3f}")
    for level in [lv for lv in LEVELS if lv in set(scores["level"])]:
        s = scores[scores["level"] == level]
        print(f"\n=== {level}: all months, by target / mode / horizon ===")
        t = summarise(s, ["target", "model", "mode", "horizon"])
        print(t.pivot_table(index=["target", "model", "horizon"], columns="mode",
                            values=["wis", "mase", "cov90"]).round(3).to_string())
        w = s[s["winter"]]
        if len(w):
            print(f"\n=== {level}: winter months only (Dec–Mar) ===")
            t = summarise(w, ["target", "model", "mode", "horizon"])
            print(t.pivot_table(index=["target", "model", "horizon"], columns="mode",
                                values=["wis", "mase", "cov90"]).round(3).to_string())
    # H4-style leakage gap for each model at provider level, horizon 3, winter
    p = scores[(scores["level"] == "provider") & (scores["horizon"] == 3) & scores["winter"]]
    if len(p) and {"asof", "final"} <= set(p["mode"]):
        print("\n=== as-of vs final, provider level, horizon 3, winter (bootstrap over providers) ===")
        for (target, model), g in p.groupby(["target", "model"]):
            r = paired_bootstrap(g[g["mode"] == "asof"], g[g["mode"] == "final"])
            if r.get("n_units"):
                print(f"{target:12s} {model:22s} WIS final vs as-of: {r['rel']:+.1%} "
                      f"[{r['rel_lo']:+.1%}, {r['rel_hi']:+.1%}]  n_providers={r['n_units']}")


def cmd_tune(args: argparse.Namespace) -> int:
    from nhs_ae.models.tune import default_origins, run_search, save_winner
    vintages = load_vintages()
    start, end = (date.fromisoformat(o + "-01") for o in args.origins) if args.origins else (None, None)
    origins = month_range(start, end) if start else default_origins()
    if max(origins) >= date(2019, 9, 1):
        log.error("tuning origins must precede the evaluation window (2019-09)")
        return 1
    table = run_search(vintages, VINTAGES_PATH, origins, n_configs=args.configs, jobs=args.jobs)
    out = PROCESSED_DIR / "tuning"
    out.mkdir(parents=True, exist_ok=True)
    table.to_csv(out / "m1_search.csv", index=False)
    cfg = save_winner(table)
    pd.set_option("display.width", 220)
    print(table[["config", "wis_mean", "mase_mean", "cov90_mean", "learning_rate", "num_leaves",
                 "min_data_in_leaf", "num_rounds", "lambda_l2", "feature_fraction",
                 "calibration_months"]].round(3).to_string(index=False))
    print(f"\nwinner written to models/m1_tuned.json: {cfg}", file=sys.stderr)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    global OUT_DIR
    if args.origins:
        start, end = (date.fromisoformat(o + "-01") for o in args.origins)
        origins = month_range(start, end)
    else:
        origins = split_origins(args.split)
    # P11: membership of SEALED_ORIGINS, not assert_not_sealed, so the refusal outlasts the
    # post-run state (conf-run-v1); checked before any data are read or any model is fitted
    sealed = pd.to_datetime(pd.Index(origins)).to_period("M").isin(SEALED_ORIGINS)
    if sealed.any():
        months = [o.strftime("%Y-%m") for o, s in zip(origins, sealed) if s]
        log.error("refused: %d requested origins (%s..%s) are sealed (CONF). Stage H runs only "
                  "through `python -m nhs_ae.evaluate.stage_h`", len(months), months[0], months[-1])
        return 1
    if args.out:
        OUT_DIR = PROCESSED_DIR / args.out
    vintages = load_vintages()
    cfg = BacktestConfig(origins=origins, modes=tuple(args.modes),
                         targets=tuple(args.targets), levels=tuple(args.levels))
    models = [MODELS[m]() for m in args.models]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.rescore:
        forecasts = pd.read_parquet(OUT_DIR / "forecasts.parquet")
    else:
        forecasts = generate_forecasts(models, vintages, cfg, jobs=args.jobs,
                                       vintages_path=VINTAGES_PATH)
        forecasts.to_parquet(OUT_DIR / "forecasts.parquet", index=False)
        log.info("wrote %d forecast rows to %s", len(forecasts), OUT_DIR / "forecasts.parquet")
    scores, dropped = score_against_truth(forecasts, vintages, cfg, unseal_token=None)
    info = {"forecast_rows": len(forecasts), "scored": len(scores), **dropped}
    scores.to_parquet(OUT_DIR / "scores.parquet", index=False)
    summarise(scores, ["level", "target", "model", "mode", "horizon", "winter"]).to_csv(
        OUT_DIR / "summary.csv", index=False)
    log.info("backtest: %s; written to %s", info, OUT_DIR)
    print_summary(scores)
    return 0


def cmd_noise(args: argparse.Namespace) -> int:
    import json
    import subprocess

    from nhs_ae.evaluate import noise
    from nhs_ae.models.tune import TUNED_PATH
    out = PROJECT_ROOT / "results" / "A-noise-floor"
    vintages = load_vintages()
    runs = []
    partial = PROCESSED_DIR / "noise_seed_runs_partial.csv"
    if args.reuse and partial.exists():   # completed runs from an interrupted invocation
        done = pd.read_csv(partial)
        runs.append(done[~done["run"].isin(args.runs)])
        log.info("reusing saved runs: %s", sorted(runs[0]["run"].unique()))
    for run in args.runs:
        runs.append(noise.seed_runs(vintages, VINTAGES_PATH, run, range(args.seeds), args.jobs))
        pd.concat(runs).to_csv(PROCESSED_DIR / "noise_seed_runs_partial.csv", index=False)
    search = pd.read_csv(PROJECT_ROOT / "results" / "m1-tuning" / "m1_search.csv")
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=PROJECT_ROOT,
                         capture_output=True, text=True, check=False).stdout.strip()
    meta = {"date": pd.Timestamp.now(tz="Europe/London").date().isoformat(), "sha": sha, "jobs": args.jobs,
            "winner_wis": json.loads(TUNED_PATH.read_text())["_wis_mean"]}
    print(noise.write_report(pd.concat(runs, ignore_index=True), search, out, meta))
    return 0


def _meta(jobs: int) -> dict:
    import subprocess
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=PROJECT_ROOT,
                         capture_output=True, text=True, check=False).stdout.strip()
    return {"date": pd.Timestamp.now(tz="Europe/London").date().isoformat(), "sha": sha,
            "jobs": jobs}


def cmd_calibration(args: argparse.Namespace) -> int:
    from nhs_ae.evaluate import stage_d
    print(stage_d.run(args.jobs, _meta(args.jobs)))
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    path = OUT_DIR / "scores.parquet"
    if not path.exists():
        log.error("no scores at %s; run `nhs-ae-backtest run` first", path)
        return 1
    scores = pd.read_parquet(path)
    n = len(scores)   # older runs predate the seal and contain CONF origins; always dropped (P11)
    scores = drop_sealed(scores)
    if len(scores) < n:
        log.warning("omitted %d sealed rows (CONF origins or 2024+ targets)", n - len(scores))
    print_summary(scores)
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    vintages = load_vintages()
    audit = revision_audit(vintages)
    start, end = (date.fromisoformat(o + "-01") for o in args.origins)
    leak = training_leakage(vintages, month_range(start, end))
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    audit.to_csv(PROCESSED_DIR / "revision_audit.csv", index=False)
    leak.to_csv(PROCESSED_DIR / "training_leakage.csv", index=False)
    pd.set_option("display.width", 200)
    pd.set_option("display.float_format", lambda x: f"{x:,.4f}")
    t = audit[audit["measure"].isin(list(TARGETS))]
    print("=== revision audit, targets, by financial year ===")
    print(summarise_audit(t).to_string(index=False))
    print("\n=== overall (targets) ===")
    for m, g in t.groupby("measure"):
        print(f"{m:11s} periods={len(g):3d}  any change={((g.providers_changed > 0) | (g.late_submitters > 0)).mean():.0%}  "
              f"mean providers changed={g.providers_changed.mean():.1f}  mean late submitters={g.late_submitters.mean():.2f}  "
              f"mean |national Δ|={g.national_rel_change.abs().mean():.2%}  max |national Δ|={g.national_rel_change.abs().max():.2%}")
    print("\n=== ten largest national revisions (targets) ===")
    big = t.reindex(t["national_rel_change"].abs().sort_values(ascending=False).index).head(10)
    print(big[["period", "measure", "n_versions", "providers_changed", "late_submitters",
               "national_first", "national_latest", "national_rel_change", "max_abs_change"]].to_string(index=False))
    print("\n=== training leakage at the origin (targets, trailing 12 months) ===")
    lt = leak[leak["measure"].isin(list(TARGETS))]
    print(lt.groupby("measure").agg(origins=("origin", "size"), share_changed=("share_changed", "mean"),
                                    mean_abs_rel_diff=("mean_abs_rel_diff", "mean"),
                                    max_abs_rel_diff=("mean_abs_rel_diff", "max"),
                                    only_in_final=("only_in_final", "mean")).to_string())
    print(f"\nwritten: {PROCESSED_DIR / 'revision_audit.csv'}, {PROCESSED_DIR / 'training_leakage.csv'}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nhs-ae-backtest", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run", help="run the rolling-origin backtest")
    p.add_argument("--models", nargs="+", default=["b0"], choices=sorted(MODELS))
    p.add_argument("--split", choices=["dev", "conf"], default="dev",
                   help="origin set: dev = 2018-04..2023-12 (default); conf = 2024-01..2025-09 "
                        "is sealed and refused (Stage H runs only through "
                        "`python -m nhs_ae.evaluate.stage_h`)")
    p.add_argument("--origins", nargs=2, metavar="YYYY-MM",
                   help="explicit range (overrides --split); refused if it reaches a sealed origin")
    p.add_argument("--modes", nargs="+", default=["asof", "final"], choices=["asof", "final"])
    p.add_argument("--targets", nargs="+", default=list(TARGETS), choices=list(TARGETS))
    p.add_argument("--levels", nargs="+", default=list(LEVELS), choices=list(LEVELS))
    p.add_argument("--jobs", type=int, default=1, help="parallel worker processes")
    p.add_argument("--rescore", action="store_true",
                   help="skip forecasting; re-score the saved forecasts.parquet")
    p.add_argument("--out", help="output folder under data/processed (default: backtest)")
    p.set_defaults(func=cmd_run)
    p = sub.add_parser("tune-m1", help="M1 hyperparameter search on pre-evaluation origins")
    p.add_argument("--origins", nargs=2, metavar="YYYY-MM", help="default 2018-04 2019-08")
    p.add_argument("--configs", type=int, default=16)
    p.add_argument("--jobs", type=int, default=1)
    p.set_defaults(func=cmd_tune)
    p = sub.add_parser("noise-floor", help="Stage A: M1 seed variance (20 seeds, two runs)")
    p.add_argument("--runs", nargs="+", default=["comparison", "floor"],
                   choices=["comparison", "floor"])
    p.add_argument("--seeds", type=int, default=20)
    p.add_argument("--jobs", type=int, default=1)
    p.add_argument("--reuse", action="store_true",
                   help="keep runs saved by an interrupted invocation that are not in --runs")
    p.set_defaults(func=cmd_noise)
    p = sub.add_parser("calibration", help="Stage D: calibration candidates on DEV")
    p.add_argument("--jobs", type=int, default=1)
    p.set_defaults(func=cmd_calibration)
    p = sub.add_parser("summary", help="print tables from the saved scores (sealed rows omitted)")
    p.set_defaults(func=cmd_summary)
    p = sub.add_parser("audit", help="revision audit and per-origin training leakage")
    p.add_argument("--origins", nargs=2, default=["2019-09", "2025-09"], metavar="YYYY-MM")
    p.set_defaults(func=cmd_audit)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
