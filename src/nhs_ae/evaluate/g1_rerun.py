"""P2: the STOP 4 table and Stage F re-run on DEV with guard G1 (exploratory).

Registered in the amendment "Guard G1 registered" (2026-09-13). The run reads the cached base
forecasts of the original Stage D and Stage F runs and writes only to new paths:
``data/processed/stage_d_g1/``, ``data/processed/stage_f_g1/``, ``results/D-calibration-G1/``
and ``results/F-reconciliation-G1/``. Every table comes in two variants: failed forecasts
scored as issued (real WIS, not covered), and failed forecasts dropped. The STOP 4 selection
(M1 + pooled conformal) stands whatever this shows.
"""

from __future__ import annotations

import logging

import pandas as pd

from nhs_ae.calibrate import g1
from nhs_ae.config import PROCESSED_DIR, PROJECT_ROOT
from nhs_ae.evaluate import stage_d, stage_e, stage_f, stage_g
from nhs_ae.evaluate.asof import load_truth, load_vintages
from nhs_ae.evaluate.harness import score_forecasts, truth_long
from nhs_ae.evaluate.splits import DEV, split_origins
from nhs_ae.features.hierarchy import current_region_map, icb_region_map
from nhs_ae.ingest.recover import month_range

log = logging.getLogger(__name__)

DW = PROCESSED_DIR / "stage_d_g1"
FW = PROCESSED_DIR / "stage_f_g1"
D_RESULTS = PROJECT_ROOT / "results" / "D-calibration-G1"
F_RESULTS = PROJECT_ROOT / "results" / "F-reconciliation-G1"
ISSUED, DROPPED = "as_issued", "failed_dropped"
assert {DW, FW}.isdisjoint({stage_d.WORK, stage_f.WORK, stage_e.WORK})
assert {D_RESULTS, F_RESULTS}.isdisjoint({stage_d.RESULTS, stage_f.RESULTS})


def _cached(path, build) -> pd.DataFrame:
    if path.exists():
        return pd.read_parquet(path)
    df = build()
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return df


def _count(model: str, level: str, fc: pd.DataFrame, last: pd.DataFrame, under_g1: bool) -> tuple:
    """Failed forecasts of one model at one level, and a row describing them."""
    z = g1.all_zero(fc, last)
    failed = z.loc[z["last_value"] > 0, [*g1.KEY, "level"]].reset_index(drop=True)
    dev = failed["origin"] >= pd.Timestamp(DEV[0])
    row = {"model": model, "level": level, "under_g1": under_g1, "forecasts": fc.groupby(g1.KEY).ngroups,
           "all_zero": len(z), "all_zero_last_zero": int((z["last_value"] == 0).sum()),
           "all_zero_no_history": int(z["last_value"].isna().sum()), "failed": len(failed),
           "failed_dev_origins": int(dev.sum()),
           "failed_origins": ", ".join(sorted(failed["origin"].dt.strftime("%Y-%m").unique()))}
    return (failed if under_g1 else None), row


def _write_md(path, title: str, body: str) -> None:
    path.write_text(f"# {title}\n\n{body}\n")


