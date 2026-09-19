"""M2 seed stability at the three worst late DEV origins (work order of 2026-09-11, step 2).

The two rule texts, the threshold and every detail the work order left open were committed
before this module, in ``docs/sampling_rule_draft.md`` (ea9ab01; provenance 9df25ae). DEV only;
no token. The one embargoed target month in reach (origin 2023-08, h6 = period 2024-01) is
excluded from every statistic, and outturns are read only through Stage E's ``score``.

Each model is fitted at each origin twice by one function (``_fit``, the body of
``stage_e._fit_origin`` with the seeds shifted): with the original seeds (fit seed
year × 100 + month, predictive seed month), which must reproduce the committed fit where one
exists, and with the retry seeds (+1,000 on both). The statistic is the absolute difference
between the two fits' quantiles as a fraction of the original fit's 50% interval width.
"""

from __future__ import annotations

import logging
import os
from datetime import date

import numpy as np
import pandas as pd

from nhs_ae.config import PROCESSED_DIR, PROJECT_ROOT
from nhs_ae.evaluate import stage_e
from nhs_ae.evaluate.asof import VINTAGES_PATH, load_vintages
from nhs_ae.evaluate.splits import sealed_mask
from nhs_ae.models import m2

log = logging.getLogger(__name__)

WORK = PROCESSED_DIR / "seed_stability"
RESULTS = PROJECT_ROOT / "results" / "E-m2-rerun69" / "seed_stability"
ORIGINS = (date(2023, 4, 1), date(2022, 7, 1), date(2023, 8, 1))
SHIFT = 1000
MEDIAN_LIMIT, P95_LIMIT = 0.05, 0.20
RUNGS = {"m2f_r4": m2.M2F_R4, "m2d_corr": m2.M2D_CORR}   # longer fits first
COMMITTED = {"m2d_corr": PROCESSED_DIR / "stage_h_prep" / "forecasts_m2d_corr.parquet",
             "m2f_r4": stage_e.WORK / "forecasts_m2f_r4.parquet"}
COMMITTED_DIAG = {"m2d_corr": PROJECT_ROOT / "results" / "E-m2-rerun69" / "diagnostics_69.csv",
                  "m2f_r4": stage_e.WORK / "diagnostics_m2f_r4.csv"}
KEYS = ["origin", "level", "target", "series", "horizon", "period", "quantile"]
CELL = ["origin", "target", "series", "horizon"]
# every family enters the predictive draws, except the COVID-window national scale at non-COVID origins
ROLES = {"sigma_rw": "scale: walk step (sets predictive spread)", "kappa": "scale: NB dispersion (sets predictive spread)",
         "sigma_g": "scale: national walk step (sets predictive spread)",
         "sigma_gc": "scale: COVID-window national step (not drawn from at these origins)",
         "f": "state: seasonal coefficients", "ell": "state: walk level (last 12 months)",
         "v": "state: zero-sum ICB walk", "gnat": "state: national walk"}


def family_diagnostics(trace) -> pd.DataFrame:
    """R-hat and ESS by variable, on ``m2.diagnostics``' own selection (no z's; walk levels
    over their last 12 months)."""
    import arviz as az
    post = trace.posterior
    ds = post.to_dataset() if hasattr(post, "to_dataset") else post
    ds = ds[[v for v in ds.data_vars if not v.startswith("z_")]]
    if "t" in ds.dims:
        ds = ds.isel(t=slice(-12, None))
    s = az.summary(ds, kind="diagnostics")
    s["family"] = s.index.str.replace(r"\[.*", "", regex=True)
    out = s.groupby("family").agg(n=("r_hat", "size"), rhat_max=("r_hat", "max"),
                                  ess_bulk_min=("ess_bulk", "min"), ess_tail_min=("ess_tail", "min")).reset_index()
    out["role"] = out["family"].str.replace(r"_(type1|all|adm|other)$", "", regex=True).map(ROLES).fillna("other")
    return out


