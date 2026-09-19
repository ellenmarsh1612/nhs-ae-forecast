"""Median-exceedance decomposition (work order of 2026-09-11; descriptive, DEV only).

Decomposes the "share of outturns above the predictive median" reported in results/E-pit/.
The rows are E-pit's rows, built by the same code (``stage_e_pit.build``): 21,708 ICB rows,
15,552 outside COVID, identical across raw ETS, M1 v3 raw + pooled conformal, M2f-r4 and the
ETS/M2f-r4 ensemble. "Above the median" is PIT bin ≥ 5, so the shares match E-pit's exactly,
ties included (E-pit's seeded placement). Nothing is refitted and no correction is fitted.

Intervals are cluster-robust (CR1) Wald intervals for a mean, clustered on ICB as the work
order asks, with an origin-clustered version alongside as a sensitivity: clustering on ICB
cannot see a national shock that moves every ICB at once, which is the dependence most
relevant to bias. The level-versus-drift rule, fixed before computing, is stated in
``verdict``.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from nhs_ae.config import PROJECT_ROOT
from nhs_ae.evaluate import stage_e_pit as P
from nhs_ae.evaluate.asof import TARGETS

log = logging.getLogger(__name__)

OUT = PROJECT_ROOT / "results" / "E-pit" / "exceedance"
Z = 1.959964
MIN_ORIGINS = 6                                       # Stage D's assessable origin-year rule


def cluster_mean(x: np.ndarray, g: np.ndarray) -> tuple[float, float]:
    """Mean of ``x`` and its CR1 cluster-robust standard error (clusters ``g``)."""
    n = len(x)
    m = float(x.mean())
    s = pd.Series(x - m).groupby(g).sum().to_numpy()
    k = len(s)
    return m, float(np.sqrt(k / (k - 1) * (s ** 2).sum()) / n) if k > 1 else float("nan")


def cluster_slope(x: np.ndarray, h: np.ndarray, g: np.ndarray) -> tuple[float, float]:
    """OLS slope of ``x`` on ``h`` with a CR1 cluster-robust standard error."""
    hc = h - h.mean()
    sxx = float((hc ** 2).sum())
    b = float((hc * (x - x.mean())).sum() / sxx)
    e = x - x.mean() - b * hc
    s = pd.Series(hc * e).groupby(g).sum().to_numpy()
    k = len(s)
    return b, float(np.sqrt(k / (k - 1) * (s ** 2).sum()) / sxx)


def cell(r: pd.DataFrame) -> dict:
    x = r["above"].to_numpy(float)
    rel = r["rel_err"].to_numpy(float)
    p, se_icb = cluster_mean(x, r["series"].to_numpy())
    _, se_org = cluster_mean(x, r["origin"].to_numpy())
    mr, se_rel = cluster_mean(rel, r["series"].to_numpy())
    naive = np.sqrt(p * (1 - p) / len(x))
    return {"n": len(x), "icbs": r["series"].nunique(), "origins": r["origin"].nunique(),
            "share_above": p, "lo_icb": max(p - Z * se_icb, 0.0), "hi_icb": min(p + Z * se_icb, 1.0),
            "lo_origin": max(p - Z * se_org, 0.0), "hi_origin": min(p + Z * se_org, 1.0),
            "design_effect_icb": (se_icb / naive) ** 2 if naive > 0 else np.nan,
            "mean_rel_err": mr, "rel_lo_icb": mr - Z * se_rel, "rel_hi_icb": mr + Z * se_rel,
            "median_rel_err": float(np.median(rel))}


def table(rows: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    out = []
    for keys, g in rows.groupby(by, sort=True):
        keys = keys if isinstance(keys, tuple) else (keys,)
        out.append({**dict(zip(by, keys)), **cell(g)})
    return pd.DataFrame(out)


def slopes(rows: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    out = []
    for keys, g in rows.groupby(by, sort=True):
        keys = keys if isinstance(keys, tuple) else (keys,)
        h = g["horizon"].to_numpy(float)
        b, se = cluster_slope(g["above"].to_numpy(float), h, g["series"].to_numpy())
        _, se_o = cluster_slope(g["above"].to_numpy(float), h, g["origin"].to_numpy())
        br, ser = cluster_slope(g["rel_err"].to_numpy(float), h, g["series"].to_numpy())
        out.append({**dict(zip(by, keys)), "n": len(g),
                    "slope_pp_per_h": 100 * b, "slope_lo_icb": 100 * (b - Z * se), "slope_hi_icb": 100 * (b + Z * se),
                    "slope_lo_origin": 100 * (b - Z * se_o), "slope_hi_origin": 100 * (b + Z * se_o),
                    "rel_slope_pp_per_h": 100 * br, "rel_slope_lo_icb": 100 * (br - Z * ser),
                    "rel_slope_hi_icb": 100 * (br + Z * ser)})
    return pd.DataFrame(out)


def verdict(pooled: pd.Series, slope: pd.Series) -> str:
    """Rule fixed before computing: drift if the exceedance slope on horizon is positive with
    its ICB-clustered 95% interval above zero; level bias if the pooled share's ICB-clustered
    interval excludes 0.5. Both can hold."""
    level = pooled["lo_icb"] > 0.5 or pooled["hi_icb"] < 0.5
    drift = slope["slope_lo_icb"] > 0
    falling = slope["slope_hi_icb"] < 0
    if drift and level:
        return "level bias and drift"
    if drift:
        return "drift"
    if level:
        return "level bias (falling with horizon)" if falling else "level bias"
    return "neither"


def build(supplied: tuple | None = None, drop_nonpositive: bool = False) -> tuple[pd.DataFrame, dict]:
    """``drop_nonpositive``: drop every forecast (for all four models, keeping one common row set)
    where any model's median is not positive, and count them; by default such a row raises."""
    meta: dict = {}
    rows = P.build(meta, supplied)["rows"]
    bad = rows["q50"] <= 0
    if bad.any():
        if not drop_nonpositive:
            raise RuntimeError("non-positive median: relative error undefined")
        drop = rows.loc[bad, P.KEYS].drop_duplicates()
        meta["nonpositive_median"] = {"forecasts_dropped": len(drop),
                                      "rows_by_model": rows.loc[bad, "model"].value_counts().to_dict(),
                                      "origins": sorted(drop["origin"].dt.strftime("%Y-%m").unique())}
        rows = rows.merge(drop.assign(_drop=True), on=P.KEYS, how="left")
        rows = rows[rows["_drop"].isna()].drop(columns="_drop").reset_index(drop=True)
    rows["above"] = (rows["bin"] >= 5).astype(float)
    rows["rel_err"] = (rows["y"] - rows["q50"]) / rows["q50"]
    rows["oyear"] = rows["origin"].dt.year
    return rows, meta