# ---- Stage D: the STOP 4 table ----------------------------------------------------------
def run_d(jobs: int, meta: dict) -> str:
    from nhs_ae.evaluate.stage_g import md_table
    v = load_vintages()
    origins = month_range(stage_d.BURN_IN_START, DEV[1])
    last = _cached(DW / "last_observed_provider.parquet",
                   lambda: g1.last_observed(v, origins, ("provider",), region_map=current_region_map(v)))
    failed, counts, by_model = {}, [], {}
    for name, calibrated_base in stage_d.BASES.items():
        fc = stage_d.base_forecasts(name, v, jobs, read_only=True)
        f, row = _count(fc["model"].iloc[0], "provider", fc, last, under_g1=calibrated_base)
        counts.append(row)
        if calibrated_base:                    # B1 and M1 v3 raw: the bases G1 applies to here
            failed[name] = by_model[fc["model"].iloc[0]] = f
    counts = pd.DataFrame(counts)
    cands = stage_d.candidates(v, jobs, failed=failed, read_only=True)
    truth = truth_long(load_truth(v, current_region_map(v)), ("provider",),
                       tuple(sorted({t for fc in cands.values() for t in fc["target"].unique()})))
    scored = []
    for model, fc in cands.items():
        s, dropped = score_forecasts(fc[fc["origin"] >= pd.Timestamp(DEV[0])], truth)
        s = g1.mark(s, by_model.get(model.split("+")[0]), g1.KEY)
        log.info("scored %-28s %8d rows, %d failed, dropped %s", model, len(s), s["failed"].sum(), dropped)
        scored.append(s)
    scores = pd.concat(scored, ignore_index=True)
    scores.to_parquet(DW / "scores.parquet", index=False)
    scored_failed = scores[scores["failed"]].groupby("model").size().rename("failed_scored")

    D_RESULTS.mkdir(parents=True, exist_ok=True)
    tabs, texts = {}, []
    for variant, s in ((ISSUED, scores), (DROPPED, scores[~scores["failed"]])):
        cells = stage_d.coverage_cells(s)
        cells_t = stage_d.coverage_cells(s, by_target=True)
        wis, gm = stage_d.wis_table(s)
        par = stage_d.pareto(stage_d.acceptance(cells), gm)
        tabs[variant] = (pd.concat([cells.assign(target="all"), cells_t]).assign(variant=variant),
                         wis.assign(variant=variant), par.assign(variant=variant))
        stage_d._fig_pareto(par, D_RESULTS / f"fig_pareto_{variant}.png")
        how = "scored as issued" if variant == ISSUED else "dropped"
        texts.append(stage_d.stop4_text(cells, par, title=f"STOP 4 with G1, failed forecasts {how} "
                                        "— DEV, as-of, provider, pooled over targets (exploratory)"))
    for i, fname in enumerate(("coverage_by_horizon_year.csv", "wis_winter_h3.csv", "pareto.csv")):
        pd.concat([tabs[ISSUED][i], tabs[DROPPED][i]]).to_csv(D_RESULTS / fname, index=False)
    counts = counts.merge(scored_failed, left_on="model", right_index=True, how="left").fillna({"failed_scored": 0})
    counts.to_csv(D_RESULTS / "failed_counts.csv", index=False)

    orig = pd.read_csv(stage_d.RESULTS / "pareto.csv")
    cols = ["gm_rel_to_ets", "worst_dev", "cells_in_band", "cells", "meets", "pareto"]
    cmp = orig[["model", *cols]].merge(tabs[ISSUED][2][["model", *cols]], on="model", suffixes=("", "_g1")).merge(
        tabs[DROPPED][2][["model", *cols]].add_suffix("_g1_dropped").rename(columns={"model_g1_dropped": "model"}),
        on="model")
    cmp.insert(1, "label", cmp["model"].map(lambda m: stage_d.LABELS.get(m, m)))
    cmp.to_csv(D_RESULTS / "comparison_with_original.csv", index=False)

    def fmt(p, suffix):
        return [f"{100 * a:+.1f}% / {100 * b:.1f} pp / {int(c)}/{int(d)}{' MEETS' if m else ''}{' pareto' if p_ else ''}"
                for a, b, c, d, m, p_ in zip(*(p[f"{c}{suffix}"] for c in cols))]
    show = pd.DataFrame({"candidate": cmp["label"], "original (no G1)": fmt(cmp, ""),
                         "G1, failed as issued": fmt(cmp, "_g1"), "G1, failed dropped": fmt(cmp, "_g1_dropped")})
    # the registered STOP 4 rule, as Stage G applied it (occupancy check failed: no decision loss)
    mmd = stage_g._mmd_cov()
    winner = {k: stage_g.select_candidate(tabs[k][2], None, False, mmd) for k in tabs}
    fs = scores["failed"]
    text = "\n\n".join(texts)
    (D_RESULTS / "stop4.txt").write_text(text + "\n")
    _write_md(D_RESULTS / "README.md", "results/D-calibration-G1",
              f"The STOP 4 table re-run on DEV with guard G1 (pre-flight item P2; amendment \"Guard G1 "
              f"registered\", 2026-09-13), run {meta.get('date', '?')} at commit `{meta.get('sha', '?')}`. "
              "**Exploratory.** The STOP 4 selection (M1 + pooled conformal) stands whatever this shows.\n\n"
              "Same base forecasts, first-release table, scoring and tables as `results/D-calibration/` (read, "
              "never rewritten). What changes: a failed forecast (all nine quantiles exactly zero while the "
              "series' last as-of month is positive) of B1 or M1 v3 raw is kept out of every calibration pool, "
              "DtACI updates included, and issued as produced. Failed forecasts are scored as issued (real WIS, "
              "not covered); every table is also given with them dropped (`variant` column).\n\n"
              "## Failed forecasts\n\n" + md_table(counts, index=False) + "\n\n"
              "`under_g1` False: M1 v3 (in-model CQR) and EnbPI are not base models under G1; their all-zero "
              "forecasts are counted, not treated.\n\n"
              "## Pareto / acceptance against the original\n\nEach cell: winter h3 WIS vs raw ETS (geometric "
              "mean over targets) / worst assessable cell |cov90 − 0.90| / cells in band.\n\n"
              + md_table(show, index=False) + "\n\n"
              "**The registered STOP 4 rule applied to these tables** (as in `results/D-calibration/decision_loss.md`): "
              + "; ".join(f"{k.replace('_', ' ')}: **{stage_d.LABELS.get(m, m)}** ({why})"
                          for k, (m, why) in winner.items()) + ". The selection made at STOP 4 stands either way.\n\n"
              f"**Where the failed forecasts fall.** Scored rows of failed forecasts: {int(fs.sum())}, over "
              f"{scores.loc[fs, 'model'].nunique()} candidates, at origins "
              f"{', '.join(sorted(scores.loc[fs, 'origin'].dt.strftime('%Y-%m').unique())) or 'none'}; in a winter-h3 "
              f"WIS: {int((fs & scores['winter'] & (scores['horizon'] == 3)).sum())}; in an assessable coverage "
              f"cell: {int((fs & stage_d.assessable(scores)).sum())}. Where both are zero the two variants "
              "coincide, and G1 acts on these tables only through the pools of later origins, which no longer "
              "hold the failed forecasts' scores.\n\n"
              "## Files\n\n- `stop4.txt`: the STOP 4 table in both variants\n- `pareto.csv`, "
              "`coverage_by_horizon_year.csv`, `wis_winter_h3.csv`: as in `results/D-calibration/`, with a "
              "`variant` column\n- `comparison_with_original.csv`: Pareto columns side by side\n"
              "- `failed_counts.csv`: failed forecasts per model\n- `fig_pareto_as_issued.png`, "
              "`fig_pareto_failed_dropped.png`\n")
    return text


