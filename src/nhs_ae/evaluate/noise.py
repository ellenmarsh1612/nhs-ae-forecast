"""Stage A: the noise floor (work order of 2026-09-10; design fixed in the amendment of
the same date, before any seed was run).

How much does M1's score move when nothing but the random seed changes? LightGBM draws
bagging rows, feature subsets and histogram bins from ``seed``; the conformal step uses
the last 12 months and has no random element, so the seed is the only thing varied.

Two runs, each 20 seeds:

* **comparison** — ``m1_tuned`` (the architecture the 16-configuration search used) on
  the search's own slice: origins 2018-04..2019-08, as-of, provider level, horizons 1–6,
  all months, mean WIS across targets. Seed 0 is the search winner itself, so it must
  reproduce the winner's recorded WIS exactly; that is checked.
* **floor** — ``m1_v3`` (the LightGBM of record) on the 21 DEV origins whose horizon-3
  target is a winter month, scored per target on winter, horizon 3, provider level, as-of
  (the slice every later comparison uses).

The minimum meaningful difference for later single-run comparisons is 2√2 × seed SD:
the 95% half-width of the difference between two runs that differ only in seed.
"""

from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd

from nhs_ae.evaluate.harness import BacktestConfig, generate_forecasts, score_against_truth
from nhs_ae.evaluate.splits import split_origins
from nhs_ae.ingest.recover import month_range
from nhs_ae.models import MODELS

log = logging.getLogger(__name__)

N_SEEDS = 20
TUNING_ORIGINS = (date(2018, 4, 1), date(2019, 8, 1))
MMD_FACTOR = 2 * np.sqrt(2)


def floor_origins() -> list[date]:
    """DEV origins whose horizon-3 target (origin + 2 months) is December–March and unsealed."""
    out = []
    for o in split_origins("dev"):
        target = pd.Timestamp(o) + pd.DateOffset(months=2)
        if target.month in (12, 1, 2, 3) and target < pd.Timestamp("2024-01-01"):
            out.append(o)
    return out


def _summaries(scores: pd.DataFrame, run: str, seed: int) -> pd.DataFrame:
    """Per target and slice: mean WIS, MASE, 50%/90% coverage and row count."""
    slices = {"all": scores}
    if run == "floor":
        slices["winter_h3"] = scores[scores["winter"] & (scores["horizon"] == 3)]
    rows = []
    for name, s in slices.items():
        g = s.groupby("target").agg(wis=("wis", "mean"), mase=("mase", "mean"),
                                    cov50=("cov50", "mean"), cov90=("cov90", "mean"),
                                    n=("wis", "size"))
        for target, r in g.iterrows():
            rows.append({"run": run, "seed": seed, "slice": name, "target": target, **r})
    return pd.DataFrame(rows)


def seed_runs(vintages: pd.DataFrame, vintages_path, run: str, seeds=range(N_SEEDS),
              jobs: int = 1) -> pd.DataFrame:
    if run == "comparison":
        model_name, origins = "m1_tuned", month_range(*TUNING_ORIGINS)
    elif run == "floor":   # only origins whose horizon-3 target is a winter month (amendment)
        model_name, origins = "m1_v3", floor_origins()
    else:
        raise ValueError(run)
    cfg = BacktestConfig(origins=origins, modes=("asof",), levels=("provider",))
    out = []
    for seed in seeds:
        model = MODELS[model_name](seed=seed)
        fc = generate_forecasts([model], vintages, cfg, jobs=jobs, vintages_path=vintages_path)
        scores, dropped = score_against_truth(fc, vintages, cfg)
        summ = _summaries(scores, run, seed)
        log.info("%s seed %02d: %s  dropped %s", run, seed,
                 summ[summ["slice"] == summ["slice"].iloc[-1]][["target", "wis", "cov90"]]
                 .round(3).to_dict("records"), dropped)
        out.append(summ)
    return pd.concat(out, ignore_index=True)


