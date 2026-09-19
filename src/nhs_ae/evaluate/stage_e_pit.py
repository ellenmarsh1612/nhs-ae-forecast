"""PIT histograms at ICB level (work order of 2026-09-11; PIT histograms are registered in
prereg §6 and had not been reported).

Exploratory, DEV only, diagnostic: no model, prior or calibration is changed and nothing is
refitted. Four models are read from existing forecast files: raw ETS, M2f-r4, the ETS/M2f-r4
equal-weight quantile average (rebuilt deterministically with ``stage_e_ensemble.vincentise``),
and M1 v3 raw + pooled conformal at ICB level (Stage F's calibrated file, the version F2 used).

The nine registered quantile levels split the unit interval into 10 PIT bins whose expected
masses are the gaps between levels. Each outturn is assigned to the bin its forecast quantiles
bracket; an outturn exactly equal to one or more quantiles is placed by a seeded uniform draw
over the tied range of levels. Rows are the same for every model: scored rows (no token, so
embargoed targets are dropped and CONF origins raise), minus ICB-months that M2's frozen data
rule treats as missing (``m2._implausible_to_nan`` applied to the outturns), intersected across
the four models.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from scipy import stats

from nhs_ae.config import PROCESSED_DIR, PROJECT_ROOT
from nhs_ae.evaluate import stage_e_ensemble as E
from nhs_ae.evaluate.asof import TARGETS, load_truth, load_vintages
from nhs_ae.evaluate.harness import score_forecasts, truth_long
from nhs_ae.models.base import QUANTILES
from nhs_ae.models.m2 import _implausible_to_nan

log = logging.getLogger(__name__)

RESULTS = PROJECT_ROOT / "results" / "E-pit"
LEVELS = np.array(QUANTILES, dtype=float)
EXPECTED = np.diff(np.concatenate([[0.0], LEVELS, [1.0]]))          # 10 bin masses
MODELS = ("ets_raw", "m1_pooled", "m2f_r4", "ensemble")
LABELS = {"ets_raw": "raw ETS", "m1_pooled": "M1 v3 raw + pooled conformal",
          "m2f_r4": "M2f-r4", "ensemble": "ETS/M2f-r4 ensemble"}
KEYS = ["origin", "target", "series", "horizon", "period"]
SEED = 0


def load_m1_pooled() -> tuple[pd.DataFrame, dict]:
    path = PROCESSED_DIR / "stage_f" / "cal_m1_v3_raw_icb.parquet"
    fc = pd.read_parquet(path)
    fc = fc[fc["origin"].isin(E.ladder()) & ~fc["series"].isin(E.EXCLUDE)].copy()
    if set(fc["origin"].unique()) != set(E.ladder()) or (fc["origin"] >= pd.Timestamp("2024-01-01")).any():
        raise RuntimeError(f"{path.name}: unexpected origins")
    meta = {"name": "m1_pooled", "file": str(path.relative_to(PROCESSED_DIR.parent.parent)),
            "sha256": E.sha256(path), "model_column": ",".join(fc["model"].astype(str).unique()),
            "origins": fc["origin"].nunique(), "icbs": fc["series"].nunique()}
    fc["model"] = "m1_pooled"
    return fc, meta


def forecasts() -> tuple[dict[str, pd.DataFrame], list[dict], int]:
    ets, m_ets = E.load_icb("ets_raw")
    m2f, m_m2f = E.load_icb("m2f_r4")
    ens, excl = E.vincentise(ets, m2f, "icb")
    m1p, m_m1p = load_m1_pooled()
    return {"ets_raw": ets, "m1_pooled": m1p, "m2f_r4": m2f, "ensemble": ens}, [m_ets, m_m1p, m_m2f], len(excl)


def near_zero_rows(truth) -> pd.DataFrame:
    """(target, series, period) outturns that M2's frozen data rule would treat as missing."""
    rows = []
    for t in TARGETS:
        p = truth.panel(t, "icb")
        p = p[[c for c in p.columns if c not in E.EXCLUDE]]
        y = p.to_numpy(float).T                                          # series × months
        bad = np.isnan(_implausible_to_nan(y)) & ~np.isnan(y)
        s, m = np.nonzero(bad)
        rows.append(pd.DataFrame({"target": t, "series": p.columns[s], "period": p.index[m]}))
    return pd.concat(rows, ignore_index=True)


