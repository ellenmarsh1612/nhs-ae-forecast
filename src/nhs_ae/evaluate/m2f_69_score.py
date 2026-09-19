"""WO-A step 3: rescore M2f-r4 on the 69-origin row set and apply the D1 condition mechanically.

The condition and how it is applied were committed before any fit (``docs/d1_precommitments.md``,
93704d0). DEV only; no token; scoring goes through the harness, which drops embargoed rows and
refuses CONF origins. Every figure is computed twice with the same code: on all 69 DEV origins
and on the 35 even-month origins (the ``b77430e`` ladder, reproduced bit for bit by the refit),
so each 69-origin figure sits beside its 35-origin counterpart.
"""

from __future__ import annotations

import json
import logging
import subprocess

import numpy as np
import pandas as pd

from nhs_ae.config import PROCESSED_DIR, PROJECT_ROOT
from nhs_ae.evaluate import m2f_69, stage_e
from nhs_ae.evaluate import stage_e_ensemble as E
from nhs_ae.evaluate import stage_e_exceedance as X
from nhs_ae.evaluate import stage_e_pit as P
from nhs_ae.evaluate.asof import load_vintages
from nhs_ae.evaluate.splits import split_origins
from nhs_ae.features.hierarchy import icb_region_map

log = logging.getLogger(__name__)

RESULTS = m2f_69.RESULTS
RHAT_ALL, RHAT_2023 = 1.10, 1.12
WIS_ANCHOR, WIS_MOVE, WIS_SEED = 0.235, 0.10, 0.002
COV_LO, COV_HI, COV_SEED = 0.85, 0.95, 0.010
GAP_LIMIT = 0.01
QSHIFT_SEED = 0.022
KEYS = ["origin", "level", "target", "series", "horizon", "period", "quantile"]


def dev69() -> pd.DatetimeIndex:
    return pd.to_datetime(pd.Index(split_origins("dev")))


def sets() -> dict[str, pd.DatetimeIndex]:
    return {"69": dev69(), "35": E.ladder()}


def _icb(path, name: str) -> pd.DataFrame:
    fc = pd.read_parquet(path)
    if "level" in fc:
        fc = fc[fc["level"] == "icb"]
    fc = fc[fc["origin"].isin(dev69()) & ~fc["series"].isin(E.EXCLUDE)].copy()
    if fc["origin"].nunique() != 69 or (fc["origin"] >= pd.Timestamp("2024-01-01")).any():
        raise RuntimeError(f"{path}: {fc['origin'].nunique()} DEV origins, expected 69")
    fc["model"], fc["level"] = name, "icb"
    return fc


def load() -> dict:
    m2f = pd.read_parquet(m2f_69.WORK / "forecasts_m2f_r4_69.parquet")
    m2f = m2f[~m2f["series"].isin(E.EXCLUDE)].copy()
    if m2f["origin"].nunique() != 69:
        raise RuntimeError("the 69-origin M2f-r4 table is incomplete")
    paths = {"m2f_r4": m2f_69.WORK / "forecasts_m2f_r4_69.parquet", "ets_raw": E.CACHE / "comparator_b1.parquet",
             "m1_pooled": PROCESSED_DIR / "stage_f" / "cal_m1_v3_raw_icb.parquet"}
    return {"m2f": m2f, "ets": _icb(paths["ets_raw"], "ets_raw"), "m1p": _icb(paths["m1_pooled"], "m1_pooled"),
            "inputs": [{"name": k, "file": str(p.relative_to(PROJECT_ROOT)), "sha256": E.sha256(p)}
                       for k, p in paths.items()]}


def reproduction(m2f: pd.DataFrame) -> dict:
    """The 35 even-origin refits against the committed ``b77430e`` table."""
    ref = pd.read_parquet(E.CACHE / "forecasts_m2f_r4.parquet")
    new = m2f[m2f["origin"].isin(E.ladder())]
    ref = ref[~ref["series"].isin(E.EXCLUDE)]
    j = new[KEYS + ["value"]].merge(ref[KEYS + ["value"]], on=KEYS, how="outer", suffixes=("_new", "_ref"))
    both = j["value_new"].notna() & j["value_ref"].notna()
    diff = (j.loc[both, "value_new"] - j.loc[both, "value_ref"]).abs()
    out = {"rows_refit": int(j["value_new"].notna().sum()), "rows_committed": int(j["value_ref"].notna().sum()),
           "rows_both": int(both.sum()), "max_abs_diff": float(diff.max()),
           "identical": bool(both.all() and (diff == 0).all())}
    if not out["identical"]:        # the seed-stability statistic, for the clause in (a)
        icb = j[both & (j["level"] == "icb")]
        w = icb.pivot_table(index=["origin", "target", "series", "horizon"], columns="quantile", values="value_ref")
        icb = icb.merge((w[0.75] - w[0.25]).rename("w50").reset_index(), on=["origin", "target", "series", "horizon"])
        out["median_shift_of_50pc_width"] = float(((icb["value_new"] - icb["value_ref"]).abs() / icb["w50"]).median())
    return out