def _fit(args):
    """``stage_e._fit_origin`` with both seeds shifted by ``shift``, plus per-variable diagnostics."""
    origin, rung, shift, draws, tune, cores = args
    w = stage_e._W
    d = m2.prepare(stage_e.panels_at(origin, w["v"]), region_of=w["regions"], clean=rung.clean_data)
    model = m2.build_model(d, rung)
    trace, secs = m2.fit(model, draws=draws, tune=tune, cores=cores,
                         seed=origin.year * 100 + origin.month + shift)
    diag = {"origin": pd.Timestamp(origin), "rung": rung.name, "shift": shift, "seconds": secs,
            **m2.diagnostics(trace, rung)}
    fam = family_diagnostics(trace).assign(origin=pd.Timestamp(origin), rung=rung.name, shift=shift)
    fut, draws_ = m2.predictive_draws(trace, d, m2.HORIZONS, seed=origin.month + shift, rung=rung)
    fc = m2._quantile_rows(draws_, d.icbs, m2.HORIZONS, fut, m2.QUANTILES).assign(level="icb")
    if rung.shared_factor or rung.corr_innov or rung.name.endswith("_agg"):   # region / England
        fc = pd.concat([fc, m2.aggregate_forecast(draws_, d, w["regions"], m2.HORIZONS, fut)],
                       ignore_index=True)
    fc["origin"] = pd.Timestamp(origin)
    return fc, diag, fam


def _path(name: str, origin: date, shift: int, ext: str):
    return WORK / name / f"{origin:%Y-%m}_s{shift}.{ext}"


def run_fits(jobs: int = 3, draws: int = 1000, tune: int = 1000, cores: int = 4) -> None:
    """The twelve fits (2 models × 3 origins × original and retry seeds), resumable, written
    only under ``WORK``; a failed fit is recorded, not raised."""
    from concurrent.futures import ProcessPoolExecutor, as_completed
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    todo = []
    for name, rung in RUNGS.items():
        (WORK / name).mkdir(parents=True, exist_ok=True)
        todo += [(o, rung, s, draws, tune, cores) for o in ORIGINS for s in (0, SHIFT)
                 if not _path(name, o, s, "parquet").exists()]
    with ProcessPoolExecutor(max_workers=jobs, initializer=stage_e._init, initargs=(VINTAGES_PATH,)) as pool:
        futs = {pool.submit(_fit, a): a for a in todo}
        for fut in as_completed(futs):
            o, rung, shift = futs[fut][:3]
            try:
                fc, diag, fam = fut.result()
            except Exception as e:  # noqa: BLE001 - a failed fit is a result, recorded as such
                log.error("%s %s shift %d: fit failed: %s", rung.name, o, shift, str(e).splitlines()[0])
                pd.DataFrame([{"origin": pd.Timestamp(o), "rung": rung.name, "shift": shift,
                               "error": str(e)[:300]}]).to_csv(_path(rung.name, o, shift, "failed.csv"), index=False)
                continue
            log.info("%s %s shift %d: %.0fs rhat %.3f ess %.0f div %d", rung.name, o, shift, diag["seconds"],
                     diag["rhat_max"], diag["ess_bulk_min"], diag["divergences"])
            fc.to_parquet(_path(rung.name, o, shift, "parquet"), index=False)
            pd.DataFrame([diag]).to_csv(_path(rung.name, o, shift, "diag.csv"), index=False)
            fam.to_csv(_path(rung.name, o, shift, "fam.csv"), index=False)


def load_fits() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    fcs, dgs, fams = [], [], []
    for name in RUNGS:
        for o in ORIGINS:
            for s in (0, SHIFT):
                if not _path(name, o, s, "parquet").exists():
                    raise FileNotFoundError(f"{name} {o} shift {s}: no fit (see {WORK / name})")
                fcs.append(pd.read_parquet(_path(name, o, s, "parquet")).assign(model=name, shift=s))
                dgs.append(pd.read_csv(_path(name, o, s, "diag.csv"), parse_dates=["origin"]))
                fams.append(pd.read_csv(_path(name, o, s, "fam.csv"), parse_dates=["origin"]))
    return pd.concat(fcs, ignore_index=True), pd.concat(dgs, ignore_index=True), pd.concat(fams, ignore_index=True)