def noise_table(runs: pd.DataFrame) -> pd.DataFrame:
    """Mean, SD (absolute and % of mean), min–max and the minimum meaningful difference."""
    rows = []
    for (run, sl, target), g in runs.groupby(["run", "slice", "target"]):
        r = {"run": run, "slice": sl, "target": target, "seeds": len(g)}
        for m in ("wis", "cov90", "cov50", "mase"):
            x = g[m]
            r.update({f"{m}_mean": x.mean(), f"{m}_sd": x.std(ddof=1), f"{m}_min": x.min(),
                      f"{m}_max": x.max()})
        r["wis_sd_pct"] = 100 * r["wis_sd"] / r["wis_mean"]
        r["mmd_wis_pct"] = MMD_FACTOR * r["wis_sd_pct"]
        r["mmd_cov90_pp"] = MMD_FACTOR * 100 * r["cov90_sd"]
        rows.append(r)
    return pd.DataFrame(rows)


def comparison_statistic(runs: pd.DataFrame, search: pd.DataFrame) -> dict:
    """Seed SD against config SD on the tuning slice (mean WIS across targets)."""
    c = runs[(runs["run"] == "comparison") & (runs["slice"] == "all")]
    per_seed = c.groupby("seed")["wis"].mean()          # mean across targets, as the search did
    out = {"seed_mean": per_seed.mean(), "seed_sd": per_seed.std(ddof=1),
           "seed_min": per_seed.min(), "seed_max": per_seed.max(),
           "seed0_wis": per_seed.get(0, np.nan)}
    out["seed_sd_pct"] = 100 * out["seed_sd"] / out["seed_mean"]
    for label, g in [("all", search), *search.groupby("calibration_months")]:
        x = g["wis_mean"]
        out[f"config_sd_pct_{label}"] = 100 * x.std(ddof=1) / x.mean()
        out[f"config_n_{label}"] = len(x)
    return out


