"""Stage E: the M2 ladder at ICB level (design in the amendments of 2026-09-10).

For each registered rung: the per-ICB prior-predictive check, one NUTS fit per origin
(35 even-month DEV origins, as-of), sampling diagnostics, posterior-predictive
quantiles, and scoring against the latest revised ICB totals. Comparators (ETS and the
Stage D selection) are run at ICB level through the ordinary harness.
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ProcessPoolExecutor
from datetime import date

import numpy as np
import pandas as pd

from nhs_ae.config import PROCESSED_DIR, PROJECT_ROOT
from nhs_ae.evaluate.asof import TARGETS, VINTAGES_PATH, load_asof, load_truth, load_vintages
from nhs_ae.evaluate.harness import score_forecasts, truth_long
from nhs_ae.evaluate.splits import split_origins
from nhs_ae.models import m2

log = logging.getLogger(__name__)

WORK = PROCESSED_DIR / "stage_e"
RESULTS = PROJECT_ROOT / "results" / "E-m2"
LADDER_ORIGINS = [o for o in split_origins("dev") if o.month % 2 == 0]
PRIOR_DRAWS = 500


def ladder_origins() -> list[date]:
    return list(LADDER_ORIGINS)


def panels_at(origin: date, vintages: pd.DataFrame) -> dict[str, pd.DataFrame]:
    d = load_asof(origin, "asof", vintages)
    return {t: d.panel(t, "icb") for t in ("att_type1", "att_all", "adm_via_ae")}


def prior_check(d: m2.M2Data, rung: m2.Rung) -> pd.DataFrame:
    """Per ICB and series: central 98% of prior-predictive counts against [min/10, max×10]."""
    import pymc as pm
    with m2.build_model(d, rung):
        prior = pm.sample_prior_predictive(PRIOR_DRAWS, random_seed=1)
    rows = []
    for s in rung.series:
        yv = d.y[s]
        if s == "adm":
            obs = ~np.isnan(yv) & ~np.isnan(d.y["type1"]) & (np.nan_to_num(d.y["type1"]) > 0)
        else:
            obs = ~np.isnan(yv)
        ii, _ = np.nonzero(obs)
        pp = prior.prior_predictive[f"y_{s}"].values.reshape(-1, len(ii))
        for i, icb in enumerate(d.icbs):
            cols = ii == i
            if not cols.any():
                continue
            lo, hi = np.percentile(pp[:, cols], [1, 99])
            o = yv[i][obs[i]]
            rows.append({"series": s, "icb": icb, "pp_lo": lo, "pp_hi": hi, "obs_min": o.min(),
                         "obs_max": o.max(), "ok": bool(lo >= o.min() / 10 and hi <= o.max() * 10)})
    return pd.DataFrame(rows)


_W: dict = {}


def _init(vpath):
    from nhs_ae.features.hierarchy import icb_region_map
    _W["v"] = load_vintages(vpath)
    _W["regions"] = icb_region_map()


def _fit_origin(args, shift: int = 0):
    """One origin's fit. ``shift`` moves both seeds (fit year × 100 + month + shift, predictive
    month + shift): 0 is the frozen specification, 1,000 the registered retry (plan §6)."""
    origin, rung, draws, tune, cores = args
    d = m2.prepare(panels_at(origin, _W["v"]), region_of=_W["regions"], clean=rung.clean_data)
    model = m2.build_model(d, rung)
    trace, secs = m2.fit(model, draws=draws, tune=tune, cores=cores,
                         seed=origin.year * 100 + origin.month + shift)
    diag = {"origin": pd.Timestamp(origin), "rung": rung.name, "shift": shift, "seconds": secs,
            **m2.diagnostics(trace, rung)}
    fut, draws_ = m2.predictive_draws(trace, d, m2.HORIZONS, seed=origin.month + shift, rung=rung)
    fc = m2._quantile_rows(draws_, d.icbs, m2.HORIZONS, fut, m2.QUANTILES).assign(level="icb")
    if rung.shared_factor or rung.corr_innov or rung.name.endswith("_agg"):   # region / England
        fc = pd.concat([fc, m2.aggregate_forecast(draws_, d, _W["regions"], m2.HORIZONS, fut)],
                       ignore_index=True)
    fc["origin"] = pd.Timestamp(origin)
    return fc, diag


def run_rung(rung: m2.Rung, origins=None, jobs: int = 3, draws: int = 1000, tune: int = 1000,
             cores: int = 4, work=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fit every origin (resumable: each origin's forecasts and diagnostics are saved as it
    finishes, and a failed fit is recorded rather than stopping the rung). ``work`` is the
    output directory (default: the Stage E cache). A cached table is returned only if it holds
    exactly the requested origins; otherwise this raises rather than hand back a different set."""
    from concurrent.futures import as_completed
    origins = origins or ladder_origins()
    work = WORK if work is None else work
    part = work / rung.name
    part.mkdir(parents=True, exist_ok=True)
    fpath, dpath = work / f"forecasts_{rung.name}.parquet", work / f"diagnostics_{rung.name}.csv"
    if fpath.exists() and dpath.exists():
        fc = pd.read_parquet(fpath)
        cached = set(fc["origin"].dt.strftime("%Y-%m"))
        wanted = {f"{o:%Y-%m}" for o in origins}
        if cached != wanted:
            raise RuntimeError(f"{fpath.name} holds {len(cached)} origins, {len(wanted)} requested: "
                               "use a new work directory rather than the cached table")
        return fc, pd.read_csv(dpath, parse_dates=["origin"])
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    todo = [o for o in origins if not (part / f"{o:%Y-%m}.parquet").exists()]
    with ProcessPoolExecutor(max_workers=jobs, initializer=_init, initargs=(VINTAGES_PATH,)) as pool:
        futs = {pool.submit(_fit_origin, (o, rung, draws, tune, cores)): o for o in todo}
        for fut in as_completed(futs):
            o = futs[fut]
            try:
                fc, diag = fut.result()
            except Exception as e:  # noqa: BLE001 - a failed fit is a result, recorded as such
                log.error("%s %s: fit failed: %s", rung.name, o, str(e).splitlines()[0])
                pd.DataFrame([{"origin": pd.Timestamp(o), "rung": rung.name, "error": str(e)[:300]}]).to_csv(
                    part / f"{o:%Y-%m}.failed.csv", index=False)
                continue
            log.info("%s %s: %.0fs rhat %.3f ess %.0f div %d", rung.name, o, diag["seconds"],
                     diag["rhat_max"], diag["ess_bulk_min"], diag["divergences"])
            fc.to_parquet(part / f"{o:%Y-%m}.parquet", index=False)
            pd.DataFrame([diag]).to_csv(part / f"{o:%Y-%m}.diag.csv", index=False)
    names = {f"{o:%Y-%m}" for o in origins}
    done = sorted(f for f in part.glob("*-*.parquet") if f.stem in names)
    fc = pd.concat([pd.read_parquet(f) for f in done], ignore_index=True)
    fc["mode"], fc["model"] = "asof", rung.name
    fc["level"] = fc["level"].fillna("icb") if "level" in fc else "icb"
    fc["scale"] = np.nan
    dg = pd.concat([pd.read_csv(f, parse_dates=["origin"]) for f in sorted(part.glob("*.diag.csv"))
                    if f.name.split(".")[0] in names], ignore_index=True)
    failed = sorted(f for f in part.glob("*.failed.csv") if f.name.split(".")[0] in names)
    if failed:
        dg = pd.concat([dg, *[pd.read_csv(f, parse_dates=["origin"]) for f in failed]], ignore_index=True)
    if len(done) == len(origins):
        fc.to_parquet(fpath, index=False)
        dg.to_csv(dpath, index=False)
    return fc, dg