# ---- Stage F ----------------------------------------------------------------------------
POST_HOC = {"ETS + pooled": ("b1", "base"), "ETS + pooled + MinT": ("b1", "mint"),
            "M1 + pooled": ("m1_v3_raw", "base"), "M1 + pooled + MinT": ("m1_v3_raw", "mint")}
M2 = (("M2f-r4 (phase 1b)", "m2f_r4"), ("M2 frozen (m2d_corr)", "m2d_corr"))


def run_f(meta: dict) -> str:
    from nhs_ae.evaluate.stage_g import md_table
    v = load_vintages()
    missing = [p for n in stage_f.BASE_MODELS for lv in stage_f.LEVELS
               if not (p := stage_f._path("base", n, lv)).exists()]
    if missing:
        raise RuntimeError(f"base forecasts missing, and this run may not generate them: {missing}")
    last = _cached(FW / "last_observed.parquet",
                   lambda: g1.last_observed(v, stage_f.origins_all(), stage_f.LEVELS, regions=icb_region_map(),
                                            region_map=current_region_map(v)))
    failed, counts = {}, []
    for n in stage_f.BASE_MODELS:
        for lv in stage_f.LEVELS:
            f, row = _count(stage_f.LABELS[n], lv, pd.read_parquet(stage_f._path("base", n, lv)), last, True)
            failed[(n, lv)] = f
            counts.append(row)
    counts = pd.DataFrame(counts)
    icb_of = stage_f.members(v).to_dict()
    region_of = icb_region_map().to_dict()
    truth = stage_f.truth_all(v)
    key = [*g1.KEY, "level"]
    fcs, scored, n_scored = {}, {}, {}
    for n in stage_f.BASE_MODELS:
        fl = {lv: failed[(n, lv)] for lv in stage_f.LEVELS}
        fall = pd.concat(fl.values(), ignore_index=True)
        fcs[(n, "base")] = pd.concat([stage_f.calibrated(n, lv, v, FW, fl[lv]) for lv in stage_f.LEVELS],
                                     ignore_index=True)
        fcs[(n, "mint")] = stage_f.reconcile_model(n, v, work=FW, failed=fl)
        for kind in ("base", "mint"):
            s = g1.mark(stage_f.score(fcs[(n, kind)], truth, f"{n}/{kind}"), fall, key)
            scored[(n, kind)] = s
            n_scored.update({(stage_f.LABELS[n], lv, kind): c for lv, c in s[s["failed"]].groupby("level").size().items()})
    for kind in ("base", "mint"):
        counts[f"failed_scored_{kind}"] = [n_scored.get((m, lv, kind), 0) for m, lv in zip(counts["model"], counts["level"])]
    dropped = {k: s[~s["failed"]] for k, s in scored.items()}
    h3 = {ISSUED: stage_f.h3_table(scored), DROPPED: stage_f.h3_table(dropped)}

    contenders, f2_scored, contenders_d, f2_scored_d = {}, {}, {}, {}
    for label, (n, kind) in POST_HOC.items():
        fall = pd.concat([failed[(n, lv)] for lv in stage_f.LEVELS], ignore_index=True)
        fc = fcs[(n, kind)]
        contenders[label], f2_scored[label] = fc, scored[(n, kind)]
        contenders_d[label], f2_scored_d[label] = fc[~g1.mask(fc, fall, key)], dropped[(n, kind)]
    for label, rung in M2:
        fc = pd.read_parquet(stage_e.WORK / f"forecasts_{rung}.parquet")
        s = stage_f.score(fc, truth, label).assign(failed=False)
        contenders[label] = contenders_d[label] = fc
        f2_scored[label] = f2_scored_d[label] = s
    f2 = {ISSUED: stage_f.f2_table(contenders, f2_scored, icb_of, region_of),
          DROPPED: stage_f.f2_table(contenders_d, f2_scored_d, icb_of, region_of)}
    dev = pd.to_datetime(pd.Index(split_origins("dev")))
    blowups = stage_f.calibration_blowups(dev, work=FW)
    return report_f(h3, f2, blowups, counts, meta, md_table, residual(dev, last))