def _figure(runs: pd.DataFrame, search: pd.DataFrame, path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    c = runs[(runs["run"] == "comparison") & (runs["slice"] == "all")]
    seeds = c.groupby("seed")["wis"].mean()
    rng = np.random.default_rng(0)
    fig, ax = plt.subplots(figsize=(8, 2.8), dpi=150)
    ax.scatter(seeds, 2 + rng.uniform(-0.12, 0.12, len(seeds)), s=22, color="#4a4a4a",
               label="winning config, 20 seeds")
    colours = {12: "#2b6cb0", 24: "#c05621"}
    for cal, g in search.groupby("calibration_months"):
        ax.scatter(g["wis_mean"], 1 + rng.uniform(-0.12, 0.12, len(g)), s=22,
                   color=colours.get(cal, "#888"), label=f"search configs, {cal}-month calibration")
    best = search["wis_mean"].min()
    ax.scatter([best], [1], s=110, facecolors="none", edgecolors="#4a4a4a", linewidths=1)
    ax.annotate("search winner (= seed 0)", (best, 1), xytext=(0, -16),
                textcoords="offset points", ha="center", fontsize=7, color="#4a4a4a")
    ax.set_yticks([1, 2], ["16 configs", "20 seeds"])
    ax.set_ylim(0.5, 2.5)
    ax.set_xlabel("mean WIS across targets (origins 2018-04..2019-08, as-of, provider, h1–6)")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, fontsize=7, loc="upper left", bbox_to_anchor=(1.0, 1.0))
    ax.set_title("Seed noise against the tuning search, same slice", fontsize=9, loc="left")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def write_report(runs: pd.DataFrame, search: pd.DataFrame, out_dir, meta: dict) -> str:
    """seed_runs.csv, noise_floor.md, fig_seed_vs_config.png, README.md; returns the STOP text."""
    out_dir.mkdir(parents=True, exist_ok=True)
    runs.to_csv(out_dir / "seed_runs.csv", index=False)
    table = noise_table(runs)
    table.to_csv(out_dir / "noise_table.csv", index=False)
    comp = comparison_statistic(runs, search)
    _figure(runs, search, out_dir / "fig_seed_vs_config.png")
    floor = table[(table["run"] == "floor") & (table["slice"] == "winter_h3")]
    lines = ["# Stage A — noise floor", "",
             f"Run {meta['date']} at commit `{meta['sha']}`. Design fixed in the pre-registration",
             "amendment of 2026-09-10 (Stage A design) before any seed was run.", "",
             "## Seed noise against the tuning search (same slice)", "",
             "Slice: origins 2018-04..2019-08, as-of, provider level, horizons 1–6, all months,",
             "mean WIS across the three targets — the slice the 16-configuration search used.", "",
             "| | n | mean WIS | SD | SD as % of mean |", "|---|---|---|---|---|",
             (f"| winning config, seeds 0–19 | {N_SEEDS} | {comp['seed_mean']:.1f} | "
              f"{comp['seed_sd']:.2f} | {comp['seed_sd_pct']:.2f}% |")]
    for label in ["all", *sorted(k for k in search["calibration_months"].unique())]:
        lines.append(f"| search configs, {'all' if label == 'all' else f'{label}-month calibration'} "
                     f"| {comp[f'config_n_{label}']} | "
                     f"{(search if label == 'all' else search[search['calibration_months'] == label])['wis_mean'].mean():.1f}"
                     f" | | {comp[f'config_sd_pct_{label}']:.2f}% |")
    lines += ["", (f"Reproducibility: seed 0 is the search winner; its WIS here is "
                   f"{comp['seed0_wis']:.4f} against {meta['winner_wis']:.4f} recorded in "
                   f"`m1_tuned.json`."), "",
              "## Noise floor on DEV (winter, horizon 3, provider, as-of; `m1_v3`)", "",
              ("| target | mean WIS | SD % of mean | min–max WIS | 90% cov mean | cov SD (pp) | "
               "min. meaningful ΔWIS | min. meaningful Δcov90 |"),
              "|---|---|---|---|---|---|---|---|"]
    for _, r in floor.iterrows():
        lines.append(f"| {r['target']} | {r['wis_mean']:.1f} | {r['wis_sd_pct']:.2f}% | "
                     f"{r['wis_min']:.1f}–{r['wis_max']:.1f} | {r['cov90_mean']:.3f} | "
                     f"{100 * r['cov90_sd']:.2f} | {r['mmd_wis_pct']:.2f}% | "
                     f"{r['mmd_cov90_pp']:.2f} pp |")
    lines += ["", ("Minimum meaningful difference = 2√2 × seed SD (95% half-width of the "
                   "difference between two single-seed runs). Smaller differences are reported "
                   "as within noise."), ""]
    stop = ["STOP 1 — noise floor",
            f"  tuning slice: seed SD {comp['seed_sd_pct']:.2f}% of mean WIS; config SD "
            f"{comp['config_sd_pct_all']:.2f}% (all 16), "
            + ", ".join(f"{comp[f'config_sd_pct_{k}']:.2f}% ({k}-month calibration)"
                        for k in sorted(search["calibration_months"].unique()))]
    for _, r in floor.iterrows():
        stop.append(f"  DEV winter h3 {r['target']:10s}: seed SD {r['wis_sd_pct']:.2f}% of WIS, "
                    f"cov90 SD {100 * r['cov90_sd']:.2f} pp -> min meaningful ΔWIS "
                    f"{r['mmd_wis_pct']:.2f}%, Δcov90 {r['mmd_cov90_pp']:.2f} pp")
    lines += ["## STOP 1 summary", "", "```", *stop, "```", ""]
    (out_dir / "noise_floor.md").write_text("\n".join(lines))
    (out_dir / "README.md").write_text(
        f"# results/A-noise-floor\n\nStage A of the 2026-09-10 work order. Produced by\n"
        f"`nhs-ae-backtest noise-floor --jobs {meta['jobs']}` on {meta['date']} at commit "
        f"`{meta['sha']}`.\n\n- `seed_runs.csv`: one row per run × seed × slice × target\n"
        f"- `noise_table.csv`: mean, SD, min–max per run × slice × target, with the minimum "
        f"meaningful differences\n- `noise_floor.md`: the report and the STOP 1 summary\n"
        f"- `fig_seed_vs_config.png`: seed noise against the 16 search configurations on the "
        f"search's slice\n")
    return "\n".join(stop)