def icb_truth(vintages: pd.DataFrame) -> pd.DataFrame:
    return truth_long(load_truth(vintages), ("icb",), tuple(TARGETS))


def score(fc: pd.DataFrame, truth: pd.DataFrame) -> pd.DataFrame:
    cols = ["origin", "mode", "model", "level", "target", "series", "horizon", "period",
            "quantile", "value", "scale"]
    s, dropped = score_forecasts(fc[cols], truth)
    log.info("scored %s: %d rows, dropped %s", fc["model"].iloc[0], len(s), dropped)
    return s


def comparator(name: str, method: str | None, vintages: pd.DataFrame, jobs: int = 4) -> pd.DataFrame:
    """A harness model at ICB level from the calibration burn-in to the end of DEV, calibrated
    with a Stage D method (pooled over ICBs), returned on the ladder origins."""
    from nhs_ae.calibrate.online import calibrate, first_release
    from nhs_ae.evaluate.harness import BacktestConfig, generate_forecasts
    from nhs_ae.evaluate.stage_d import BURN_IN_START
    from nhs_ae.ingest.recover import month_range
    from nhs_ae.models import MODELS
    WORK.mkdir(parents=True, exist_ok=True)
    path = WORK / f"comparator_{name}.parquet"
    if path.exists():
        fc = pd.read_parquet(path)
    else:
        cfg = BacktestConfig(origins=month_range(BURN_IN_START, split_origins("dev")[-1]),
                             modes=("asof",), levels=("icb",))
        fc = generate_forecasts([MODELS[name]()], vintages, cfg, jobs=jobs, vintages_path=VINTAGES_PATH)
        fc.to_parquet(path, index=False)
    if method and method != "raw":
        frp = WORK / "first_release_icb.parquet"
        if frp.exists():
            fr = pd.read_parquet(frp)
        else:
            fr = first_release(vintages, month_range(BURN_IN_START, split_origins("dev")[-1])[1:],
                               since=BURN_IN_START, level="icb")
            fr.to_parquet(frp, index=False)
        fc = calibrate(fc, fr, methods=(method,))
    keep = pd.to_datetime(pd.Index(ladder_origins()))
    return fc[fc["origin"].isin(keep)]