def committed(name: str) -> pd.DataFrame:
    fc = pd.read_parquet(COMMITTED[name])
    return fc[fc["origin"].isin([pd.Timestamp(o) for o in ORIGINS])]


def reproduction(fits: pd.DataFrame) -> pd.DataFrame:
    """Original-seed refits against the committed tables, by model, origin and level."""
    rows = []
    for name in RUNGS:
        ref, new = committed(name), fits[(fits["model"] == name) & (fits["shift"] == 0)]
        j = new[KEYS + ["value"]].merge(ref[KEYS + ["value"]], on=KEYS, how="outer", suffixes=("_new", "_ref"))
        for (o, lev), g in j.groupby(["origin", "level"]):
            both = g["value_new"].notna() & g["value_ref"].notna()
            diff = (g.loc[both, "value_new"] - g.loc[both, "value_ref"]).abs()
            rows.append({"model": name, "origin": o, "level": lev, "rows_refit": int(g["value_new"].notna().sum()),
                         "rows_committed": int(g["value_ref"].notna().sum()), "rows_both": int(both.sum()),
                         "max_abs_diff": float(diff.max()) if both.any() else np.nan,
                         "identical": bool(both.all() and (diff == 0).all()) if g["value_ref"].notna().any() else None})
    return pd.DataFrame(rows)


def ratios(fits: pd.DataFrame) -> pd.DataFrame:
    """One row per ICB quantile: |retry − original| / the original fit's 50% width. Rows whose
    target period is sealed are dropped."""
    f = fits[fits["level"] == "icb"]
    cols = ["model", *KEYS, "value"]
    a, b = f.loc[f["shift"] == 0, cols], f.loc[f["shift"] == SHIFT, cols]
    j = a.merge(b, on=["model", *KEYS], suffixes=("_orig", "_retry"), validate="one_to_one")
    w = a.pivot_table(index=["model", *CELL], columns="quantile", values="value")
    j = j.merge((w[0.75] - w[0.25]).rename("w50").reset_index(), on=["model", *CELL], validate="many_to_one")
    diff = (j["value_retry"] - j["value_orig"]).abs()
    j["ratio"] = np.where(j["w50"] > 0, diff / j["w50"].where(j["w50"] > 0, 1.0), np.where(diff == 0, 0.0, np.inf))
    return j[~sealed_mask(j)].reset_index(drop=True)


def summarise(r: pd.DataFrame, by: list[str] | None = None) -> pd.DataFrame:
    """Median and 95th percentile of the ratio (an infinite ratio sorts last and counts against)."""
    def p95(x):
        return float(np.quantile(np.minimum(x.to_numpy(), 1e9), 0.95))
    out = r.groupby(["model", *(by or [])])["ratio"].agg(
        rows="size", median="median", p95=p95, max="max", infinite=lambda x: int(np.isinf(x).sum())).reset_index()
    out["median_ok"], out["p95_ok"] = out["median"] < MEDIAN_LIMIT, out["p95"] < P95_LIMIT
    return out


def verdict(row: pd.Series) -> str:
    return "STABLE" if row["median"] < MEDIAN_LIMIT and row["p95"] < P95_LIMIT else "MATERIAL"


