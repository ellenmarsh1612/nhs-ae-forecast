"""Stage F: reconciliation (F1, H3) and built-in coherence against post-hoc (F2).

Design in the pre-registration amendments of 2026-09-11 (Stage F, F2, implementation
details). Hierarchy: providers with an ICB in the current mapping → 36 ICBs → 7 regions →
England, every aggregate the sum of its providers. Base models (ETS, STL+ARIMA, M1 raw) are
forecast at every level, calibrated at their own level with pooled conformal (Stage D), then
MinT-shrink reconciled quantile by quantile with an error covariance built only from
outturns published by the origin.
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from nhs_ae.calibrate import g1
from nhs_ae.calibrate.online import calibrate
from nhs_ae.config import PROCESSED_DIR, PROJECT_ROOT
from nhs_ae.evaluate import splits, stage_d, stage_e
from nhs_ae.evaluate.asof import TARGETS, VINTAGES_PATH, load_asof, load_truth, load_vintages
from nhs_ae.evaluate.harness import (
    BacktestConfig,
    forecast_origin,
    generate_forecasts,
    score_forecasts,
    truth_long,
)
from nhs_ae.evaluate.metrics import paired_bootstrap
from nhs_ae.evaluate.splits import split_origins
from nhs_ae.features.hierarchy import current_icb_map, current_region_map, icb_region_map
from nhs_ae.ingest.recover import month_range
from nhs_ae.models import MODELS
from nhs_ae.reconcile.mint import reconcile_quantiles, shrink_cov, summing_matrix

log = logging.getLogger(__name__)

WORK = PROCESSED_DIR / "stage_f"
RESULTS = PROJECT_ROOT / "results" / "F-reconciliation"
BASE_MODELS = ("b1", "b2", "m1_v3_raw")
LABELS = {"b1": "ETS", "b2": "STL+ARIMA", "m1_v3_raw": "M1"}
LEVELS = ("provider", "icb", "region", "england")
AGG_LEVELS = ("region", "england")
HISTORY = 36                      # resolved origins in the error-covariance window
DEFAULT_REL_VAR = 0.01            # relative error variance when a level has no history yet
EXCLUDE = ("UNMAPPED", "LEGACY")
COLS = ["origin", "mode", "model", "level", "target", "series", "horizon", "period",
        "quantile", "value", "scale"]
REUSE = {("b1", "provider"): stage_d.WORK / "forecasts_b1.parquet",
         ("m1_v3_raw", "provider"): stage_d.WORK / "forecasts_m1_v3_raw.parquet",
         ("b1", "icb"): stage_e.WORK / "comparator_b1.parquet",
         ("m1_v3_raw", "icb"): stage_e.WORK / "comparator_m1_v3_raw.parquet"}


def origins_all() -> list[date]:
    """Calibration burn-in plus DEV: the origins every base forecast is generated for."""
    return month_range(stage_d.BURN_IN_START, split_origins("dev")[-1])


def _path(kind: str, name: str, level: str, work=None):
    """Cache file; base forecasts always come from ``WORK``, the rest from ``work`` (default ``WORK``)."""
    return (WORK if kind == "base" or work is None else work) / f"{kind}_{name}_{level}.parquet"


def _check_work(work, failed) -> None:
    if failed is not None and (work is None or work == WORK):
        raise ValueError("guarded (G1) output needs its own work directory, not the Stage F cache")


def members(vintages: pd.DataFrame) -> pd.Series:
    """Bottom of the hierarchy: provider code -> ICB, for providers the current mapping places."""
    m = current_icb_map(vintages)
    return m[~m.isin(EXCLUDE)]


# ---- base forecasts ----------------------------------------------------------------------
@dataclass
class SummedView:
    """AsOfData stand-in whose region and England panels are sums of the mapped ICB panels
    (the Stage F hierarchy, not the data's own region labels), so the harness's
    ``forecast_origin`` fits them unchanged."""
    data: object
    regions: pd.Series

    @property
    def origin(self):
        return self.data.origin

    @property
    def mode(self):
        return self.data.mode

    def panel(self, target: str, level: str) -> pd.DataFrame:
        icb = self.data.panel(target, "icb")
        icb = icb[[c for c in icb.columns if c not in EXCLUDE]]
        if level == "region":
            return icb.T.groupby(self.regions.reindex(icb.columns).fillna("?")).sum(min_count=1).T
        if level == "england":
            return icb.sum(axis=1, min_count=1).rename("ENGLAND").to_frame()
        raise ValueError(f"SummedView has no {level!r} level")


_W: dict = {}


def _init(vpath, names):
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[var] = "1"
    v = load_vintages(vpath)
    _W.update(v=v, region_map=current_region_map(v), regions=icb_region_map(),
              models=[MODELS[n]() for n in names],
              cfg=BacktestConfig(origins=[], modes=("asof",), levels=AGG_LEVELS))


def _agg_task(origin):
    d = load_asof(origin, "asof", _W["v"], _W["region_map"])
    return forecast_origin(SummedView(d, _W["regions"]), _W["models"], _W["cfg"])


def generate(vintages: pd.DataFrame, jobs: int, origins: list[date] | None = None) -> None:
    """Every base forecast Stage F needs, cached under ``WORK``; Stage D/E runs are reused."""
    WORK.mkdir(parents=True, exist_ok=True)
    origins = origins_all() if origins is None else origins
    want = pd.to_datetime(pd.Index(origins))
    for (name, level), src in REUSE.items():
        path = _path("base", name, level)
        if path.exists():
            continue
        fc = pd.read_parquet(src)
        missing = want.difference(pd.Index(fc["origin"].unique()))
        if len(missing):
            raise RuntimeError(f"{src.name} lacks origins {list(missing[:3])}…")
        fc[fc["origin"].isin(want)].to_parquet(path, index=False)
    for level in ("icb", "provider"):
        path = _path("base", "b2", level)
        if not path.exists():
            cfg = BacktestConfig(origins=origins, modes=("asof",), levels=(level,))
            fc = generate_forecasts([MODELS["b2"]()], vintages, cfg, jobs=jobs, vintages_path=VINTAGES_PATH)
            fc.to_parquet(path, index=False)
    if not all(_path("base", n, lv).exists() for n in BASE_MODELS for lv in AGG_LEVELS):
        with ProcessPoolExecutor(max_workers=jobs, initializer=_init,
                                 initargs=(VINTAGES_PATH, BASE_MODELS)) as pool:
            fc = pd.concat(list(pool.map(_agg_task, origins)), ignore_index=True)
        key = {MODELS[n]().name: n for n in BASE_MODELS}
        for (model, level), g in fc.groupby(["model", "level"]):
            g.to_parquet(_path("base", key[model], level), index=False)


# ---- calibration at each level -----------------------------------------------------------
def first_release_level(level: str) -> pd.DataFrame:
    """First-published outturns at ``level``; an aggregate resolves when its last ICB does."""
    if level == "provider":
        return pd.read_parquet(stage_d.WORK / "first_release.parquet")
    fr = pd.read_parquet(stage_e.WORK / "first_release_icb.parquet")
    fr = fr[~fr["series"].isin(EXCLUDE)]
    if level == "icb":
        return fr
    key = fr["series"].map(icb_region_map()).fillna("?") if level == "region" else "ENGLAND"
    g = fr.assign(series=key).groupby(["target", "series", "period"])
    return g.agg(y_first=("y_first", "sum"), resolved=("resolved", "max")).reset_index()


def calibrated(name: str, level: str, vintages: pd.DataFrame, work=None,
               failed: pd.DataFrame | None = None) -> pd.DataFrame:
    """Pooled conformal at ``level``, pooled over that level's hierarchy members only.
    ``failed`` (``calibrate.g1.failed_forecasts`` rows at this level) applies guard G1."""
    _check_work(work, failed)
    path = _path("cal", name, level, work)
    if path.exists():
        return pd.read_parquet(path)
    fc = pd.read_parquet(_path("base", name, level))
    fc = (fc[fc["series"].isin(members(vintages).index)] if level == "provider"
          else fc[~fc["series"].isin(EXCLUDE)])
    cal = calibrate(fc, first_release_level(level), methods=("pooled",), failed=failed)
    path.parent.mkdir(parents=True, exist_ok=True)
    cal.to_parquet(path, index=False)
    return cal


# ---- MinT over the hierarchy -------------------------------------------------------------
def _median_errors(cal: pd.DataFrame, fr: pd.DataFrame, level: str, guard=None,
                   unseal_token: str | None = None) -> pd.DataFrame:
    """``guard`` (callable or None) sees the merged medians and first releases before any error
    is computed (the Stage H runner's sealed-period check). Before either, the merged rows'
    origins and periods pass ``splits.assert_not_sealed`` with ``unseal_token`` (P11)."""
    med = cal[cal["quantile"] == 0.5][["origin", "target", "series", "horizon", "period", "value"]]
    e = med.merge(fr[["target", "series", "period", "y_first", "resolved"]],
                  on=["target", "series", "period"])
    splits.assert_not_sealed(e[["origin", "period"]], unseal_token)
    if guard is not None:
        guard(e)
    e["err"] = e["y_first"] - e["value"]
    e["rel"] = e["err"] / e["value"].clip(lower=1.0)
    e["level"] = level
    return e[["origin", "target", "series", "horizon", "resolved", "err", "rel", "level"]]


def error_cov(hist: pd.DataFrame, names: list[str], level_of: dict, med: np.ndarray) -> np.ndarray:
    """W for one (target, horizon, origin): Schäfer–Strimmer over the ``HISTORY`` most recent
    resolved origins; a series with fewer than three errors gets its level's median relative
    error variance times its median forecast squared."""
    if hist.empty:
        return np.diag(DEFAULT_REL_VAR * np.clip(med, 1.0, None) ** 2)
    recent = np.sort(hist["origin"].unique())[-HISTORY:]
    hist = hist[hist["origin"].isin(recent)]
    E = hist.pivot(index="origin", columns="series", values="err").reindex(columns=names)
    g = hist.groupby("series")["rel"]
    rel_var = g.var()[g.count() >= 3]
    lvl_rel = rel_var.groupby(rel_var.index.map(level_of)).median()
    fallback_rel = np.array([lvl_rel.get(level_of[n], rel_var.median() if len(rel_var) else DEFAULT_REL_VAR)
                             for n in names])
    return shrink_cov(E.to_numpy(float), fallback_rel * np.clip(med, 1.0, None) ** 2)


def reconcile_model(name: str, vintages: pd.DataFrame, origins=None, work=None,
                    failed: dict[str, pd.DataFrame] | None = None) -> pd.DataFrame:
    """MinT-shrink reconciliation of one base model's calibrated forecasts at every DEV origin.

    ``failed`` ({level: failed forecasts}; guard G1): those forecasts are calibrated under G1,
    kept out of the error covariance and the reconciliation inputs (a failed provider joins its
    ICB's rest node, a failed aggregate drops out of S) and returned as issued."""
    _check_work(work, failed)
    path = _path("mint", name, "all", work)
    if path.exists() and origins is None:
        return pd.read_parquet(path)
    icb_of = members(vintages).to_dict()
    region_of = icb_region_map().to_dict()
    cal = {lv: calibrated(name, lv, vintages, work, None if failed is None else failed[lv]) for lv in LEVELS}
    fr = {lv: first_release_level(lv) for lv in LEVELS}
    rec = reconcile_frames(cal, fr, failed, split_origins("dev") if origins is None else origins,
                           icb_of, region_of)
    if origins is None:
        path.parent.mkdir(parents=True, exist_ok=True)
        rec.to_parquet(path, index=False)
    return rec


def reconcile_frames(cal: dict[str, pd.DataFrame], fr: dict[str, pd.DataFrame],
                     failed: dict[str, pd.DataFrame] | None, origins, icb_of: dict, region_of: dict,
                     errs_guard=None, unseal_token: str | None = None) -> pd.DataFrame:
    """The body of ``reconcile_model`` on injected frames: ``cal`` (calibrated forecasts of one
    base model), ``fr`` (first releases) and ``failed`` (G1, or None), each {level: frame},
    reconciled at ``origins``. Returns the reconciled rows plus the G1 as-issued rows, checked
    against the base row counts. ``errs_guard`` and ``unseal_token`` are passed to
    ``_median_errors``."""
    fail = {lv: g1.mask(cal[lv], None if failed is None else failed[lv], g1.KEY) for lv in LEVELS}
    errs = pd.concat([_median_errors(cal[lv][~fail[lv]], fr[lv], lv, errs_guard, unseal_token)
                      for lv in LEVELS])
    inputs = {lv: cal[lv].assign(value=cal[lv]["value"].mask(fail[lv])) for lv in LEVELS}
    level_of = {s: lv for lv in LEVELS for s in cal[lv]["series"].unique()}
    if len(level_of) != sum(cal[lv]["series"].nunique() for lv in LEVELS):
        raise RuntimeError("a series code appears at two levels")
    qs = sorted(cal["provider"]["quantile"].unique())
    dev = pd.to_datetime(pd.Index(origins))
    out = []
    for target in TARGETS:
        wide = {lv: inputs[lv][(inputs[lv]["target"] == target) & inputs[lv]["origin"].isin(dev)]
                .pivot_table(index=["origin", "horizon", "series"], columns="quantile", values="value")
                for lv in LEVELS}
        cp = cal["provider"]
        present = (cp[(cp["target"] == target) & (cp["quantile"] == 0.5)]
                   .groupby(["origin", "horizon"])["series"].agg(set))
        for h in sorted(cal["provider"]["horizon"].unique()):
            eh = errs[(errs["target"] == target) & (errs["horizon"] == h)]
            for t in dev:
                if (t, h) not in wide["provider"].index:
                    continue
                # an aggregate with no base forecast here (M1 at England level before it has
                # enough training rows) simply drops out of S
                q = {lv: (wide[lv].loc[(t, h)].dropna() if (t, h) in wide[lv].index
                          else wide[lv].iloc[:0].droplevel([0, 1])) for lv in LEVELS}
                forecast = [p for p in q["provider"].index if p in icb_of]
                # a provider with no base forecast (young code, late submission) is still in
                # its ICB's history: one unobserved "rest" node per ICB carries it
                rest = sorted({icb_of[p] for p in present.get((t, h), set()) - set(forecast)
                               if p in icb_of and icb_of[p] in q["icb"].index})
                node_icb = {**{p: icb_of[p] for p in forecast}, **{f"{i}~rest": i for i in rest}}
                bottom = list(node_icb)
                parents = {s: bottom for s in q["england"].index}
                parents.update({r: [b for b in bottom if region_of.get(node_icb[b]) == r] for r in q["region"].index})
                parents.update({i: [b for b in bottom if node_icb[b] == i] for i in q["icb"].index})
                S, names = summing_matrix(bottom, parents)
                base = pd.concat([q[lv] for lv in ("england", "region", "icb", "provider")]).reindex(names)
                obs = base[0.5].notna().to_numpy()
                seen = [n for n, o in zip(names, obs) if o]
                W = error_cov(eh[eh["resolved"] <= t], seen, level_of, base.loc[seen, 0.5].to_numpy())
                rec = reconcile_quantiles(base[qs], S, names, W, obs).loc[seen]
                long = rec.stack().rename("value").reset_index()
                long.columns = ["series", "quantile", "value"]
                long["origin"], long["horizon"], long["target"] = t, h, target
                out.append(long)
        log.info("reconciled %s %s", ", ".join(map(str, cal["provider"]["model"].unique())), target)
    rec = pd.concat(out, ignore_index=True)
    base_rows = pd.concat([c[c["quantile"] == 0.5] for c in cal.values()])
    rec = rec.merge(base_rows[["origin", "target", "series", "horizon", "period", "level", "mode", "scale"]],
                    on=["origin", "target", "series", "horizon"], how="left", validate="many_to_one")
    rec["model"] = f"{cal['provider']['model'].iloc[0]}+mint"
    rec = rec[COLS]
    issued = [cal[lv][fail[lv] & cal[lv]["origin"].isin(dev).to_numpy()] for lv in LEVELS]
    if sum(map(len, issued)):                   # G1: failed forecasts go out as produced
        rec = pd.concat([rec, pd.concat(issued).assign(model=rec["model"].iloc[0])[COLS]], ignore_index=True)
    # every base forecast of a hierarchy member must come back reconciled, and nothing else
    expect = {lv: int((c["origin"].isin(dev) & c["value"].notna() & c["series"].isin(level_of)).sum())
              for lv, c in cal.items()}
    got = rec.groupby("level").size().to_dict()
    if got != expect:
        raise RuntimeError(f"reconciled rows {got} != base rows {expect}")
    return rec


# ---- scoring -----------------------------------------------------------------------------
def truth_all(vintages: pd.DataFrame) -> pd.DataFrame:
    """Latest revised outturns at every level; region and England are sums of the mapped ICBs,
    scored only in months with every ICB present (as for the M2 aggregates in Stage E)."""
    t = truth_long(load_truth(vintages), ("provider", "icb"), tuple(TARGETS))
    return pd.concat([t, stage_e.agg_truth(vintages)], ignore_index=True)


def score(fc: pd.DataFrame, truth: pd.DataFrame, label: str) -> pd.DataFrame:
    dev = pd.to_datetime(pd.Index(split_origins("dev")))
    s, dropped = score_forecasts(fc.loc[fc["origin"].isin(dev), COLS], truth)
    log.info("scored %s: %d rows, dropped %s", label, len(s), dropped)
    return s.assign(model=label)


def coherence_gaps(fc: pd.DataFrame, icb_of: dict, region_of: dict) -> pd.DataFrame:
    """|aggregate median − Σ children's medians| / aggregate median, per aggregate forecast."""
    med = fc[fc["quantile"] == 0.5]
    rows = []
    for level, child, parent_of in (("icb", "provider", icb_of), ("region", "icb", region_of),
                                    ("england", "region", None)):
        ch = med[med["level"] == child]
        par = med[med["level"] == level]
        if ch.empty or par.empty:
            continue
        ch = ch.assign(parent=ch["series"].map(parent_of) if parent_of else "ENGLAND")
        sums = ch.groupby(["origin", "target", "horizon", "parent"])["value"].sum().rename("children")
        agg = par.set_index(["origin", "target", "horizon", "series"])["value"].rename("agg")
        agg.index = agg.index.set_names("parent", level="series")
        j = pd.concat([agg, sums], axis=1, join="inner")
        rows.append(pd.DataFrame({"level": level, "gap": (j["agg"] - j["children"]).abs() / j["agg"]},
                                 index=j.index).reset_index())
    return pd.concat(rows, ignore_index=True)


# ---- F1: H3 ------------------------------------------------------------------------------
def winter_h3(s: pd.DataFrame) -> pd.DataFrame:
    return s[s["winter"] & (s["horizon"] == 3)]


def h3_table(scored: dict[tuple[str, str], pd.DataFrame]) -> pd.DataFrame:
    """Reconciled against base, winter h=3 WIS, bootstrap over series (targets pooled within a
    series); per target as description."""
    keys = ("series", "target", "origin", "horizon", "period")
    rows = []
    for name in BASE_MODELS:
        b, r = winter_h3(scored[(name, "base")]), winter_h3(scored[(name, "mint")])
        for level in LEVELS:
            bl, rl = b[b["level"] == level], r[r["level"] == level]
            res = paired_bootstrap(bl, rl, unit="series", keys=keys)
            row = {"base": LABELS[name], "level": level, "n_series": res.get("n_units", 0),
                   "rel": res.get("rel"), "rel_lo": res.get("rel_lo"), "rel_hi": res.get("rel_hi")}
            for t in TARGETS:
                rt = paired_bootstrap(bl[bl["target"] == t], rl[rl["target"] == t], unit="series", keys=keys)
                row[f"rel_{t}"] = rt.get("rel")
            out = stage_d.assessable(bl)
            ro = paired_bootstrap(bl[out], rl[stage_d.assessable(rl)], unit="series", keys=keys)
            row["rel_outside_covid"] = ro.get("rel")
            rows.append(row)
    t = pd.DataFrame(rows)
    verdict = []
    for name in BASE_MODELS:
        g = t[t["base"] == LABELS[name]].set_index("level")
        icb_ok = bool(g.loc["icb", "rel_hi"] < 0)
        prov_ok = bool(g.loc["provider", "rel"] <= 0.02)
        verdict.append({"base": LABELS[name], "icb_improves": icb_ok, "provider_within_2pct": prov_ok,
                        "H3": "holds" if icb_ok and prov_ok else "fails"})
    return t.merge(pd.DataFrame(verdict), on="base")


# ---- F2: coherence against calibration ---------------------------------------------------
F2_REFERENCE = "M1 + pooled"   # the operational model; ETS + pooled aggregates blow up in 2020–21


def calibration_blowups(dev: pd.DatetimeIndex, work=None) -> pd.DataFrame:
    """Calibrated forecasts whose 97.5% quantile exceeds ten times the median, per model and
    level, with the zero-forecast base rows that seed them."""
    rows = []
    for n in BASE_MODELS:
        for lv in LEVELS:
            b = pd.read_parquet(_path("base", n, lv))
            wb = b.pivot_table(index=["origin", "target", "series", "horizon"], columns="quantile", values="value")
            zero = wb[wb.max(axis=1) == 0].reset_index()["origin"]
            c = pd.read_parquet(_path("cal", n, lv, work))
            wc = c[c["origin"].isin(dev)].pivot_table(index=["origin", "target", "series", "horizon"],
                                                      columns="quantile", values="value")
            bad = wc[wc[0.975] > 10 * wc[0.5].clip(lower=1)].reset_index()["origin"]
            rows.append({"base": LABELS[n], "level": lv, "all_zero_base_rows": len(zero),
                         "all_zero_origins": ", ".join(sorted(zero.dt.strftime("%Y-%m").unique())[:4]),
                         "cal_q975_over_10x_median": len(bad), "share": len(bad) / max(len(wc), 1),
                         "first": bad.min(), "last": bad.max()})
    return pd.DataFrame(rows)


def f2_table(contenders: dict[str, pd.DataFrame], scored: dict[str, pd.DataFrame],
             icb_of: dict, region_of: dict, origins=None) -> pd.DataFrame:
    """F2 at the ``origins`` given (default: the DEV ladder origins)."""
    ladder = pd.to_datetime(pd.Index(stage_e.ladder_origins() if origins is None else origins))
    ref = scored[F2_REFERENCE]
    ref = ref[ref["origin"].isin(ladder)]
    rows = []
    for label, fc in contenders.items():
        fc = fc[fc["origin"].isin(ladder)]
        gaps = coherence_gaps(fc, icb_of, region_of)
        s = scored[label]
        s = s[s["origin"].isin(ladder)]
        for level in ("icb", "region", "england"):
            sl, rl = s[s["level"] == level], ref[ref["level"] == level]
            if sl.empty:
                continue
            gl = gaps[gaps["level"] == level]["gap"]
            inside = ~stage_d.assessable(sl)
            rel = []
            for t in TARGETS:
                r = paired_bootstrap(winter_h3(rl[rl["target"] == t]), winter_h3(sl[sl["target"] == t]),
                                     unit="series")
                rel.append(r.get("rel", np.nan))
            rows.append({
                "model": label, "level": level,
                "coh_gap_mean": gl.mean() if len(gl) else np.nan,
                "coh_gap_max": gl.max() if len(gl) else np.nan,
                "wis_rel_m1": float(np.exp(np.mean(np.log1p(rel))) - 1),
                **{f"wis_{t}": winter_h3(sl[sl["target"] == t])["wis"].mean() for t in TARGETS},
                "cov90": sl["cov90"].mean(), "cov50": sl["cov50"].mean(),
                **{f"cov90_h{h}": sl.loc[sl["horizon"] == h, "cov90"].mean() for h in range(1, 7)},
                "cov90_out": sl.loc[~inside, "cov90"].mean(), "cov50_out": sl.loc[~inside, "cov50"].mean(),
                "cov90_in": sl.loc[inside, "cov90"].mean(), "cov50_in": sl.loc[inside, "cov50"].mean(),
                "n": len(sl)})
    return pd.DataFrame(rows)


def _fig_f2(table: pd.DataFrame, path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    levels = ("icb", "region", "england")
    fig, axes = plt.subplots(1, 3, figsize=(9, 3.0), dpi=150, sharey=True)
    for ax, level in zip(axes, levels):
        g = table[table["level"] == level]
        for _, r in g.iterrows():
            ax.plot(range(1, 7), [r[f"cov90_h{h}"] for h in range(1, 7)], marker="o", ms=3, lw=1.1,
                    label=r["model"], ls="--" if "MinT" in r["model"] else "-")
        ax.axhspan(0.87, 0.93, color="#ddd", zorder=0)
        ax.set_title(level, fontsize=8)
        ax.set_xlabel("horizon (months)", fontsize=7)
        ax.tick_params(labelsize=6)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("90% interval coverage", fontsize=7)
    axes[-1].legend(frameon=False, fontsize=5.5)
    fig.suptitle("F2: 90% coverage by horizon, DEV ladder origins (band 0.87–0.93)", fontsize=8)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _pct(x) -> str:
    return "" if x is None or pd.isna(x) else f"{100 * x:+.1f}%"


def report(h3: pd.DataFrame, f2: pd.DataFrame, blowups: pd.DataFrame, meta: dict) -> str:
    from nhs_ae.evaluate.stage_g import md_table
    RESULTS.mkdir(parents=True, exist_ok=True)
    h3.to_csv(RESULTS / "h3_results.csv", index=False)
    f2.to_csv(RESULTS / "coherence_vs_calibration.csv", index=False)
    blowups.to_csv(RESULTS / "calibration_blowups.csv", index=False)
    _fig_f2(f2, RESULTS / "fig_f2_coverage.png")
    h = h3.assign(ci=[f"[{_pct(lo)}, {_pct(hi)}]" for lo, hi in zip(h3["rel_lo"], h3["rel_hi"])])
    show = h[["base", "level", "n_series", "rel", "ci", *[f"rel_{t}" for t in TARGETS], "rel_outside_covid", "H3"]]
    show = show.assign(**{c: show[c].map(_pct) for c in ["rel", *[f"rel_{t}" for t in TARGETS], "rel_outside_covid"]})
    bl = blowups.assign(share=blowups["share"].map(lambda x: f"{x:.1%}"),
                        window=[f"{a:%Y-%m}..{b:%Y-%m}" if pd.notna(a) else ""
                                for a, b in zip(blowups["first"], blowups["last"])])
    (RESULTS / "h3_results.md").write_text(
        f"# H3 on DEV (exploratory), run {meta.get('date', '?')} at `{meta.get('sha', '?')}`\n\n"
        "Winter h=3 WIS of MinT-shrink reconciled forecasts relative to the calibrated base "
        "(negative = reconciliation helps); 95% bootstrap interval over series (1,000 resamples, "
        "targets pooled within a series). DEV origins 2018-04 to 2023-12, as-of, all months "
        "including COVID; the outside-COVID column is exploratory. H3 holds for a base if the ICB "
        "interval is entirely below zero and the provider point estimate is at most +2%. The "
        "confirmatory test is Stage H on CONF.\n\n" + md_table(show, index=False) + "\n\n"
        "## The ETS rows are an artefact\n\n"
        "At origin 2020-05 ETS forecasts exactly zero (every quantile) for many series at every "
        "level, after the April 2020 collapse. Those forecasts enter the pooled conformal sets. "
        "At aggregate levels the pools are tiny (England: at most 12 scores per horizon, so the "
        "95% and 97.5% adjustments are the largest score), and one log-scale score of about 14 "
        "(with a zero forecast, the log of the outturn itself) inflates upper quantiles by a "
        "factor of up to about e^14, roughly 10^6, until it leaves the 12-origin window. MinT then "
        "projects the inflated aggregate quantiles onto the providers. The other bases have no "
        "such rows at aggregate level. Calibrated forecasts with a 97.5% quantile above ten times "
        "the median:\n\n" + md_table(bl[["base", "level", "all_zero_base_rows", "all_zero_origins",
                                             "cal_q975_over_10x_median", "share", "window"]], index=False) + "\n")
    f = f2.copy()
    for c in ("coh_gap_mean", "coh_gap_max"):
        f[c] = f[c].map(lambda x: "" if pd.isna(x) else f"{100 * x:.2f}%")
    f["wis_rel_m1"] = f["wis_rel_m1"].map(_pct)
    for c in [c for c in f.columns if c.startswith("cov")]:
        f[c] = f[c].map(lambda x: f"{x:.2f}")
    for t in TARGETS:
        f[f"wis_{t}"] = f[f"wis_{t}"].map(lambda x: f"{x:,.0f}")
    cols = ["model", "level", "coh_gap_mean", "coh_gap_max", "wis_rel_m1", *[f"wis_{t}" for t in TARGETS],
            "cov90", "cov50", *[f"cov90_h{h}" for h in range(1, 7)], "cov90_out", "cov50_out", "cov90_in", "cov50_in"]
    (RESULTS / "coherence_vs_calibration.md").write_text(
        f"# F2: built-in coherence against post-hoc reconciliation, run {meta.get('date', '?')} at "
        f"`{meta.get('sha', '?')}`\n\n35 DEV ladder origins, as-of. *Coherence gap:* |aggregate "
        "median − sum of its children's medians| / aggregate median (ICB: children are providers; "
        "region: ICBs; England: regions). For reconciled forecasts the ICB gap is the rest node "
        "(providers the base model cannot forecast, which stay in the hierarchy but are not "
        "reported); the region and England gaps come from re-sorting crossed quantiles after "
        "projection. M2's aggregates are sums of joint draws, so they are coherent as "
        "distributions; their medians are not additive, and the gap shown for M2 measures that. "
        f"*WIS:* winter h=3 mean WIS per target, and the geometric mean over targets of the WIS "
        f"ratio to {F2_REFERENCE} at the same level (ETS + pooled is not used as the reference: "
        "its aggregates blow up in 2020–21, see `h3_results.md`). `_out`/`_in`: outside/inside the "
        "COVID window (exploratory). M2f-r4 is the phase-1b model from branch `m2f-redesign` "
        "(commit b77430e); `m2d_corr` is the frozen M2.\n\n" + md_table(f[cols], index=False) + "\n")
    lines = ["STOP 7 — Stage F", "", "F1 / H3 on DEV (winter h=3 WIS, reconciled vs calibrated base):"]
    for _, r in h3.iterrows():
        lines.append(f"  {r['base']:10s} {r['level']:8s} {_pct(r['rel']):>8s} "
                     f"[{_pct(r['rel_lo'])}, {_pct(r['rel_hi'])}]  outside COVID {_pct(r['rel_outside_covid'])}")
    for base, g in h3.groupby("base", sort=False):
        lines.append(f"  H3 {base}: {g['H3'].iloc[0]} (ICB improves: {g['icb_improves'].iloc[0]}, "
                     f"provider within +2%: {g['provider_within_2pct'].iloc[0]})")
    lines += ["", (f"F2 (35 ladder origins): coherence gap mean | WIS vs {F2_REFERENCE} | cov90 cov50 | "
                   "outside COVID 90/50:")]
    for _, r in f2.iterrows():
        gap = "   n/a" if pd.isna(r["coh_gap_mean"]) else f"{100 * r['coh_gap_mean']:5.2f}%"
        lines.append(f"  {r['model']:26s} {r['level']:8s} {gap} | {_pct(r['wis_rel_m1']):>8s} | "
                     f"{r['cov90']:.2f} {r['cov50']:.2f} | {r['cov90_out']:.2f} {r['cov50_out']:.2f}")
    text = "\n".join(lines)
    (RESULTS / "stop7.txt").write_text(text + "\n")
    (RESULTS / "README.md").write_text(
        f"# results/F-reconciliation\n\nStage F, run {meta.get('date', '?')} at commit `{meta.get('sha', '?')}`.\n\n"
        "- `h3_results.md` / `.csv`: F1, H3 on DEV per base model and level, and the ETS artefact\n"
        "- `calibration_blowups.csv`: calibrated forecasts with a 97.5% quantile above ten times the median\n"
        "- `coherence_vs_calibration.md` / `.csv`: F2, coherence gap against calibration at ICB, "
        "region and England level\n- `fig_f2_coverage.png`: 90% coverage by horizon per contender and level\n"
        "- `stop7.txt`: the STOP 7 summary\n")
    return text


def run(jobs: int, meta: dict) -> str:
    vintages = load_vintages()
    generate(vintages, jobs)
    icb_of = members(vintages).to_dict()
    region_of = icb_region_map().to_dict()
    truth = truth_all(vintages)
    fcs, scored = {}, {}
    for name in BASE_MODELS:
        fcs[(name, "base")] = pd.concat([calibrated(name, lv, vintages) for lv in LEVELS], ignore_index=True)
        fcs[(name, "mint")] = reconcile_model(name, vintages)
        for kind in ("base", "mint"):
            scored[(name, kind)] = score(fcs[(name, kind)], truth, f"{name}/{kind}")
    h3 = h3_table(scored)
    post_hoc = {"ETS + pooled": ("b1", "base"), "ETS + pooled + MinT": ("b1", "mint"),
                "M1 + pooled": ("m1_v3_raw", "base"), "M1 + pooled + MinT": ("m1_v3_raw", "mint")}
    contenders = {label: fcs[k] for label, k in post_hoc.items()}
    f2_scored = {label: scored[k] for label, k in post_hoc.items()}
    for label, rung in (("M2f-r4 (phase 1b)", "m2f_r4"), ("M2 frozen (m2d_corr)", "m2d_corr")):
        contenders[label] = pd.read_parquet(stage_e.WORK / f"forecasts_{rung}.parquet")
        f2_scored[label] = score(contenders[label], truth, label)
    f2 = f2_table(contenders, f2_scored, icb_of, region_of)
    blowups = calibration_blowups(pd.to_datetime(pd.Index(split_origins("dev"))))
    return report(h3, f2, blowups, meta)


def main(argv=None) -> int:
    import argparse
    import subprocess
    p = argparse.ArgumentParser(prog="python -m nhs_ae.evaluate.stage_f")
    p.add_argument("--jobs", type=int, default=8)
    p.add_argument("--generate-only", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.generate_only:
        generate(load_vintages(), args.jobs)
        return 0
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                         check=False).stdout.strip()
    print(run(args.jobs, {"date": pd.Timestamp.now(tz="Europe/London").date().isoformat(), "sha": sha}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