def pit_hist(scores: pd.DataFrame, bins: int = 10) -> np.ndarray:
    h, _ = np.histogram(scores["pit"].dropna(), bins=bins, range=(0, 1))
    return h / max(h.sum(), 1)


def summarise_rung(model: str, s: pd.DataFrame, ref: pd.DataFrame, diag: pd.DataFrame | None) -> dict:
    from nhs_ae.evaluate.metrics import paired_bootstrap
    from nhs_ae.evaluate.stage_d import acceptance, coverage_cells
    w, wr = s[s["winter"] & (s["horizon"] == 3)], ref[ref["winter"] & (ref["horizon"] == 3)]
    rel = {}
    for t in TARGETS:
        r = paired_bootstrap(wr[wr["target"] == t], w[w["target"] == t], unit="series")
        rel[t] = (r.get("rel", np.nan), r.get("rel_lo", np.nan), r.get("rel_hi", np.nan))
    gm = float(np.exp(np.mean([np.log1p(v[0]) for v in rel.values()])) - 1)
    acc = acceptance(coverage_cells(s.assign(model=model)))
    ph = pit_hist(s)
    out = {"model": model, "gm_wis_rel_to_ets": gm,
           **{f"wis_rel_{t}": v[0] for t, v in rel.items()},
           **{f"wis_rel_{t}_ci": f"[{v[1]:+.1%}, {v[2]:+.1%}]" for t, v in rel.items()},
           **{f"cov90_h{h}": s.loc[s["horizon"] == h, "cov90"].mean() for h in sorted(s["horizon"].unique())},
           "worst_cell_dev": float(acc["worst_dev"].iloc[0]) if len(acc) else np.nan,
           "cells_in_band": f"{int(acc['cells_in_band'].iloc[0])}/{int(acc['cells'].iloc[0])}" if len(acc) else "",
           "pit_max_bin": float(ph.max()), "pit_min_bin": float(ph.min())}
    if diag is not None and len(diag):
        out.update({"rhat_max": diag["rhat_max"].max(), "rhat_median": diag["rhat_max"].median(),
                    "ess_bulk_min": diag["ess_bulk_min"].min(), "divergences": int(diag["divergences"].sum()),
                    "fits_ok": int(((diag["rhat_max"] < 1.01) & (diag["ess_bulk_min"] > 400)
                                    & (diag["divergences"] == 0)).sum()),
                    "fits": len(diag), "minutes_per_fit": diag["seconds"].mean() / 60})
    return out


RUNGS = {"m2a": m2.M2A, "m2b": m2.M2B, "m2c_on_a": m2.M2C_ON_A, "m2c_on_b": m2.M2C_ON_B,
         "m2a_c": m2.M2A_C, "m2d": m2.M2D, "m2d2": m2.M2D2, "m2e_on_d": m2.M2E_ON_D,
         "m2e_on_d2": m2.M2E_ON_D2}
