"""Stage D: calibration candidates on DEV (design in the amendment of 2026-09-10).

1. Base forecasts, as-of, provider level, cached under ``data/processed/stage_d/``:
   ``m1_v3_raw`` and ETS from 2017-07 (burn-in for calibration history) to 2023-12;
   ``m1_v3`` (status quo) and EnbPI on DEV only.
2. First-release table for the delayed-feedback rule.
3. Post-hoc calibration (pooled, per-series, DtACI) of ``m1_v3_raw`` and ETS.
4. Every candidate scored on DEV origins (burn-in dropped; the seal embargoes 2024
   targets), against the latest revised outturn.
5. Tables and figures for STOP 4: coverage by origin-year × horizon in the assessable
   region, the acceptance check, winter-h3 WIS relative to raw ETS with bootstrap
   intervals, and the Pareto front.
"""

from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd

from nhs_ae.calibrate.online import calibrate, first_release
from nhs_ae.config import PROCESSED_DIR, PROJECT_ROOT
from nhs_ae.evaluate.asof import VINTAGES_PATH, load_truth
from nhs_ae.evaluate.harness import BacktestConfig, generate_forecasts, score_forecasts, truth_long
from nhs_ae.evaluate.metrics import paired_bootstrap
from nhs_ae.evaluate.splits import DEV
from nhs_ae.features.hierarchy import current_region_map
from nhs_ae.ingest.recover import month_range
from nhs_ae.models import MODELS

log = logging.getLogger(__name__)

WORK = PROCESSED_DIR / "stage_d"
RESULTS = PROJECT_ROOT / "results" / "D-calibration"
BURN_IN_START = date(2017, 7, 1)
COVID = (pd.Timestamp("2020-03-01"), pd.Timestamp("2021-06-01"))
BAND = (0.87, 0.93)
MIN_ORIGINS = 6
BASES = {"m1_v3_raw": True, "b1": True, "m1_v3": False, "m1_enbpi": False}   # needs burn-in?
LABELS = {
    "m1_lightgbm_v3": "M1 v3, in-model CQR (status quo)",
    "m1_lightgbm_v3_raw": "M1 raw",
    "m1_lightgbm_v3_raw+pooled": "M1 + pooled conformal",
    "m1_lightgbm_v3_raw+series": "M1 + per-series conformal",
    "m1_lightgbm_v3_raw+dtaci": "M1 + DtACI",
    "m1_enbpi": "M1 EnbPI",
    "b1_ets": "ETS raw",
    "b1_ets+pooled": "ETS + pooled conformal",
    "b1_ets+series": "ETS + per-series conformal",
    "b1_ets+dtaci": "ETS + DtACI",
}
REFERENCE = "b1_ets"


def base_forecasts(name: str, vintages: pd.DataFrame, jobs: int, read_only: bool = False) -> pd.DataFrame:
    path = WORK / f"forecasts_{name}.parquet"
    start = BURN_IN_START if BASES[name] else DEV[0]
    origins = month_range(start, DEV[1])
    if path.exists():
        cached = pd.read_parquet(path)
        if set(cached["origin"].dt.date) == set(origins):
            return cached
        log.warning("cached %s covers other origins; regenerating", name)
    if read_only:
        raise RuntimeError(f"{path} is missing or covers other origins, and this run may not regenerate it")
    cfg = BacktestConfig(origins=origins, modes=("asof",), levels=("provider",))
    fc = generate_forecasts([MODELS[name]()], vintages, cfg, jobs=jobs, vintages_path=VINTAGES_PATH)
    WORK.mkdir(parents=True, exist_ok=True)
    fc.to_parquet(path, index=False)
    return fc


def candidates(vintages: pd.DataFrame, jobs: int, failed: dict[str, pd.DataFrame] | None = None,
               read_only: bool = False) -> dict[str, pd.DataFrame]:
    """``failed`` ({base name: ``calibrate.g1.failed_forecasts`` rows} for every calibrated
    base) applies guard G1; ``read_only`` refuses to regenerate any cached input."""
    fr_path = WORK / "first_release.parquet"
    if fr_path.exists():
        fr = pd.read_parquet(fr_path)
    elif read_only:
        raise RuntimeError(f"{fr_path} is missing and this run may not write it")
    else:
        fr = first_release(vintages, month_range(BURN_IN_START, DEV[1])[1:], since=BURN_IN_START)
        WORK.mkdir(parents=True, exist_ok=True)
        fr.to_parquet(fr_path, index=False)
    out = {}
    for name, needs_history in BASES.items():
        fc = base_forecasts(name, vintages, jobs, read_only)
        out[fc["model"].iloc[0]] = fc
        if needs_history:
            cal = calibrate(fc, fr, failed=None if failed is None else failed[name])
            out.update({m: g for m, g in cal.groupby("model")})
    return out