def secondary(fits: pd.DataFrame) -> pd.DataFrame:
    """Between-seed WIS and coverage differences on rows scored for both seeds (Stage E's
    ``score``: latest revised ICB totals; embargoed rows dropped, CONF origins refused)."""
    truth = stage_e.icb_truth(load_vintages(VINTAGES_PATH))
    scored = {}
    for (name, s), f in fits[fits["level"] == "icb"].groupby(["model", "shift"]):
        sc = stage_e.score(f.assign(mode="asof", scale=np.nan), truth)
        scored[name, s] = sc[[*CELL, "period", "wis", "cov50", "cov90"]]
    rows = []
    for name in RUNGS:
        j = scored[name, 0].merge(scored[name, SHIFT], on=[*CELL, "period"], suffixes=("_orig", "_retry"))
        for key, g in [*j.groupby(["origin", "target"]), *[((pd.NaT, t), g) for t, g in j.groupby("target")]]:
            rows.append({"model": name, "origin": key[0], "target": key[1], "rows": len(g),
                         "wis_orig": g["wis_orig"].mean(), "wis_retry": g["wis_retry"].mean(),
                         "wis_diff_pct": 100 * (g["wis_retry"].mean() / g["wis_orig"].mean() - 1),
                         "cov50_orig": g["cov50_orig"].mean(), "cov50_retry": g["cov50_retry"].mean(),
                         "cov50_diff_pp": 100 * (g["cov50_retry"].mean() - g["cov50_orig"].mean()),
                         "cov90_orig": g["cov90_orig"].mean(), "cov90_retry": g["cov90_retry"].mean(),
                         "cov90_diff_pp": 100 * (g["cov90_retry"].mean() - g["cov90_orig"].mean())})
    out = pd.DataFrame(rows)
    pooled = out[out["origin"].isna()]
    gm = [{"model": m, "origin": pd.NaT, "target": "gm", "rows": int(g["rows"].sum()),
           "wis_diff_pct": 100 * (np.exp(np.log(g["wis_retry"] / g["wis_orig"]).mean()) - 1)}
          for m, g in pooled.groupby("model")]
    return pd.concat([out, pd.DataFrame(gm)], ignore_index=True)


def wis_spread(sec: pd.DataFrame) -> pd.DataFrame:
    """The observed between-seed WIS difference (pooled over the three origins, one pair) beside
    Stage A's seed SD and MMD. A single pair's |d| corresponds to a seed SD of |d|/√2. Not a floor."""
    a = pd.read_csv(PROJECT_ROOT / "results" / "A-noise-floor" / "noise_table.csv")
    a = a[a["run"] == "floor"].pivot_table(index="target", columns="slice", values=["wis_sd_pct", "mmd_wis_pct"])
    p = sec[sec["origin"].isna() & (sec["target"] != "gm")].copy()
    p["abs_diff_pct"] = p["wis_diff_pct"].abs()
    p["implied_seed_sd_pct"] = p["abs_diff_pct"] / np.sqrt(2)
    for sl in ("winter_h3", "all"):
        p[f"stage_a_sd_pct_{sl}"] = p["target"].map(a[("wis_sd_pct", sl)])
        p[f"stage_a_mmd_pct_{sl}"] = p["target"].map(a[("mmd_wis_pct", sl)])
    p["sd_ratio_vs_winter_h3"] = p["implied_seed_sd_pct"] / p["stage_a_sd_pct_winter_h3"]
    return p[["model", "target", "rows", "wis_diff_pct", "abs_diff_pct", "implied_seed_sd_pct",
              "stage_a_sd_pct_winter_h3", "stage_a_mmd_pct_winter_h3", "stage_a_sd_pct_all",
              "stage_a_mmd_pct_all", "sd_ratio_vs_winter_h3"]]


def diagnostics_table(dg: pd.DataFrame) -> pd.DataFrame:
    """Each refit's R-hat, ESS and divergences beside the committed fit's (none for M2f-r4 at 2022-07)."""
    cols = ["rhat_max", "ess_bulk_min", "ess_tail_min", "divergences", "worst_rhat_param"]
    out = []
    for name in RUNGS:
        c = pd.read_csv(COMMITTED_DIAG[name], parse_dates=["origin"])
        c = c[c["origin"].isin([pd.Timestamp(o) for o in ORIGINS])].assign(fit="committed")
        r = dg[dg["rung"] == name].assign(fit=lambda x: np.where(x["shift"] == 0, "refit, original seeds",
                                                                  "refit, retry seeds"))
        out.append(pd.concat([c[["origin", "fit", "seconds", *cols]], r[["origin", "fit", "seconds", *cols]]])
                   .assign(model=name))
    return pd.concat(out, ignore_index=True).sort_values(["model", "origin", "fit"])