def score_all(data: dict, truth: pd.DataFrame, agg: pd.DataFrame) -> dict[str, pd.DataFrame]:
    m2f = data["m2f"]
    s_icb, _ = E.score(m2f[m2f["level"] == "icb"], truth)
    s_agg, _ = E.score(m2f[m2f["level"] != "icb"], agg)
    s_ets, _ = E.score(data["ets"], truth)
    return {"m2f_icb": s_icb, "m2f_agg": s_agg, "ets": s_ets}


def wis_vs_ets(sc: dict) -> pd.DataFrame:
    rows = []
    for name, origins in sets().items():
        a = E.winter_h3(sc["ets"][sc["ets"]["origin"].isin(origins)])
        b = E.winter_h3(sc["m2f_icb"][sc["m2f_icb"]["origin"].isin(origins)])
        for win in ("all", "outside", "inside"):
            aw, bw = (a, b) if win == "all" else (a[a["window"] == win], b[b["window"] == win])
            res = E.compare(aw, bw)
            for key in (*E.TARGETS, "gm"):
                r = res[key]
                rows.append({"set": name, "window": win, "target": key, "rel": r["rel"], "rel_lo": r["rel_lo"],
                             "rel_hi": r["rel_hi"], "n_icbs": r.get("n_units"),
                             "n_origins": bw["origin"].nunique()})
    return pd.DataFrame(rows)


def coverage(sc: dict) -> pd.DataFrame:
    out = []
    for name, origins in sets().items():
        m2f = pd.concat([sc["m2f_icb"], sc["m2f_agg"]])
        scored = {"m2f_r4": m2f[m2f["origin"].isin(origins)], "ets_raw": sc["ets"][sc["ets"]["origin"].isin(origins)]}
        out.append(E.coverage_table(scored).assign(set=name))
    return pd.concat(out, ignore_index=True)


def coherence(m2f: pd.DataFrame) -> pd.DataFrame:
    regions = icb_region_map().to_dict()
    g = E.coherence_gaps(m2f, regions)
    out = []
    for name, origins in sets().items():
        gs = g[g["origin"].isin(origins)]
        for (level, win), x in [*gs.groupby(["level", "window"]), *[((lv, "all"), x) for lv, x in gs.groupby("level")]]:
            out.append({"set": name, "level": level, "window": win, "mean_gap": x["gap"].mean(),
                        "max_gap": x["gap"].max(), "n": len(x)})
    return pd.DataFrame(out)


def pit_exceedance(data: dict) -> dict[str, dict]:
    """E-pit's method (four models on common rows, near-zero outturns out, seeded ties) and the
    exceedance decomposition (ICB and origin clustering), on each origin set."""
    out = {}
    for name, origins in sets().items():
        ets = data["ets"][data["ets"]["origin"].isin(origins)]
        m2f = data["m2f"][(data["m2f"]["level"] == "icb") & data["m2f"]["origin"].isin(origins)].copy()
        m2f["model"] = "m2f_r4"
        ens, excl = E.vincentise(ets, m2f, "icb")
        m1p = data["m1p"][data["m1p"]["origin"].isin(origins)]
        fcs = {"ets_raw": ets, "m1_pooled": m1p, "m2f_r4": m2f, "ensemble": ens}
        supplied = (fcs, data["inputs"], len(excl))
        meta: dict = {}
        rows = P.build(meta, supplied)["rows"]
        hist, st = P.summarise(rows)
        out[name] = {"hist": hist, "stats": st, "meta": meta, "exceed": X.run(supplied, drop_nonpositive=True)}
    return out


def sampling() -> pd.DataFrame:
    a = pd.read_csv(m2f_69.WORK / "diagnostics_m2f_r4_69.csv", parse_dates=["origin"])
    b = pd.read_csv(PROJECT_ROOT / "results" / "E-m2-rerun69" / "diagnostics_69.csv", parse_dates=["origin"])
    rows = []
    for label, d in (("m2f_r4, 69", a), ("m2f_r4, 35 even", a[a["origin"].isin(E.ladder())]), ("m2d_corr, 69", b)):
        for yr, g in [*d.groupby(d["origin"].dt.year), ("all", d)]:
            rows.append({"model_set": label, "origin_year": yr, "fits": len(g),
                         "rhat_max_median": g["rhat_max"].median(), "rhat_max_worst": g["rhat_max"].max(),
                         "ess_bulk_min_median": g["ess_bulk_min"].median(), "ess_bulk_min_lowest": g["ess_bulk_min"].min(),
                         "divergences": int(g["divergences"].sum())})
    return pd.DataFrame(rows)