def assessable(scores: pd.DataFrame) -> pd.Series:
    o, p = scores["origin"], scores["period"]
    return ~(o.between(*COVID) | p.between(*COVID))


def coverage_cells(scores: pd.DataFrame, by_target: bool = False) -> pd.DataFrame:
    s = scores.assign(oyear=scores["origin"].dt.year, assess=assessable(scores))
    keys = ["model", "oyear", "horizon"] + (["target"] if by_target else [])
    rows = []
    for region, g in (("assessable", s[s["assess"]]), ("covid_window", s[~s["assess"]])):
        c = g.groupby(keys).agg(cov90=("cov90", "mean"), cov50=("cov50", "mean"),
                                n=("cov90", "size"), origins=("origin", "nunique")).reset_index()
        c["region"] = region
        rows.append(c)
    out = pd.concat(rows, ignore_index=True)
    out["assessed"] = (out["region"] == "assessable") & (out["origins"] >= MIN_ORIGINS)
    out["in_band"] = out["cov90"].between(*BAND)
    return out


def acceptance(cells: pd.DataFrame) -> pd.DataFrame:
    a = cells[cells["assessed"]]
    return a.groupby("model").agg(
        cells=("in_band", "size"), cells_in_band=("in_band", "sum"),
        worst_dev=("cov90", lambda x: float((x - 0.9).abs().max())),
        min_cov=("cov90", "min"), max_cov=("cov90", "max")).assign(
        meets=lambda d: d["cells_in_band"] == d["cells"]).reset_index()


def wis_table(scores: pd.DataFrame) -> pd.DataFrame:
    w = scores[scores["winter"] & (scores["horizon"] == 3)]
    ref = w[w["model"] == REFERENCE]
    rows = []
    for (model, target), g in w.groupby(["model", "target"]):
        r = paired_bootstrap(ref[ref["target"] == target], g)
        rows.append({"model": model, "target": target, "wis": g["wis"].mean(),
                     "cov90": g["cov90"].mean(), "rel_to_ets": r.get("rel", np.nan),
                     "rel_lo": r.get("rel_lo", np.nan), "rel_hi": r.get("rel_hi", np.nan),
                     "n_providers": r.get("n_units", 0)})
    t = pd.DataFrame(rows, columns=["model", "target", "wis", "cov90", "rel_to_ets", "rel_lo",
                                    "rel_hi", "n_providers"])
    gm = t.groupby("model")["rel_to_ets"].apply(lambda x: float(np.exp(np.log1p(x).mean()) - 1))
    return t, gm.rename("gm_rel_to_ets").reset_index()


def pareto(acc: pd.DataFrame, gm: pd.DataFrame) -> pd.DataFrame:
    p = acc.merge(gm, on="model")
    x, y = p["gm_rel_to_ets"].to_numpy(), p["worst_dev"].to_numpy()
    p["pareto"] = [not np.any((x <= x[i]) & (y <= y[i]) & ((x < x[i]) | (y < y[i])))
                   for i in range(len(p))]
    return p.sort_values(["pareto", "worst_dev"], ascending=[False, True])