def residual(dev: pd.DatetimeIndex, last: pd.DataFrame) -> pd.DataFrame:
    """Blow-ups G1 leaves: guarded calibrated forecasts with a 97.5% quantile above ten times the
    median, how many reach a winter-h3 cell, and the base forecasts G1 does not catch because only
    some of their quantiles are zero (median zero, series last observed positive)."""
    from nhs_ae.evaluate.harness import WINTER_MONTHS
    rows = []
    for n in stage_f.BASE_MODELS:
        for lv in stage_f.LEVELS:
            c = pd.read_parquet(stage_f._path("cal", n, lv, FW))
            w = c[c["origin"].isin(dev)].pivot_table(index=["origin", "target", "series", "horizon", "period"],
                                                     columns="quantile", values="value")
            bad = w[w[0.975] > 10 * w[0.5].clip(lower=1)].reset_index()
            b = pd.read_parquet(stage_f._path("base", n, lv))
            b = b[b["origin"].isin(dev)].pivot_table(index=["origin", "target", "series", "horizon"],
                                                     columns="quantile", values="value")
            part = b[(b[0.5] == 0) & (b.max(axis=1) > 0)].reset_index().merge(
                last[last["level"] == lv], on=["origin", "target", "series"], how="left")
            part = part[part["last_value"] > 0]
            rows.append({"base": stage_f.LABELS[n], "level": lv, "cal_q975_over_10x_median": len(bad),
                         "winter_h3": int(((bad["horizon"] == 3) & bad["period"].dt.month.isin(WINTER_MONTHS)).sum()),
                         "window": f"{bad['origin'].min():%Y-%m}..{bad['origin'].max():%Y-%m}" if len(bad) else "",
                         "base_median_zero_not_failed": len(part),
                         "their_origins": ", ".join(sorted(part["origin"].dt.strftime("%Y-%m").unique())[:6])})
    return pd.DataFrame(rows)