def pit_bin(q: np.ndarray, y: np.ndarray, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Bin index 0–9 for each row of quantiles ``q`` (rows × 9, sorted) and outturn ``y``; ties
    are placed by a uniform draw over the tied range of levels."""
    below = (q < y[:, None]).sum(axis=1)
    at_or_below = (q <= y[:, None]).sum(axis=1)
    tied = at_or_below > below
    out = below.copy()
    for i in np.flatnonzero(tied):
        lo, hi = LEVELS[below[i]], LEVELS[at_or_below[i] - 1]
        if hi > lo:                                         # several quantiles equal y
            u = rng.uniform(lo, hi)
            out[i] = int(np.searchsorted(LEVELS, u, side="right"))
        else:                                               # one quantile equals y: either side
            out[i] = below[i] + int(rng.integers(0, 2))
    return out, tied


def build(meta_out: dict, supplied: tuple | None = None) -> dict:
    """``supplied`` = (forecasts by model, input metadata, ETS exclusions) replaces the 35-origin
    ``forecasts()`` (the 69-origin M2f-r4 rescore passes its own); the method is unchanged."""
    vintages = load_vintages()
    t = load_truth(vintages)
    truth = truth_long(t, ("icb",), tuple(TARGETS))
    nz = near_zero_rows(t)
    fcs, metas, n_excl_ens = forecasts() if supplied is None else supplied
    scored = {}
    for name, fc in fcs.items():
        s, dropped = score_forecasts(fc.assign(model=name, level="icb")[E.COLS], truth)
        s = s.merge(nz.assign(near_zero=True), on=["target", "series", "period"], how="left")
        meta_out.setdefault("dropped", {})[name] = dropped
        meta_out.setdefault("near_zero_scored_rows", {})[name] = int(s["near_zero"].fillna(False).sum())
        scored[name] = s[~s["near_zero"].fillna(False).astype(bool)]
    common = set.intersection(*(set(map(tuple, s[KEYS].to_numpy())) for s in scored.values()))
    meta_out["rows_common"] = len(common)
    meta_out["rows_per_model_before_intersection"] = {k: len(v) for k, v in scored.items()}
    rng = np.random.default_rng(SEED)
    frames = []
    for name in MODELS:
        s = scored[name]
        s = s[[tuple(r) in common for r in s[KEYS].to_numpy()]].sort_values(KEYS).reset_index(drop=True)
        q = np.sort(s[[float(x) for x in QUANTILES]].to_numpy(float), axis=1)
        b, tied = pit_bin(q, s["y"].to_numpy(float), rng)
        frames.append(s[KEYS + ["y", "cov50", "cov90"]].assign(model=name, bin=b, tied=tied, q50=q[:, 4],
                                                              window=np.where(E.stage_d.assessable(s), "outside", "inside")))
    meta_out.update(inputs=metas, near_zero_outturns=len(nz), ets_excluded_from_average=n_excl_ens)
    return {"rows": pd.concat(frames, ignore_index=True)}


def summarise(rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    hist, st = [], []
    for name in MODELS:
        r = rows[rows["model"] == name]
        for win in ("outside", "all"):
            rw = r if win == "all" else r[r["window"] == "outside"]
            for h in [*range(1, 7), "pooled"]:
                g = rw if h == "pooled" else rw[rw["horizon"] == h]
                counts = np.bincount(g["bin"], minlength=10)
                n = int(counts.sum())
                share = counts / n
                for k in range(10):
                    hist.append({"model": name, "window": win, "horizon": h, "bin": k,
                                 "lo": float(np.concatenate([[0.0], LEVELS])[k]),
                                 "hi": float(np.concatenate([LEVELS, [1.0]])[k]),
                                 "count": int(counts[k]), "share": share[k], "expected": EXPECTED[k],
                                 "ratio": share[k] / EXPECTED[k]})
                chi = stats.chisquare(counts, EXPECTED * n)
                st.append({"model": name, "window": win, "horizon": h, "n": n,
                           "chi2": float(chi.statistic), "df": 9, "p_descriptive": float(chi.pvalue),
                           "cov50_bins": share[4:6].sum(), "cov90_bins": share[2:8].sum(),
                           "cov50_scored": float(g["cov50"].mean()), "cov90_scored": float(g["cov90"].mean()),
                           "below_median": share[:5].sum(), "central_2bins": share[4:6].sum(),
                           "lower_tail": share[:2].sum(), "upper_tail": share[8:].sum(),
                           "ties": int(g["tied"].sum())})
    return pd.DataFrame(hist), pd.DataFrame(st)


def shape(row: pd.Series) -> str:
    """One-line reading of a pooled histogram, by the work order's key (thresholds are stated in
    pit_findings.md; the numbers are always shown next to the words)."""
    parts = []
    if row["central_2bins"] > 0.55 and row["lower_tail"] + row["upper_tail"] < 0.10:
        parts.append("hump in the central bins: too wide in the middle")
    elif row["central_2bins"] < 0.45 and row["lower_tail"] + row["upper_tail"] > 0.10:
        parts.append("U-shape: too narrow overall")
    if not 0.45 <= row["below_median"] <= 0.55:
        parts.append("slope: outturns mostly " + ("below" if row["below_median"] > 0.55 else "above")
                     + " the median (" + ("over" if row["below_median"] > 0.55 else "under") + "-forecasting)")
    lo, hi = row["lower_tail"], row["upper_tail"]
    if max(lo, hi) > 0.10 and min(lo, hi) <= 0.05:
        parts.append(f"inflated {'lower' if lo > hi else 'upper'} tail: tail failures on that side")
    return "; ".join(parts) or "no marked departure by these thresholds"


def figures(hist: pd.DataFrame) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    edges = np.concatenate([[0.0], LEVELS, [1.0]])
    fig, axes = plt.subplots(2, 4, figsize=(11, 4.6), dpi=150, sharey=True)
    for i, win in enumerate(("outside", "all")):
        for j, name in enumerate(MODELS):
            ax = axes[i, j]
            g = hist[(hist["model"] == name) & (hist["window"] == win) & (hist["horizon"] == "pooled")]
            ax.bar(edges[:-1], g["ratio"], width=np.diff(edges), align="edge", color="#4a6fa5",
                   edgecolor="white", linewidth=0.6)
            ax.axhline(1.0, color="#888", lw=0.8, ls="--")
            ax.set_title(f"{LABELS[name]}\n{'outside COVID' if win == 'outside' else 'all months'}", fontsize=7)
            ax.set_xticks([0, 0.25, 0.5, 0.75, 1])
            ax.tick_params(labelsize=6)
            ax.spines[["top", "right"]].set_visible(False)
        axes[i, 0].set_ylabel("share / expected", fontsize=7)
    fig.suptitle("PIT, ICB level, 35 DEV ladder origins, h1–6 pooled (1 = calibrated; bar width = expected mass)",
                 fontsize=8)
    fig.tight_layout()
    fig.savefig(RESULTS / "fig_pit_pooled.png")
    plt.close(fig)
    fig, axes = plt.subplots(4, 6, figsize=(12, 7.2), dpi=150, sharey=True)
    for i, name in enumerate(MODELS):
        for h in range(1, 7):
            ax = axes[i, h - 1]
            g = hist[(hist["model"] == name) & (hist["window"] == "outside") & (hist["horizon"] == h)]
            ax.bar(edges[:-1], g["ratio"], width=np.diff(edges), align="edge", color="#4a6fa5",
                   edgecolor="white", linewidth=0.5)
            ax.axhline(1.0, color="#888", lw=0.8, ls="--")
            ax.set_xticks([0, 0.5, 1])
            ax.tick_params(labelsize=5.5)
            ax.spines[["top", "right"]].set_visible(False)
            if i == 0:
                ax.set_title(f"h{h}", fontsize=7)
        axes[i, 0].set_ylabel(LABELS[name], fontsize=6)
    fig.suptitle("PIT by horizon, ICB level, outside COVID (share / expected)", fontsize=8)
    fig.tight_layout()
    fig.savefig(RESULTS / "fig_pit_by_horizon.png")
    plt.close(fig)


def main(argv=None) -> int:
    import json
    import subprocess
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                         check=False, cwd=PROJECT_ROOT).stdout.strip()
    meta = {"date": pd.Timestamp.now(tz="Europe/London").date().isoformat(), "sha": sha}
    out = build(meta)
    hist, st = summarise(out["rows"])
    pooled = st[st["horizon"] == "pooled"].copy()
    pooled["shape"] = pooled.apply(shape, axis=1)
    RESULTS.mkdir(parents=True, exist_ok=True)
    hist.to_csv(RESULTS / "pit_histograms.csv", index=False)
    st.merge(pooled[["model", "window", "horizon", "shape"]], on=["model", "window", "horizon"], how="left").to_csv(
        RESULTS / "pit_stats.csv", index=False)
    figures(hist)
    (RESULTS / "pit_run.json").write_text(json.dumps(meta, indent=1, default=str))
    cols = ["model", "window", "n", "chi2", "p_descriptive", "cov50_bins", "cov90_bins", "cov50_scored",
            "cov90_scored", "below_median", "lower_tail", "upper_tail", "ties", "shape"]
    print(pooled[cols].to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    print(json.dumps({k: v for k, v in meta.items() if k != "inputs"}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
