"""Exploratory, DEV-only analyses of M2f-r4 (phase 1b; work order of 2026-09-11).

Task 1 recomputes the COVID-window split of M2f-r4's ICB winter-h3 WIS against raw ETS that
``docs/m2f_redesign.md`` reports without an artefact (and the same split for M2f-r3 and the
frozen ``m2d_corr``, from the same table). Task 2, run only after its amendment row is
committed, evaluates an equal-weight quantile average of raw ETS and M2f-r4.

Inputs are the cached forecast tables, read directly and validated: ``stage_e.run_rung`` would
return any cache without checking its origins. Outputs go to new paths only. Nothing here
passes an unseal token, so ``score_forecasts`` raises on any CONF origin and drops embargoed
target months (DEV origins late in 2023 that reach into 2024).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from nhs_ae.config import PROCESSED_DIR, PROJECT_ROOT
from nhs_ae.evaluate import stage_d, stage_e
from nhs_ae.evaluate.asof import TARGETS, load_vintages
from nhs_ae.evaluate.harness import score_forecasts
from nhs_ae.evaluate.metrics import paired_bootstrap

log = logging.getLogger(__name__)

RESULTS = PROJECT_ROOT / "results" / "E-ensemble"
CACHE = PROCESSED_DIR / "stage_e"
COLS = ["origin", "mode", "model", "level", "target", "series", "horizon", "period",
        "quantile", "value", "scale"]
KEYS = ("series", "origin", "horizon", "period")
N_BOOT, SEED = 1000, 0
EXCLUDE = ("UNMAPPED", "LEGACY")
RUNGS = ("m2f_r4", "m2f_r3", "m2d_corr")
# docs/m2f_redesign.md, "Exploratory split by the COVID window": ICB winter-h3 WIS against raw
# ETS, (outside, inside). No artefact was committed behind these figures.
CLAIMED = {"m2f_r4": (-0.001, 0.917), "m2f_r3": (0.004, 0.149), "m2d_corr": (0.134, 0.124)}
REPRO_TOL = 0.005                                     # |recomputed − claimed| for "reproduced"


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ladder() -> pd.DatetimeIndex:
    return pd.to_datetime(pd.Index(stage_e.ladder_origins()))


def load_icb(name: str) -> tuple[pd.DataFrame, dict]:
    """ICB-level forecasts on the 35 ladder origins, validated, with provenance."""
    path = CACHE / ("comparator_b1.parquet" if name == "ets_raw" else f"forecasts_{name}.parquet")
    fc = pd.read_parquet(path)
    fc = fc[(fc["level"] == "icb") & fc["origin"].isin(ladder()) & ~fc["series"].isin(EXCLUDE)].copy()
    got = set(fc["origin"].unique())
    if got != set(ladder()):
        raise RuntimeError(f"{path.name}: {len(got)} ladder origins, expected {len(ladder())}")
    if (fc["origin"] >= pd.Timestamp("2024-01-01")).any():
        raise RuntimeError(f"{path.name}: CONF origin present")
    meta = {"name": name, "file": str(path.relative_to(PROCESSED_DIR.parent.parent)),
            "sha256": sha256(path),
            "modified": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds"),
            "model_column": ",".join(sorted(fc["model"].astype(str).unique())),
            "origins": len(got), "icbs": fc["series"].nunique()}
    fc["model"] = name
    return fc, meta


def score(fc: pd.DataFrame, truth: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    s, dropped = score_forecasts(fc[COLS], truth)          # no token: embargoed rows dropped
    s["window"] = np.where(stage_d.assessable(s), "outside", "inside")
    return s, dropped


def winter_h3(s: pd.DataFrame) -> pd.DataFrame:
    return s[s["winter"] & (s["horizon"] == 3)]


def compare(ref: pd.DataFrame, test: pd.DataFrame) -> dict:
    """Per-target paired bootstrap over ICBs (reference a, tested b; negative = tested better)
    plus the geometric mean over targets with a joint bootstrap interval (the same ICB resample
    for all three targets)."""
    out, per_unit = {}, {}
    for t in TARGETS:
        a, b = ref[ref["target"] == t], test[test["target"] == t]
        r = paired_bootstrap(a, b, metric="wis", unit="series", n=N_BOOT, seed=SEED, keys=KEYS)
        out[t] = r
        m = a[[*KEYS, "wis"]].merge(b[[*KEYS, "wis"]], on=list(KEYS), suffixes=("_a", "_b"))
        per_unit[t] = m.groupby("series")[["wis_a", "wis_b"]].mean()
    common = sorted(set.intersection(*(set(p.index) for p in per_unit.values())))
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, len(common), size=(N_BOOT, len(common)))
    logs = np.zeros(N_BOOT)
    for t in TARGETS:
        p = per_unit[t].loc[common]
        ua, ub = p["wis_a"].to_numpy(), p["wis_b"].to_numpy()
        logs += np.log1p(ub[idx].mean(axis=1) / ua[idx].mean(axis=1) - 1)
    gm_draws = np.exp(logs / len(TARGETS)) - 1
    gm = float(np.exp(np.mean([np.log1p(out[t]["rel"]) for t in TARGETS])) - 1)
    out["gm"] = {"rel": gm, "rel_lo": float(np.percentile(gm_draws, 2.5)),
                 "rel_hi": float(np.percentile(gm_draws, 97.5)), "n_units": len(common)}
    return out


def mmd() -> dict[str, float]:
    """Stage A minimum meaningful differences, winter h = 3 floor run, per target (fractions),
    plus their cross-target mean (the convention Stage E applied to gm)."""
    t = pd.read_csv(PROJECT_ROOT / "results" / "A-noise-floor" / "noise_table.csv")
    t = t[(t["run"] == "floor") & (t["slice"] == "winter_h3")].set_index("target")
    out = {k: float(t.loc[k, "mmd_wis_pct"]) / 100 for k in TARGETS}
    out["gm"] = float(np.mean([out[k] for k in TARGETS]))
    out.update({f"cov90_{k}": float(t.loc[k, "mmd_cov90_pp"]) / 100 for k in TARGETS})
    return out


def verify_covid_split() -> tuple[pd.DataFrame, dict]:
    """Task 1: ICB winter-h3 WIS of each rung against raw ETS, all / outside / inside COVID."""
    vintages = load_vintages()
    truth = stage_e.icb_truth(vintages)
    fc_ets, meta_ets = load_icb("ets_raw")
    s_ets, drop_ets = score(fc_ets, truth)
    metas, rows, origins = [meta_ets], [], {}
    floor = mmd()
    for rung in RUNGS:
        fc, meta = load_icb(rung)
        s, dropped = score(fc, truth)
        meta["dropped"] = dropped
        metas.append(meta)
        w_ref, w_test = winter_h3(s_ets), winter_h3(s)
        for win in ("all", "outside", "inside"):
            a = w_ref if win == "all" else w_ref[w_ref["window"] == win]
            b = w_test if win == "all" else w_test[w_test["window"] == win]
            origins[(rung, win)] = sorted(b["origin"].dt.strftime("%Y-%m").unique())
            res = compare(a, b)
            claim = None if win == "all" else CLAIMED[rung][0 if win == "outside" else 1]
            for key in (*TARGETS, "gm"):
                r = res[key]
                rows.append({
                    "model": rung, "window": win, "target": key,
                    "rel": r["rel"], "rel_lo": r["rel_lo"], "rel_hi": r["rel_hi"],
                    "n_icbs": r.get("n_units"), "n_pairs": r.get("n_pairs"),
                    "n_origins": len(origins[(rung, win)]),
                    "mmd": floor[key], "within_mmd_of_parity": abs(r["rel"]) <= floor[key],
                    "claimed": claim if key == "gm" else None,
                    "diff_vs_claimed": (r["rel"] - claim) if (key == "gm" and claim is not None) else None,
                    "reproduced": (abs(r["rel"] - claim) <= REPRO_TOL) if (key == "gm" and claim is not None) else None})
    table = pd.DataFrame(rows)
    info = {"inputs": metas, "ets_dropped": drop_ets, "origins": origins, "mmd": floor}
    return table, info


def _pct(x, digits: int = 1) -> str:
    return "" if x is None or pd.isna(x) else f"{100 * x:+.{digits}f}%"


def write_verification(table: pd.DataFrame, info: dict, meta: dict) -> str:
    from nhs_ae.evaluate.stage_g import md_table
    RESULTS.mkdir(parents=True, exist_ok=True)
    table.to_csv(RESULTS / "covid_split_verification.csv", index=False)
    show = table.assign(
        interval=[f"[{_pct(lo)}, {_pct(hi)}]" for lo, hi in zip(table["rel_lo"], table["rel_hi"])],
        rel=table["rel"].map(_pct), mmd=table["mmd"].map(lambda x: f"±{100 * x:.2f}%"),
        claimed=table["claimed"].map(_pct), diff_vs_claimed=table["diff_vs_claimed"].map(lambda x: _pct(x, 2)))
    cols = ["model", "window", "target", "rel", "interval", "n_icbs", "n_origins", "mmd",
            "within_mmd_of_parity", "claimed", "diff_vs_claimed", "reproduced"]
    gm = table[table["target"] == "gm"].set_index(["model", "window"])
    r4_out, r4_in = gm.loc[("m2f_r4", "outside")], gm.loc[("m2f_r4", "inside")]
    per_t_out = table[(table["model"] == "m2f_r4") & (table["window"] == "outside") & (table["target"] != "gm")]
    lines = [
        f"# M2f-r4 COVID-window split: verification (run {meta['date']} at `{meta['sha']}`)", "",
        "Exploratory, DEV only. ICB level; the 35 even-month DEV ladder origins; as-of; winter targets "
        "(December–March); h = 3; WIS relative to raw ETS at ICB level (negative = the M2 variant is "
        "better). *Outside* = origin and target month both outside 2020-03 to 2021-06 (Stage D's "
        "assessable rule); *inside* = the rest. Paired bootstrap over ICBs, 1,000 resamples, seed 0: "
        "per target with `paired_bootstrap`, and for the geometric mean (gm) over targets a joint "
        "bootstrap with the same ICB resample for all three targets. Embargoed targets (from origin "
        "2023-12) are dropped by the seal without a token. Rules fixed before computing: *reproduced* "
        f"if |recomputed gm − claimed| ≤ {100 * REPRO_TOL:.1f} pp; *at parity with ETS* if |gm| ≤ the "
        f"cross-target mean Stage A MMD ({100 * info['mmd']['gm']:.2f}%), each target also checked "
        "against its own MMD (Stage A floor run, winter h = 3: "
        + ", ".join(f"{t} {100 * info['mmd'][t]:.2f}%" for t in TARGETS) + ").", "",
        "## Verdict", "",
        f"- **Outside COVID, M2f-r4 vs raw ETS: gm {_pct(r4_out['rel'])} "
        f"[{_pct(r4_out['rel_lo'])}, {_pct(r4_out['rel_hi'])}]** on {int(r4_out['n_origins'])} origins "
        f"(claimed −0.1%: {'reproduced' if r4_out['reproduced'] else 'NOT reproduced'}, difference "
        f"{_pct(r4_out['diff_vs_claimed'], 2)}). "
        + ("Within the MMD of parity" if r4_out["within_mmd_of_parity"] else "NOT within the MMD of parity")
        + "; per target: " + "; ".join(
            f"{r.target} {_pct(r.rel)} [{_pct(r.rel_lo)}, {_pct(r.rel_hi)}] "
            f"({'within' if r.within_mmd_of_parity else 'outside'} ±{100 * r.mmd:.2f}%)"
            for r in per_t_out.itertuples()) + ".",
        (f"- **Inside COVID: gm {_pct(r4_in['rel'])} [{_pct(r4_in['rel_lo'])}, {_pct(r4_in['rel_hi'])}]** on "
         f"{int(r4_in['n_origins'])} origins ({', '.join(info['origins'][('m2f_r4', 'inside')])}) "
         f"(claimed +91.7%: {'reproduced' if r4_in['reproduced'] else 'NOT reproduced'}, difference "
         f"{_pct(r4_in['diff_vs_claimed'], 2)})."),
        f"- Winter-h3 origins outside the window: {', '.join(info['origins'][('m2f_r4', 'outside')])}.", "",
        "## All rows", "", md_table(show[cols], index=False), "",
        "## Inputs", "",
        md_table(pd.DataFrame([{k: v for k, v in m.items() if k != "dropped"} for m in info["inputs"]]), index=False),
        "", "Rows dropped at scoring (ETS; each rung in the CSV run log): " + str(info["ets_dropped"]), ""]
    text = "\n".join(lines)
    (RESULTS / "covid_split_verification.md").write_text(text)
    return text


# ---- Task 2: the ETS/M2f-r4 ensemble (amendment of 2026-09-11, committed at 588ef19) --------
ENS_KEYS = ["origin", "target", "series", "horizon", "period"]
AGG_LEVELS = ("region", "england")
RULE_GM_MMD = 0.0298                                  # cross-target mean Stage A MMD, as registered
GAP_LIMIT = 0.01


def load_level(name: str, level: str) -> tuple[pd.DataFrame, dict]:
    """ETS or M2f-r4 forecasts at ``level`` on the 35 ladder origins, validated, with provenance.
    ETS at region and England level is Stage F's raw ETS fitted to the summed ICB series."""
    if level == "icb":
        return load_icb(name)
    path = (PROCESSED_DIR / "stage_f" / f"base_b1_{level}.parquet" if name == "ets_raw"
            else CACHE / f"forecasts_{name}.parquet")
    fc = pd.read_parquet(path)
    fc = fc[(fc["level"] == level) & fc["origin"].isin(ladder())].copy()
    got = set(fc["origin"].unique())
    if got != set(ladder()) or (fc["origin"] >= pd.Timestamp("2024-01-01")).any():
        raise RuntimeError(f"{path.name} ({level}): {len(got)} ladder origins or a CONF origin")
    meta = {"name": f"{name} ({level})", "file": str(path.relative_to(PROCESSED_DIR.parent.parent)),
            "sha256": sha256(path),
            "modified": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds"),
            "model_column": ",".join(sorted(fc["model"].astype(str).unique())),
            "origins": len(got), "icbs": fc["series"].nunique()}
    fc["model"] = name
    return fc, meta