RUNGS["m2d_corr"] = m2.M2D_CORR
RUNGS["m2f_r2"] = m2.M2F_R2                                     # phase 1b redesign
RUNGS["m2f_r3"] = m2.M2F_R3                                     # phase 1b refinement
RUNGS["m2f_r4"] = m2.M2F_R4                                     # national COVID volatility
for _base in ("m2d", "m2d2", "m2e_on_d", "m2e_on_d2"):          # M2f on whichever base survives
    RUNGS[f"m2f_on_{_base}"] = m2.with_factor(RUNGS[_base])
    RUNGS[f"{_base}_agg"] = m2.with_aggregates(RUNGS[_base])


def main(argv=None) -> int:
    import argparse
    import sys
    p = argparse.ArgumentParser(prog="python -m nhs_ae.evaluate.stage_e")
    p.add_argument("--rungs", nargs="+", default=["m2a"], choices=sorted(RUNGS))
    p.add_argument("--jobs", type=int, default=2)
    p.add_argument("--cores", type=int, default=4, help="threads per NUTS fit (one per chain)")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for name in args.rungs:
        _, dg = run_rung(RUNGS[name], jobs=args.jobs, cores=args.cores)
        print(name, dg[["seconds", "rhat_max", "ess_bulk_min", "divergences"]].describe().round(3).to_string(),
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def _mmd_wis_pct() -> float:
    path = PROJECT_ROOT / "results" / "A-noise-floor" / "noise_table.csv"
    if not path.exists():
        return 0.0
    t = pd.read_csv(path)
    t = t[(t["run"] == "floor") & (t["slice"] == "winter_h3")]
    return float(t["mmd_wis_pct"].mean()) if len(t) else 0.0


OVERRIDES = {"m2d": "carried forward by Ellie's decision of 2026-09-10 despite the rule (amendment)"}


def retention(table: pd.DataFrame, mmd_pct: float) -> list[str]:
    """The work order's rule, applied rung by rung: keep a rung only if gm winter-h3 WIS
    improves on the retained rung below by more than the minimum meaningful difference AND
    the worst assessable coverage cell moves towards nominal. Recorded overrides win."""
    t = table.set_index("model")
    notes, base = [], "m2a"

    def step(cand: str, ref: str) -> bool | None:
        if cand not in t.index or ref not in t.index:
            return None
        dw = 100 * ((1 + t.loc[cand, "gm_wis_rel_to_ets"]) / (1 + t.loc[ref, "gm_wis_rel_to_ets"]) - 1)
        dc = 100 * (t.loc[cand, "worst_cell_dev"] - t.loc[ref, "worst_cell_dev"])
        keep = (dw < -mmd_pct) and (dc < 0)
        verdict = "RETAINED" if keep else "rejected"
        if not keep and cand in OVERRIDES:
            verdict = "rejected by the rule; " + OVERRIDES[cand]
        notes.append(f"{cand} vs {ref}: WIS {dw:+.1f}% (needs < -{mmd_pct:.1f}%), worst cell {dc:+.1f} pp "
                     f"(needs < 0) -> {verdict}")
        return keep or cand in OVERRIDES

    for rung in ("m2b", "m2c"):
        cand = rung if rung == "m2b" else ("m2c_on_b" if base == "m2b" else "m2c_on_a")
        if step(cand, base):
            base = cand
    if base == "m2a" and step("m2d", "m2a_c"):   # M2d against M2a refitted centred
        base = "m2d"
    if base == "m2d" and step("m2d2", "m2d"):
        base = "m2d2"
    cand_e = "m2e_on_d2" if base == "m2d2" else "m2e_on_d"
    if base in ("m2d", "m2d2") and step(cand_e, base):
        base = cand_e
    if step(f"m2f_on_{base}", base):
        base = f"m2f_on_{base}"
    notes.append(f"highest retained rung: {base}")
    return notes


def coherence(fc: pd.DataFrame) -> float:
    """Share of (origin, ICB, horizon) whose all-types median is below its Type 1 median."""
    med = fc[fc["quantile"] == 0.5].pivot_table(index=["origin", "series", "horizon"],
                                                columns="target", values="value")
    return float((med["att_all"] < med["att_type1"]).mean())


def _figures(scored: dict[str, pd.DataFrame], out) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    names = list(scored)
    fig, axes = plt.subplots(1, len(names), figsize=(2.2 * len(names), 2.4), dpi=150, sharey=True)
    for ax, n in zip(np.atleast_1d(axes), names):
        ax.bar(np.arange(10) / 10 + 0.05, pit_hist(scored[n]), width=0.09, color="#4a6fa5")
        ax.axhline(0.1, color="#888", lw=0.8, ls="--")
        ax.set_title(n, fontsize=7)
        ax.set_xticks([0, 0.5, 1])
        ax.tick_params(labelsize=6)
    fig.suptitle("PIT histograms, ICB level, DEV ladder origins (flat = calibrated)", fontsize=8)
    fig.tight_layout()
    fig.savefig(out / "fig_pit_by_rung.png")
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(6.5, 3.4), dpi=150)
    for n in names:
        c = scored[n].groupby("horizon")["cov90"].mean()
        ax.plot(c.index, c.values, marker="o", ms=3, lw=1.2, label=n)
    ax.axhspan(0.87, 0.93, color="#ddd", zorder=0)
    ax.set_xlabel("horizon (months)")
    ax.set_ylabel("90% interval coverage")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, fontsize=6.5, ncol=2)
    ax.set_title("Coverage by horizon, ICB level (band = acceptance 0.87–0.93)", fontsize=8, loc="left")
    fig.tight_layout()
    fig.savefig(out / "fig_coverage_by_rung.png")
    plt.close(fig)