def _fig_pareto(p: pd.DataFrame, path, x_max: float = 45.0) -> None:
    """Pareto plot; candidates beyond ``x_max`` % are pinned to the edge with their value."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7.5, 4.4), dpi=150)
    placed: list[tuple[float, float]] = []
    for _, r in p.sort_values("worst_dev").iterrows():
        x, y = 100 * r["gm_rel_to_ets"], 100 * r["worst_dev"]
        off = x > x_max
        xp = x_max if off else x
        colour = "#2b6cb0" if r["model"].startswith("m1") else "#c05621"
        ax.scatter(xp, y, s=46 if r["pareto"] else 24, color=colour, marker=">" if off else "o",
                   edgecolors="black" if r["pareto"] else "none", zorder=3)
        label = LABELS.get(r["model"], r["model"]) + (f" (WIS {x:+,.0f}%, off scale)" if off else "")
        dy = 3 + 9 * sum(1 for px, py in placed if abs(px - xp) < 12 and abs(py - y) < 1.2)
        placed.append((xp, y))
        ax.annotate(label, (xp, y), xytext=(-5 if off else 5, dy), textcoords="offset points",
                    fontsize=6.3, ha="right" if off else "left")
    ax.axhline(3, color="#888", lw=0.8, ls="--")
    ax.text(-4, 3.3, "acceptance: every cell within ±3 pp", fontsize=6.3, color="#555")
    ax.set_xlim(-5, x_max + 2)
    ax.set_xlabel("winter h=3 WIS vs raw ETS, % (geometric mean over targets; lower is better)")
    ax.set_ylabel("worst assessable cell |cov90 − 0.90|, pp")
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_title("Calibration candidates on DEV (as-of, provider level); outlined = Pareto front",
                 fontsize=8.5, loc="left")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def run(jobs: int = 1, meta: dict | None = None) -> str:
    from nhs_ae.evaluate.asof import load_vintages
    vintages = load_vintages()
    cands = candidates(vintages, jobs)
    region_map = current_region_map(vintages)
    truth = truth_long(load_truth(vintages, region_map), ("provider",), tuple(
        sorted({t for fc in cands.values() for t in fc["target"].unique()})))
    scored = []
    for model, fc in cands.items():
        fc = fc[fc["origin"] >= pd.Timestamp(DEV[0])]            # burn-in is never scored
        s, dropped = score_forecasts(fc, truth)
        log.info("scored %-28s %8d rows  dropped %s", model, len(s), dropped)
        scored.append(s)
    scores = pd.concat(scored, ignore_index=True)
    WORK.mkdir(parents=True, exist_ok=True)
    scores.to_parquet(WORK / "scores.parquet", index=False)
    RESULTS.mkdir(parents=True, exist_ok=True)
    cells = coverage_cells(scores)
    cells_t = coverage_cells(scores, by_target=True)
    pd.concat([cells.assign(target="all"), cells_t]).to_csv(
        RESULTS / "coverage_by_horizon_year.csv", index=False)
    acc = acceptance(cells)
    wis, gm = wis_table(scores)
    wis.to_csv(RESULTS / "wis_winter_h3.csv", index=False)
    par = pareto(acc, gm)
    par.to_csv(RESULTS / "pareto.csv", index=False)
    _fig_pareto(par, RESULTS / "fig_pareto.png")
    return report(cells, par, wis, meta or {})


def report(cells: pd.DataFrame, par: pd.DataFrame, wis: pd.DataFrame, meta: dict) -> str:
    text = stop4_text(cells, par)
    (RESULTS / "stop4.txt").write_text(text + "\n")
    (RESULTS / "README.md").write_text(
        f"# results/D-calibration\n\nStage D of the 2026-09-10 work order, produced by "
        f"`nhs-ae-backtest calibration --jobs {meta.get('jobs', '?')}` on {meta.get('date', '?')} "
        f"at commit `{meta.get('sha', '?')}`. Design and selection rule: pre-registration "
        f"amendment of 2026-09-10 (Stage D design).\n\n"
        "- `coverage_by_horizon_year.csv`: 90%/50% coverage per candidate × origin-year × "
        "horizon (target = all, or per target), region assessable / covid_window, origins, "
        "assessed, in_band\n- `wis_winter_h3.csv`: winter horizon-3 WIS per candidate and target, "
        "relative to raw ETS with 95% paired bootstrap intervals over providers\n"
        "- `pareto.csv`, `fig_pareto.png`: acceptance check and Pareto front\n"
        "- `stop4.txt`: the STOP 4 summary\n- `decision_loss.md`: written after Stage G "
        "(selection by decision loss needs the occupancy check)\n")
    return text


def stop4_text(cells: pd.DataFrame, par: pd.DataFrame, title: str = "STOP 4 — calibration candidates "
               "on DEV (as-of, provider, pooled over targets)") -> str:
    lines = [title,
             "  90% coverage by origin-year (rows) × horizon (cols); assessable region only;",
             "  '*' = cell outside 0.87–0.93; '(n)' = fewer than 6 origins, reported not assessed"]
    a = cells[cells["region"] == "assessable"]
    for model in dict.fromkeys([*par["model"], *sorted(a["model"].unique())]):
        g = a[a["model"] == model]
        lines.append(f"\n  {LABELS.get(model, model)}")
        lines.append("    year   " + "".join(f"  h={h}  " for h in sorted(g["horizon"].unique())))
        for y, gy in g.groupby("oyear"):
            cellstr = ""
            for _, r in gy.sort_values("horizon").iterrows():
                flag = "*" if r["assessed"] and not r["in_band"] else " "
                cellstr += (f" {r['cov90']:.2f}{flag}  " if r["assessed"]
                            else f"({r['cov90']:.2f}) ")
            lines.append(f"    {y}  {cellstr}")
    lines.append("\n  Pareto / acceptance (gm WIS vs raw ETS, winter h3; worst cell deviation):")
    for _, r in par.iterrows():
        lines.append(f"    {LABELS.get(r['model'], r['model']):36s} WIS {100 * r['gm_rel_to_ets']:+6.1f}%  "
                     f"worst {100 * r['worst_dev']:4.1f} pp  in band {int(r['cells_in_band'])}/"
                     f"{int(r['cells'])}  {'MEETS' if r['meets'] else '     '}"
                     f"{'  pareto' if r['pareto'] else ''}")
    return "\n".join(lines)