def _wide(fc: pd.DataFrame) -> pd.DataFrame:
    from nhs_ae.models.base import QUANTILES
    w = fc.set_index([*ENS_KEYS, "quantile"])["value"].unstack("quantile")
    return w[list(QUANTILES)]


def vincentise(ets: pd.DataFrame, m2f: pd.DataFrame, level: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Equal-weight pointwise average of the nine quantiles, sorted and floored at zero. A failed
    ETS forecast (all nine quantiles zero) or a missing one is excluded from the average, so that
    forecast is M2f-r4 alone. Returns the ensemble (long) and a table of the exclusions."""
    we, wm = _wide(ets), _wide(m2f)
    idx = we.index.intersection(wm.index)
    if len(idx) != len(wm.index):
        raise RuntimeError(f"{level}: {len(wm.index) - len(idx)} M2f-r4 forecasts have no ETS row")
    we, wm = we.loc[idx], wm.loc[idx]
    if wm.isna().any(axis=1).any():
        raise RuntimeError(f"{level}: M2f-r4 has missing quantiles")
    failed = (we.fillna(-1.0) == 0.0).all(axis=1)
    missing = we.isna().any(axis=1)
    alone = (failed | missing).to_numpy()
    vals = np.where(alone[:, None], wm.to_numpy(), (we.to_numpy() + wm.to_numpy()) / 2.0)
    vals = np.maximum(np.sort(vals, axis=1), 0.0)
    ens = pd.DataFrame(vals, index=idx, columns=we.columns).stack().rename("value").reset_index()
    scale = ets.drop_duplicates(ENS_KEYS).set_index(ENS_KEYS)["scale"]
    ens["scale"] = scale.reindex(pd.MultiIndex.from_frame(ens[ENS_KEYS])).to_numpy()
    ens["mode"], ens["model"], ens["level"] = "asof", "ensemble", level
    excl = pd.DataFrame({"level": level, "failed_all_zero": failed.to_numpy(), "missing": missing.to_numpy()},
                        index=idx).reset_index()
    return ens[COLS], excl[excl["failed_all_zero"] | excl["missing"]]


def coverage_table(scored: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for name, s in scored.items():
        for level, g in s.groupby("level"):
            for win in ("all", "outside", "inside"):
                gw = g if win == "all" else g[g["window"] == win]
                for h, gh in gw.groupby("horizon"):
                    rows.append({"model": name, "level": level, "window": win, "horizon": int(h),
                                 "cov90": gh["cov90"].mean(), "cov50": gh["cov50"].mean(), "n": len(gh)})
    return pd.DataFrame(rows)


def worst_dev(cov: pd.DataFrame, model: str, level: str = "icb", window: str = "all") -> dict:
    c = cov[(cov["model"] == model) & (cov["level"] == level) & (cov["window"] == window)]
    return {"cov90": float((c["cov90"] - 0.90).abs().max()), "cov50": float((c["cov50"] - 0.50).abs().max())}


def coherence_gaps(fc: pd.DataFrame, region_of: dict) -> pd.DataFrame:
    """|aggregate median − Σ children's medians| / aggregate median, per aggregate forecast
    (region: children are ICBs; England: children are regions)."""
    med = fc[np.isclose(fc["quantile"].astype(float), 0.5)]
    rows = []
    for level, child, parent_of in (("region", "icb", region_of), ("england", "region", None)):
        ch = med[med["level"] == child]
        ch = ch.assign(parent=ch["series"].map(parent_of) if parent_of else "ENGLAND")
        sums = ch.groupby(["origin", "target", "horizon", "period", "parent"])["value"].sum().rename("children")
        agg = med[med["level"] == level].set_index(["origin", "target", "horizon", "period", "series"])["value"]
        agg = agg.rename("agg")
        agg.index = agg.index.set_names("parent", level="series")
        j = pd.concat([agg, sums], axis=1, join="inner").reset_index()
        j["gap"] = (j["agg"] - j["children"]).abs() / j["agg"]
        j["level"] = level
        rows.append(j)
    out = pd.concat(rows, ignore_index=True)
    out["window"] = np.where(stage_d.assessable(out), "outside", "inside")
    return out


def evaluate_ensemble() -> dict:
    """Task 2: build the ensemble at every level, score it on DEV, and apply the registered rule."""
    from nhs_ae.features.hierarchy import icb_region_map
    vintages = load_vintages()
    truth = pd.concat([stage_e.icb_truth(vintages), stage_e.agg_truth(vintages)], ignore_index=True)
    fcs, metas, excluded = {"ets_raw": [], "m2f_r4": [], "ensemble": []}, [], []
    for level in ("icb", *AGG_LEVELS):
        ets, me = load_level("ets_raw", level)
        m2f, mm = load_level("m2f_r4", level)
        ens, excl = vincentise(ets, m2f, level)
        fcs["ets_raw"].append(ets.assign(level=level))
        fcs["m2f_r4"].append(m2f.assign(level=level))
        fcs["ensemble"].append(ens)
        metas += [me, mm]
        excluded.append(excl)
    fcs = {k: pd.concat(v, ignore_index=True) for k, v in fcs.items()}
    scored, dropped = {}, {}
    for name, fc in fcs.items():
        scored[name], dropped[name] = score(fc, truth)
    floor = mmd()
    rows = []
    icb = {k: winter_h3(v[v["level"] == "icb"]) for k, v in scored.items()}
    for ref, test in (("ets_raw", "ensemble"), ("m2f_r4", "ensemble"), ("ets_raw", "m2f_r4")):
        for win in ("all", "outside", "inside"):
            a = icb[ref] if win == "all" else icb[ref][icb[ref]["window"] == win]
            b = icb[test] if win == "all" else icb[test][icb[test]["window"] == win]
            res = compare(a, b)
            for key in (*TARGETS, "gm"):
                r = res[key]
                rows.append({"tested": test, "reference": ref, "window": win, "target": key,
                             "rel": r["rel"], "rel_lo": r["rel_lo"], "rel_hi": r["rel_hi"],
                             "n_icbs": r.get("n_units"), "n_origins": b["origin"].nunique(),
                             "mmd": floor[key]})
    wis = pd.DataFrame(rows)
    cov = coverage_table(scored)
    region_of = icb_region_map().to_dict()
    gaps = pd.concat([coherence_gaps(fc, region_of).assign(model=name) for name, fc in fcs.items()],
                     ignore_index=True)
    gap_summary = pd.concat([
        gaps.groupby(["model", "level"])["gap"].agg(mean="mean", max="max", n="size").reset_index().assign(window="all"),
        gaps[gaps["window"] == "outside"].groupby(["model", "level"])["gap"].agg(
            mean="mean", max="max", n="size").reset_index().assign(window="outside")], ignore_index=True)
    # ---- the registered verdict rule, applied mechanically ----
    vm = wis[(wis["tested"] == "ensemble") & (wis["reference"] == "m2f_r4") & (wis["window"] == "all")].set_index("target")
    d_ens, d_m2f = worst_dev(cov, "ensemble"), worst_dev(cov, "m2f_r4")
    gs = gap_summary[(gap_summary["model"] == "ensemble") & (gap_summary["window"] == "all")].set_index("level")["mean"]
    cond = {
        "(i) gm improvement over M2f-r4 > 2.98% and interval below zero":
            bool(vm.loc["gm", "rel"] < -RULE_GM_MMD and vm.loc["gm", "rel_hi"] < 0),
        "(ii) no target worsens by more than its own MMD":
            bool(all(vm.loc[t, "rel"] <= floor[t] for t in TARGETS)),
        "(iii) coverage guard (worst-horizon |cov − nominal|, ICB, all months, 90% and 50%)":
            bool(d_ens["cov90"] <= d_m2f["cov90"] and d_ens["cov50"] <= d_m2f["cov50"]),
        "(iv) coherence gap under 1% at region and England":
            bool(gs.loc["region"] < GAP_LIMIT and gs.loc["england"] < GAP_LIMIT)}
    verdict = "ENSEMBLE" if all(cond.values()) else "M2f-r4 alone"
    return {"wis": wis, "cov": cov, "gaps": gap_summary, "excluded": pd.concat(excluded, ignore_index=True),
            "metas": metas, "dropped": dropped, "cond": cond, "verdict": verdict,
            "worst": {"ensemble": d_ens, "m2f_r4": d_m2f, "ets_raw": worst_dev(cov, "ets_raw")}, "mmd": floor}


def write_ensemble(res: dict, meta: dict) -> str:
    RESULTS.mkdir(parents=True, exist_ok=True)
    res["wis"].to_csv(RESULTS / "ensemble_wis.csv", index=False)
    res["cov"].to_csv(RESULTS / "ensemble_coverage.csv", index=False)
    res["gaps"].to_csv(RESULTS / "ensemble_coherence.csv", index=False)
    res["excluded"].to_csv(RESULTS / "ensemble_failed_ets.csv", index=False)
    w, cov, gaps = res["wis"], res["cov"], res["gaps"]

    def wline(test, ref, win):
        g = w[(w["tested"] == test) & (w["reference"] == ref) & (w["window"] == win)].set_index("target")
        per = "  ".join(f"{t} {_pct(g.loc[t, 'rel'])} [{_pct(g.loc[t, 'rel_lo'])}, {_pct(g.loc[t, 'rel_hi'])}]"
                        for t in TARGETS)
        return (f"    {win:8s} gm {_pct(g.loc['gm', 'rel']):>7s} [{_pct(g.loc['gm', 'rel_lo'])}, "
                f"{_pct(g.loc['gm', 'rel_hi'])}]  ({int(g.loc['gm', 'n_origins'])} origins)   {per}")

    def cline(model, level, win):
        c = cov[(cov["model"] == model) & (cov["level"] == level) & (cov["window"] == win)].sort_values("horizon")
        return (f"    {model:9s} {win:8s} cov90 " + " ".join(f"{x:.2f}" for x in c["cov90"])
                + "   cov50 " + " ".join(f"{x:.2f}" for x in c["cov50"]))

    lines = [f"STOP — E-ensemble: ETS/M2f-r4 equal-weight quantile average (run {meta['date']} at `{meta['sha']}`)",
             ("  Exploratory, DEV only. 35 even-month ladder origins, as-of. Rule registered at 588ef19 before any "
              "ensemble score."), "",
             ("  Winter-h3 ICB WIS, relative change (negative = tested better); paired bootstrap over 36 ICBs, "
              "1,000, seed 0:")]
    for test, ref in (("ensemble", "m2f_r4"), ("ensemble", "ets_raw"), ("m2f_r4", "ets_raw")):
        lines.append(f"  {test} vs {ref}:")
        lines += [wline(test, ref, win) for win in ("all", "outside", "inside")]
    lines += ["", "  ICB coverage by horizon h1–h6:"]
    for win in ("all", "outside"):
        lines += [cline(m, "icb", win) for m in ("ets_raw", "m2f_r4", "ensemble")]
    lines += ["", "  Worst-horizon |coverage − nominal|, ICB, all months: " + "; ".join(
        f"{m} 90% {100 * d['cov90']:.1f} pp, 50% {100 * d['cov50']:.1f} pp" for m, d in res["worst"].items())]
    lines += ["", "  Coherence gap (mean |aggregate median − Σ children's medians| / aggregate median):"]
    for m in ("ets_raw", "m2f_r4", "ensemble"):
        g = gaps[gaps["model"] == m].set_index(["window", "level"])
        lines.append(f"    {m:9s} all months: region {100 * g.loc[('all', 'region'), 'mean']:.2f}%, "
                     f"England {100 * g.loc[('all', 'england'), 'mean']:.2f}%   outside COVID: region "
                     f"{100 * g.loc[('outside', 'region'), 'mean']:.2f}%, England "
                     f"{100 * g.loc[('outside', 'england'), 'mean']:.2f}%")
    ex = res["excluded"]
    lines += ["", f"  Failed or missing ETS forecasts excluded from the average: {int(ex['failed_all_zero'].sum())} "
              f"all-zero, {int(ex['missing'].sum())} missing (by level: "
              + (", ".join(f"{k} {v}" for k, v in ex.groupby('level').size().items()) or "none") + ")"]
    lines += ["", "  Registered verdict rule (all four must hold):"]
    lines += [f"    {'PASS' if ok else 'FAIL'}  {name}" for name, ok in res["cond"].items()]
    lines += ["", f"  VERDICT: {res['verdict']}"]
    text = "\n".join(lines)
    (RESULTS / "stop_ensemble.txt").write_text(text + "\n")
    return text


def main(argv=None) -> int:
    import argparse
    import subprocess
    p = argparse.ArgumentParser(prog="python -m nhs_ae.evaluate.stage_e_ensemble")
    p.add_argument("task", choices=["verify", "ensemble"])
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                         check=False, cwd=PROJECT_ROOT).stdout.strip()
    meta = {"date": pd.Timestamp.now(tz="Europe/London").date().isoformat(), "sha": sha}
    if args.task == "verify":
        table, info = verify_covid_split()
        print(write_verification(table, info, meta))
    else:
        res = evaluate_ensemble()
        print(write_ensemble(res, meta))
        import json
        (RESULTS / "ensemble_inputs.json").write_text(json.dumps(
            {"inputs": res["metas"], "dropped_at_scoring": res["dropped"], "mmd": res["mmd"]}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