def report(rungs: list[str], comparators: dict[str, tuple[str, str | None]], meta: dict,
           stop_name: str = "stop5") -> str:
    from nhs_ae.evaluate.stage_d import coverage_cells
    vintages = load_vintages()
    truth = icb_truth(vintages)
    ref = score(comparator("b1", None, vintages).assign(model="ets_icb"), truth)
    rows, scored, diags = [], {}, {}
    for name in rungs:
        fc, dg = run_rung(RUNGS[name])
        s = score(fc.assign(model=name), truth)
        rows.append({**summarise_rung(name, s, ref, dg), "incoherent_share": coherence(fc)})
        scored[name], diags[name] = s, dg
    for label, (base, method) in comparators.items():
        s = score(comparator(base, method, vintages).assign(model=label), truth)
        rows.append(summarise_rung(label, s, ref, None))
        scored[label] = s
    RESULTS.mkdir(parents=True, exist_ok=True)
    table = pd.DataFrame(rows)
    table.to_csv(RESULTS / "ladder_results.csv", index=False)
    cells = pd.concat([coverage_cells(s.assign(model=n)) for n, s in scored.items()])
    cells.to_csv(RESULTS / "coverage_by_horizon_year.csv", index=False)
    _figures(scored, RESULTS)
    for name, dg in diags.items():
        worst = dg.sort_values("rhat_max", ascending=False).head(5)
        (RESULTS / f"{name.upper()}_diagnostics.md").write_text(
            f"# {name} sampling diagnostics ({len(dg)} fits, nutpie, 4 chains × 1,000 draws)\n\n"
            + dg[["seconds", "rhat_max", "ess_bulk_min", "ess_tail_min", "divergences"]].describe().round(3).to_string()
            + "\n\nWorst five fits by R-hat:\n\n" + worst[["origin", "rhat_max", "worst_rhat_param",
                                                             "ess_bulk_min", "divergences"]].to_string(index=False)
            + "\n\nTargets (work order E7): R-hat < 1.01, bulk ESS > 400, 0 divergences. Necessary, not "
            "sufficient: the backtest PIT and coverage in `ladder_results.csv` are the decision-relevant "
            "diagnostics.\n")
    mmd = _mmd_wis_pct()
    keep = retention(table, mmd)
    lines = ["M2 ladder (ICB level, DEV ladder origins, as-of)",
             "  90% coverage by origin-year × horizon, assessable region ('*' outside 0.87–0.93, (x) not assessed):"]
    a = cells[cells["region"] == "assessable"]
    for n in scored:
        g = a[a["model"] == n]
        lines.append(f"\n  {n}")
        for y, gy in g.groupby("oyear"):
            cells_txt = " ".join((f"{r['cov90']:.2f}{'*' if not r['in_band'] else ' '}" if r["assessed"]
                                  else f"({r['cov90']:.2f})") for _, r in gy.sort_values("horizon").iterrows())
            lines.append(f"    {y}  {cells_txt}")
    lines.append("\n  summary (gm winter-h3 WIS vs ETS at ICB level; worst cell; sampling):")
    for _, r in table.iterrows():
        diag = (f"  rhat≤{r['rhat_max']:.3f} ess≥{r['ess_bulk_min']:.0f} div {int(r['divergences'])} "
                f"ok {int(r['fits_ok'])}/{int(r['fits'])}" if "rhat_max" in r and pd.notna(r.get("rhat_max")) else "")
        lines.append(f"    {r['model']:24s} WIS {100 * r['gm_wis_rel_to_ets']:+6.1f}%  worst {100 * r['worst_cell_dev']:4.1f} pp  "
                     f"in band {r['cells_in_band']}{diag}")
    lines += ["", "  retention (work order rule; MMD from Stage A, provider level, applied at ICB level):",
              *[f"    {x}" for x in keep]]
    text = "\n".join(lines)
    (RESULTS / f"{stop_name}.txt").write_text(text + "\n")
    (RESULTS / "README.md").write_text(
        f"# results/E-m2\n\nStage E ladder (M2a–M2c), ICB level, run {meta.get('date', '?')} at commit "
        f"`{meta.get('sha', '?')}` with PyMC 6.3.2 and nutpie 0.16.11 (`.venv-m2`).\n\n"
        "- `ladder_results.csv`: per rung and comparator: winter-h3 WIS relative to ETS (with 95% "
        "bootstrap intervals over ICBs), 90% coverage by horizon, worst assessable coverage cell, PIT "
        "extremes, sampling diagnostics\n- `coverage_by_horizon_year.csv`: coverage cells\n"
        "- `M2X_diagnostics.md`: sampling diagnostics per rung\n- `fig_pit_by_rung.png`, "
        "`fig_coverage_by_rung.png`\n- `m2a_prior_check.csv`: the registered prior-predictive gate\n"
        "- `stop5.txt`: the STOP 5 summary\n")
    return text