def run(supplied: tuple | None = None, drop_nonpositive: bool = False) -> dict:
    rows, meta = build(supplied, drop_nonpositive)
    # balanced sensitivity: origins contributing all six horizons in the window
    res = {}
    for win in ("outside", "all"):
        r = rows if win == "all" else rows[rows["window"] == "outside"]
        full = r.groupby(["model", "origin"])["horizon"].nunique()
        bal_orig = full[full == 6].reset_index()[["model", "origin"]]
        rb = r.merge(bal_orig, on=["model", "origin"])
        yrs = table(r, ["model", "oyear"])
        yrs["assessable"] = yrs["origins"] >= MIN_ORIGINS
        res[win] = {
            "pooled": table(r, ["model"]),
            "horizon": table(r, ["model", "horizon"]),
            "target": table(r, ["model", "target"]),
            "year": yrs,
            "m2f_h_t": table(r[r["model"] == "m2f_r4"], ["target", "horizon"]),
            "slopes": slopes(r, ["model"]),
            "slopes_target": slopes(r, ["model", "target"]),
            "horizon_balanced": table(rb, ["model", "horizon"]),
            "slopes_balanced": slopes(rb, ["model"]),
        }
    res["meta"] = meta
    res["rows"] = {"all": len(rows) // 4, "outside": int((rows["window"] == "outside").sum()) // 4}
    return res


def write(res: dict, sha: str, date: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for win in ("outside", "all"):
        for name, t in res[win].items():
            t.assign(window=win).to_csv(OUT / f"{name}_{win}.csv", index=False)
    lines = []
    for win in ("outside", "all"):
        pooled = res[win]["pooled"].set_index("model")
        sl = res[win]["slopes"].set_index("model")
        for m in P.MODELS:
            lines.append({"window": win, "model": m, "verdict": verdict(pooled.loc[m], sl.loc[m])})
        slt = res[win]["slopes_target"].set_index(["model", "target"])
        pt = res[win]["target"].set_index(["model", "target"])
        for m in P.MODELS:
            for t in TARGETS:
                lines.append({"window": win, "model": m, "target": t,
                              "verdict": verdict(pt.loc[(m, t)], slt.loc[(m, t)])})
    pd.DataFrame(lines).to_csv(OUT / "verdicts.csv", index=False)
    (OUT / "run.json").write_text(pd.Series({"sha": sha, "date": date, **res["rows"],
                                             "near_zero_outturns": res["meta"].get("near_zero_outturns"),
                                             "rows_common": res["meta"].get("rows_common")}).to_json(indent=1))


def main(argv=None) -> int:
    import subprocess
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                         check=False, cwd=PROJECT_ROOT).stdout.strip()
    res = run()
    write(res, sha, pd.Timestamp.now(tz="Europe/London").date().isoformat())
    pd.set_option("display.width", 220)
    for win in ("outside", "all"):
        print(f"\n===== {win} =====")
        for name in ("pooled", "slopes", "horizon", "target", "year", "slopes_target", "slopes_balanced"):
            t = res[win][name]
            print(f"--- {name}")
            print(t.round(4).to_string(index=False))
    print(pd.read_csv(OUT / "verdicts.csv").to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