def report_f(h3: dict, f2: dict, blowups: pd.DataFrame, counts: pd.DataFrame, meta: dict, md_table,
             resid: pd.DataFrame) -> str:
    pct = stage_f._pct
    F_RESULTS.mkdir(parents=True, exist_ok=True)
    pd.concat([t.assign(variant=k) for k, t in h3.items()]).to_csv(F_RESULTS / "h3_results.csv", index=False)
    pd.concat([t.assign(variant=k) for k, t in f2.items()]).to_csv(F_RESULTS / "coherence_vs_calibration.csv",
                                                                    index=False)
    blowups.to_csv(F_RESULTS / "calibration_blowups.csv", index=False)
    counts.to_csv(F_RESULTS / "failed_counts.csv", index=False)
    resid.to_csv(F_RESULTS / "residual_blowups.csv", index=False)
    for k, t in f2.items():
        stage_f._fig_f2(t, F_RESULTS / f"fig_f2_coverage_{k}.png")

    orig = pd.read_csv(stage_f.RESULTS / "h3_results.csv")
    def cell(r):
        return f"{pct(r['rel'])} [{pct(r['rel_lo'])}, {pct(r['rel_hi'])}]"
    cmp = orig[["base", "level"]].copy()
    cmp["original (no G1)"] = orig.apply(cell, axis=1)
    for k, t in h3.items():
        cmp = cmp.merge(t[["base", "level"]].assign(**{f"G1, {k.replace('_', ' ')}": t.apply(cell, axis=1)}),
                        on=["base", "level"], how="outer")
    verdicts = pd.DataFrame({"base": orig.drop_duplicates("base")["base"]})
    verdicts["original"] = verdicts["base"].map(orig.drop_duplicates("base").set_index("base")["H3"])
    for k, t in h3.items():
        verdicts[f"G1, {k.replace('_', ' ')}"] = verdicts["base"].map(t.drop_duplicates("base").set_index("base")["H3"])

    orig_b = pd.read_csv(stage_f.RESULTS / "calibration_blowups.csv")
    bl = orig_b[["base", "level", "cal_q975_over_10x_median"]].merge(
        blowups[["base", "level", "cal_q975_over_10x_median"]], on=["base", "level"], suffixes=(" original", " G1"))

    def f2_show(t):
        f = t[["model", "level", "coh_gap_mean", "wis_rel_m1", "cov90", "cov50", "cov90_out", "n"]].copy()
        f["coh_gap_mean"] = f["coh_gap_mean"].map(lambda x: "" if pd.isna(x) else f"{100 * x:.2f}%")
        f["wis_rel_m1"] = f["wis_rel_m1"].map(pct)
        for c in ("cov90", "cov50", "cov90_out"):
            f[c] = f[c].map(lambda x: f"{x:.2f}")
        return f
    text_lines = ["STOP 7 with G1 (exploratory DEV re-run) — H3, winter h=3 WIS, reconciled vs calibrated base:"]
    for k, t in h3.items():
        text_lines.append(f"  [{k}]")
        for _, r in t.iterrows():
            text_lines.append(f"    {r['base']:10s} {r['level']:8s} {pct(r['rel']):>8s} "
                              f"[{pct(r['rel_lo'])}, {pct(r['rel_hi'])}]  outside COVID {pct(r['rel_outside_covid'])}")
        for base, g in t.groupby("base", sort=False):
            text_lines.append(f"    H3 {base}: {g['H3'].iloc[0]} (ICB improves: {g['icb_improves'].iloc[0]}, "
                              f"provider within +2%: {g['provider_within_2pct'].iloc[0]})")
    text = "\n".join(text_lines)
    (F_RESULTS / "stop7.txt").write_text(text + "\n")
    _write_md(F_RESULTS / "README.md", "results/F-reconciliation-G1",
              f"Stage F re-run on DEV with guard G1 (pre-flight item P2; amendment \"Guard G1 registered\", "
              f"2026-09-13), run {meta.get('date', '?')} at commit `{meta.get('sha', '?')}`. **Exploratory.** "
              "H3's confirmatory test is Stage H on CONF; this re-run changes no registered decision.\n\n"
              "Same base forecasts, first-release tables, scoring and H3 rule as `results/F-reconciliation/` "
              "(read, never rewritten). What changes: a failed base forecast (all nine quantiles exactly zero "
              "while the series' last as-of month at that level is positive) is kept out of the pooled "
              "conformal sets, the MinT error covariance and the reconciliation inputs (a failed provider joins "
              "its ICB's rest node; a failed aggregate drops out of S), and is issued as produced. Failed "
              "forecasts are scored as issued (real WIS, not covered); every table is also given with them "
              "dropped.\n\n## Failed forecasts per base model and level\n\n" + md_table(counts, index=False)
              + "\n\n## H3 verdicts\n\n" + md_table(verdicts, index=False) + "\n\n"
              "## H3: winter h=3 WIS, reconciled against calibrated base (negative = reconciliation helps)\n\n"
              + md_table(cmp, index=False) + "\n\n"
              "## Calibrated forecasts with a 97.5% quantile above ten times the median\n\n"
              + md_table(bl, index=False) + "\n\n"
              "## What G1 leaves\n\nG1 as registered catches a forecast only when all nine quantiles are "
              "zero. A forecast whose median is zero but whose upper quantiles are not still enters the pools, "
              "and its inner intervals (50%, 80%) score about the log of the outturn, as a failed forecast "
              "would. DEV origins; `winter_h3`: flagged forecasts that fall in a winter-h3 cell, the cells H3 "
              "scores; `base_median_zero_not_failed`: base forecasts with a zero median, some positive "
              "quantile and a positive last observed month.\n\n" + md_table(resid, index=False) + "\n\n"
              "D4 = (a) registered G1 alone, with no cap and no minimum pool, so that no calibration method "
              "is invented after seeing DEV results; this run changes nothing about that.\n\n"
              "## F2 (35 ladder origins), failed forecasts as issued\n\n" + md_table(f2_show(f2[ISSUED]), index=False)
              + "\n\n## F2, failed forecasts dropped\n\n" + md_table(f2_show(f2[DROPPED]), index=False) + "\n\n"
              "## Files\n\n- `h3_results.csv`, `coherence_vs_calibration.csv`: as in `results/F-reconciliation/`, "
              "with a `variant` column\n- `failed_counts.csv`, `calibration_blowups.csv`, `residual_blowups.csv`\n"
              "- `fig_f2_coverage_as_issued.png`, `fig_f2_coverage_failed_dropped.png`\n- `stop7.txt`\n")
    return text


def main(argv=None) -> int:
    import argparse
    import subprocess
    p = argparse.ArgumentParser(prog="python -m nhs_ae.evaluate.g1_rerun")
    p.add_argument("--jobs", type=int, default=8)
    p.add_argument("--stage", choices=("d", "f", "both"), default="both")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                         check=False).stdout.strip()
    meta = {"date": pd.Timestamp.now(tz="Europe/London").date().isoformat(), "sha": sha}
    if args.stage in ("d", "both"):
        print(run_d(args.jobs, meta))
    if args.stage in ("f", "both"):
        print(run_f(meta))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