def agg_truth(vintages: pd.DataFrame) -> pd.DataFrame:
    """Region and England outturns as sums of the same ICBs the forecasts sum (skipna=False,
    so a month with any ICB missing is not scored at the aggregate level)."""
    from nhs_ae.features.hierarchy import icb_region_map
    truth = load_truth(vintages)
    regions = icb_region_map()
    rows = []
    for t in TARGETS:
        p = truth.panel(t, "icb")
        p = p[[c for c in p.columns if c not in m2.EXCLUDE]]
        reg = p.T.groupby(regions.reindex(p.columns).fillna("?")).sum(min_count=1).T
        full = p.notna().all(axis=1)
        reg = reg.where(full, axis=0)          # a month with any ICB missing: not scored
        eng = p.sum(axis=1, min_count=len(p.columns)).rename("ENGLAND").to_frame()
        for level, panel in (("region", reg), ("england", eng)):
            long = panel.stack(future_stack=True).rename("y").reset_index()
            long.columns = ["period", "series", "y"]
            long["target"], long["level"] = t, level
            rows.append(long)
    return pd.concat(rows, ignore_index=True)


def aggregate_report(pairs: dict[str, str], meta: dict) -> str:
    """Region and England calibration of M2f against its base refitted with joint draws."""
    vintages = load_vintages()
    truth = agg_truth(vintages)
    rows = []
    for label, name in pairs.items():
        fc, _ = run_rung(RUNGS[name])
        fc = fc[fc["level"].isin(["region", "england"])]
        for level, g in fc.groupby("level"):
            s = score(g.assign(model=label), truth[truth["level"] == level])
            w = s[s["winter"] & (s["horizon"] == 3)]
            rows.append({"model": label, "level": level, "winter_h3_wis": w["wis"].mean(),
                         **{f"cov90_h{h}": s.loc[s["horizon"] == h, "cov90"].mean() for h in range(1, 7)},
                         "cov90_all": s["cov90"].mean(), "cov50_all": s["cov50"].mean(), "n": len(s)})
    t = pd.DataFrame(rows)
    RESULTS.mkdir(parents=True, exist_ok=True)
    t.to_csv(RESULTS / "m2f_aggregates.csv", index=False)
    lines = ["Aggregate calibration (sums of ICB draws; DEV ladder origins, as-of; all months incl. COVID):"]
    for _, r in t.iterrows():
        lines.append(f"  {r['model']:34s} {r['level']:8s} winter-h3 WIS {r['winter_h3_wis']:10.0f}  "
                     + " ".join(f"h{h} {r[f'cov90_h{h}']:.2f}" for h in range(1, 7))
                     + f"  | cov90 {r['cov90_all']:.2f} cov50 {r['cov50_all']:.2f}")
    text = "\n".join(lines)
    (RESULTS / "m2f_aggregates.txt").write_text(text + "\n")
    return text