def d1(dg: pd.DataFrame, wis: pd.DataFrame, cov: pd.DataFrame, coh: pd.DataFrame) -> pd.DataFrame:
    """The four conditions of (a), as fixed in docs/d1_precommitments.md."""
    r_all = float(dg["rhat_max"].median())
    r_23 = float(dg.loc[dg["origin"].dt.year == 2023, "rhat_max"].median())
    gm = float(wis.query("set == '69' and window == 'all' and target == 'gm'")["rel"].iloc[0])
    move = gm - WIS_ANCHOR
    c = cov.query("set == '69' and model == 'm2f_r4' and level == 'icb' and window == 'all'").set_index("horizon")["cov90"]
    out_band = c[(c < COV_LO) | (c > COV_HI)]
    material = c[(c < COV_LO - COV_SEED) | (c > COV_HI + COV_SEED)]
    g = coh.query("set == '69' and window == 'all'").set_index("level")["mean_gap"]
    rows = [
        {"condition": "median max R-hat across the 69 fits > 1.10", "value": r_all, "limit": RHAT_ALL, "holds": r_all > RHAT_ALL},
        {"condition": "2023 median max R-hat > 1.12", "value": r_23, "limit": RHAT_2023, "holds": r_23 > RHAT_2023},
        {"condition": "winter-h3 ICB gm WIS vs raw ETS moves from +23.5% by > 10 pp", "value": gm, "limit": f"|{move:+.4f}| > {WIS_MOVE} (+{WIS_SEED} seed)",
         "holds": abs(move) > WIS_MOVE + WIS_SEED, "within_seed_noise": WIS_MOVE < abs(move) <= WIS_MOVE + WIS_SEED},
        {"condition": "90% ICB coverage (all months) outside [0.85, 0.95] at any horizon",
         "value": ", ".join(f"h{h} {v:.4f}" for h, v in c.items()), "limit": "[0.85, 0.95] (±0.010 seed)",
         "holds": len(material) > 0, "within_seed_noise": len(out_band) > 0 and len(material) == 0},
        {"condition": "mean coherence gap > 1% at region or England",
         "value": f"region {g['region']:.5f}, england {g['england']:.5f}", "limit": GAP_LIMIT,
         "holds": bool((g > GAP_LIMIT).any())}]
    return pd.DataFrame(rows)


def analyse() -> str:
    RESULTS.mkdir(parents=True, exist_ok=True)
    data = load()
    rep = reproduction(data["m2f"])
    vintages = load_vintages()
    sc = score_all(data, stage_e.icb_truth(vintages), stage_e.agg_truth(vintages))
    wis, cov, coh = wis_vs_ets(sc), coverage(sc), coherence(data["m2f"])
    samp = sampling()
    dg = pd.read_csv(m2f_69.WORK / "diagnostics_m2f_r4_69.csv", parse_dates=["origin"])
    cond = d1(dg, wis, cov, coh)
    verdict = "D1 EXCLUDE" if cond["holds"].any() else "D1 INCLUDE"
    pe = pit_exceedance(data)
    for name, res in pe.items():
        res["hist"].assign(set=name).to_csv(RESULTS / f"pit_histograms_{name}.csv", index=False)
        res["stats"].assign(set=name).to_csv(RESULTS / f"pit_stats_{name}.csv", index=False)
        for win in ("outside", "all"):
            for tab in ("pooled", "horizon", "target", "year", "slopes", "slopes_target"):
                res["exceed"][win][tab].assign(set=name, window=win).to_csv(
                    RESULTS / f"exceedance_{tab}_{win}_{name}.csv", index=False)
    wis.to_csv(RESULTS / "wis_vs_raw_ets.csv", index=False)
    cov.to_csv(RESULTS / "coverage.csv", index=False)
    coh.to_csv(RESULTS / "coherence.csv", index=False)
    samp.to_csv(RESULTS / "sampling_by_year.csv", index=False)
    dg.to_csv(RESULTS / "diagnostics_69.csv", index=False)
    cond.to_csv(RESULTS / "d1_conditions.csv", index=False)
    lines = [verdict, "",
             "Mechanical application of docs/d1_precommitments.md (a), committed at 93704d0 before any fit:"]
    lines += [f"  {'FLIPS' if r.holds else 'holds not'}  {r.condition}: {r.value} (limit {r.limit})"
              + ("  [crossing within seed noise: not a flip]" if isinstance(r.within_seed_noise, (bool, np.bool_))
                 and r.within_seed_noise else "")
              for r in cond.itertuples()]
    lines += ["", f"35 even-origin refits against b77430e: {rep}"]
    (RESULTS / "stop_m2f_freeze.txt").write_text("\n".join(lines) + "\n")
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False,
                         cwd=PROJECT_ROOT).stdout.strip()
    (RESULTS / "run.json").write_text(json.dumps(
        {"sha": sha, "verdict": verdict, "reproduction_35": rep, "inputs": data["inputs"],
         "pit_meta": {k: {kk: vv for kk, vv in v["meta"].items() if kk != "inputs"} for k, v in pe.items()},
         "exceedance_rows": {k: v["exceed"]["rows"] for k, v in pe.items()},
         "exceedance_nonpositive_median": {k: v["exceed"]["meta"].get("nonpositive_median") for k, v in pe.items()}},
        indent=1, default=str))
    return "\n".join(lines)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    print(analyse())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