def analyse() -> str:
    import json
    import subprocess
    RESULTS.mkdir(parents=True, exist_ok=True)
    fits, dg, fam = load_fits()
    rep = reproduction(fits)
    r = ratios(fits)
    expected = len(ORIGINS) * 36 * 3 * len(m2.HORIZONS) * len(m2.QUANTILES) - 36 * 3 * len(m2.QUANTILES)
    counts = r.groupby("model").size()
    if not (counts == expected).all():
        raise RuntimeError(f"ratio rows {counts.to_dict()}, expected {expected} per model")
    overall = summarise(r).assign(set="all quantiles")
    med = summarise(r[r["quantile"] == 0.5]).assign(set="median forecast only")
    cells = summarise(r, ["horizon", "target"])
    sec = secondary(fits)
    spread = wis_spread(sec)
    rep.to_csv(RESULTS / "reproduction.csv", index=False)
    pd.concat([overall, med]).to_csv(RESULTS / "stability_overall.csv", index=False)
    cells.to_csv(RESULTS / "stability_by_horizon_target.csv", index=False)
    summarise(r, ["origin"]).to_csv(RESULTS / "stability_by_origin.csv", index=False)
    summarise(r, ["quantile"]).to_csv(RESULTS / "stability_by_quantile.csv", index=False)
    summarise(r[r["quantile"] == 0.5], ["horizon", "target"]).to_csv(
        RESULTS / "stability_median_by_horizon_target.csv", index=False)
    sec.to_csv(RESULTS / "secondary_wis_coverage.csv", index=False)
    spread.to_csv(RESULTS / "wis_spread_vs_stage_a.csv", index=False)
    diagnostics_table(dg).to_csv(RESULTS / "diagnostics.csv", index=False)
    fam.to_csv(RESULTS / "diagnostics_by_family.csv", index=False)
    v = {row["model"]: verdict(row) for _, row in overall.iterrows()}
    where = {m: ", ".join(f"h{c.horizon} {c.target}" for c in cells[(cells["model"] == m)
                                                                     & ~(cells["median_ok"] & cells["p95_ok"])].itertuples())
             for m in RUNGS}
    text = "; ".join(
        [f"VERDICT: m2d_corr {v['m2d_corr']} (selects Text {'A' if v['m2d_corr'] == 'STABLE' else 'B'})",
         f"M2f-r4 {v['m2f_r4']} (reported for D1, selects nothing)"])
    detail = [f"{m}: median {row['median']:.4f} (limit < {MEDIAN_LIMIT}), p95 {row['p95']:.4f} (limit < {P95_LIMIT}), "
              f"rows {row['rows']}" + (f"; cells over a limit: {where[m]}" if where[m] else "")
              for m, row in overall.set_index("model").iterrows()]
    (RESULTS / "verdict.txt").write_text(text + "\n\n" + "\n".join(detail) + "\n")
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                         check=False, cwd=PROJECT_ROOT).stdout.strip()
    (RESULTS / "run.json").write_text(json.dumps(
        {"sha": sha, "origins": [f"{o:%Y-%m}" for o in ORIGINS], "shift": SHIFT, "rows_per_model": int(expected),
         "verdicts": v, "reproduced": rep.to_dict("records"), "work": str(WORK)}, indent=1, default=str))
    return text


def main(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="python -m nhs_ae.evaluate.seed_stability")
    p.add_argument("--jobs", type=int, default=3)
    p.add_argument("--cores", type=int, default=4)
    p.add_argument("--analyse-only", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not args.analyse_only:
        run_fits(jobs=args.jobs, cores=args.cores)
    print(analyse())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
