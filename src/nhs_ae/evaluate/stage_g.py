"""Stage G: occupancy validation, decision loss for Stage D, breach probabilities.

Design in the pre-registration amendment of 2026-09-10 (Stage G). Inputs: the KH03 and
discharge-delay tables built by ``nhs_ae.ingest.kh03`` / ``nhs_ae.ingest.discharge``,
the admissions series, and Stage D's scored candidates.

Admissions used to *fit* the bed-days ratio are the latest published values; the revision
audit puts the difference from the as-of values at 0.06–0.15% of national totals, far
below anything that could move an occupancy ratio. Everything that is a forecast uses
as-of data only.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from nhs_ae.config import PROCESSED_DIR, PROJECT_ROOT
from nhs_ae.decide.occupancy import (
    COST_LOSS,
    COVID,
    THRESHOLD,
    _usable,
    breach_table,
    cost_loss_expense,
    fit_coefficients,
    occupancy_draws,
    sample_quantiles,
)
from nhs_ae.evaluate.asof import as_of_date, load_truth
from nhs_ae.models.base import QUANTILES

log = logging.getLogger(__name__)

RESULTS = PROJECT_ROOT / "results" / "G-decision"
VALIDATION_QUARTERS = pd.date_range("2018-04-01", "2023-10-01", freq="QS")
TOLERANCE = {"median_abs_pp": 5.0, "share_within_10pp": 0.80}
N_DRAWS = 4000


def load_kh03(path=PROCESSED_DIR / "kh03.parquet") -> pd.DataFrame:
    """Every published version; ``fit_coefficients`` picks what was out at each date."""
    k = pd.read_parquet(path)
    for c in ("quarter_start", "published"):
        k[c] = pd.to_datetime(k[c]).astype("datetime64[ns]")
    return k[~k["is_total"]]


def latest(kh03: pd.DataFrame) -> pd.DataFrame:
    return kh03[kh03["is_latest"]]


def monthly_admissions(vintages: pd.DataFrame) -> pd.DataFrame:
    p = load_truth(vintages).panel("adm_via_ae", "provider")
    m = p.stack(future_stack=True).dropna().rename("adm").reset_index()
    m.columns = ["period", "org_code", "adm"]
    return m


def _in_covid(q: pd.Series) -> pd.Series:
    return (q <= COVID[1]) & (q + pd.offsets.QuarterEnd(0) >= COVID[0])


def validate(kh03: pd.DataFrame, adm_q: pd.DataFrame, discharge_q: pd.DataFrame | None = None,
             quarters=VALIDATION_QUARTERS) -> pd.DataFrame:
    """Out-of-sample reconstruction error per trust-quarter and variant (pp)."""
    rows = []
    actual = latest(kh03).merge(adm_q, on=["org_code", "quarter_start"])
    actual = actual[actual["ga_available"].gt(0) & actual["ga_occupied"].gt(0)]
    for q in quarters:
        as_of = pd.Timestamp(q)
        truth = actual[actual["quarter_start"] == q]
        if truth.empty:
            continue
        for variant, pooled in (("trust", False), ("national", True)):
            c = fit_coefficients(kh03, adm_q, as_of, pooled_only=pooled)
            if c.empty:
                continue
            t = truth.merge(c[["org_code", "log_c"]], on="org_code")
            pred = np.exp(t["log_c"]) * t["adm"] / t["days"] / t["ga_available"]
            rows.append(pd.DataFrame({
                "quarter_start": q, "org_code": t["org_code"], "variant": variant,
                "occ_actual": t["ga_occupied"] / t["ga_available"], "occ_pred": pred}))
    v = pd.concat(rows, ignore_index=True)
    v["err_pp"] = 100 * (v["occ_pred"] - v["occ_actual"])
    v["covid_window"] = _in_covid(v["quarter_start"])
    return v


def validation_summary(v: pd.DataFrame) -> pd.DataFrame:
    g = v.groupby(["variant", "covid_window"])
    s = g.agg(trust_quarters=("err_pp", "size"),
              median_abs_pp=("err_pp", lambda x: float(x.abs().median())),
              share_within_10pp=("err_pp", lambda x: float((x.abs() <= 10).mean())),
              mean_err_pp=("err_pp", "mean")).reset_index()
    s["passes"] = ((s["median_abs_pp"] <= TOLERANCE["median_abs_pp"])
                   & (s["share_within_10pp"] >= TOLERANCE["share_within_10pp"]))
    return s


def winter_quarter_origins(start="2018-10-01", end="2023-10-01") -> list[pd.Timestamp]:
    """First months of the winter quarters (Oct–Dec, Jan–Mar) in DEV, outside COVID."""
    qs = [q for q in pd.date_range(start, end, freq="QS") if q.month in (1, 10)]
    return [q for q in qs if not _in_covid(pd.Series([q])).iloc[0]]


def decision_loss(scores: pd.DataFrame, kh03: pd.DataFrame, adm_q: pd.DataFrame,
                  seed: int = 0) -> pd.DataFrame:
    """Per candidate: mean cost-loss expense over the grid, Brier score, trust-quarters."""
    rng = np.random.default_rng(seed)
    s = scores[(scores["target"] == "adm_via_ae") & (scores["level"] == "provider")]
    qcols = list(QUANTILES)
    rows = []
    for q0 in winter_quarter_origins():
        origin = q0 - pd.DateOffset(months=2)
        months = pd.date_range(q0, periods=3, freq="MS")
        coefs = fit_coefficients(kh03, adm_q, as_of_date(origin.date()))
        event = latest(kh03)[(kh03["quarter_start"] == q0) & kh03["ga_available"].gt(0)].assign(
            occ=lambda d: d["ga_occupied"] / d["ga_available"])[["org_code", "occ"]]
        u = rng.uniform(size=N_DRAWS)                          # comonotone across months
        usable = set(coefs.dropna(subset=["beds"])["org_code"]) & set(event["org_code"])
        for model, g in s[(s["origin"] == origin) & s["period"].isin(months)].groupby("model"):
            gi = g[g["series"].isin(usable)].groupby("series").filter(
                lambda x: x["period"].nunique() == 3).sort_values(["series", "period"])
            trusts = list(dict.fromkeys(gi["series"]))
            if not trusts:
                continue
            draws = sample_quantiles(gi[qcols].to_numpy(float), QUANTILES, N_DRAWS, rng, u=u)
            total = draws.reshape(len(trusts), 3, N_DRAWS).sum(axis=1)
            days = np.full(len(trusts), float(sum(m.days_in_month for m in months)))
            c = coefs.set_index("org_code").loc[trusts].reset_index()
            occ = occupancy_draws(total, days, c, rng)
            p = (occ / c["beds"].to_numpy()[:, None] > THRESHOLD).mean(axis=1)
            ev = event.set_index("org_code").loc[trusts, "occ"].to_numpy() > THRESHOLD
            rows.append(pd.DataFrame({"model": model, "quarter_start": q0, "org_code": trusts,
                                      "p": p, "event": ev}))
    d = pd.concat(rows, ignore_index=True)
    out = []
    for model, g in d.groupby("model"):
        r = {"model": model, "trust_quarters": len(g), "event_rate": g["event"].mean(),
             "mean_p": g["p"].mean(), "brier": float(np.mean((g["p"] - g["event"]) ** 2))}
        for ratio in COST_LOSS:
            r[f"expense_{ratio}"] = cost_loss_expense(g["p"].to_numpy(), g["event"].to_numpy(), ratio)
        r["expense_mean"] = np.mean([r[f"expense_{x}"] for x in COST_LOSS])
        out.append(r)
    return pd.DataFrame(out).sort_values("expense_mean"), d


def load_discharge(path=PROCESSED_DIR / "discharge.parquet") -> pd.DataFrame:
    d = pd.read_parquet(path)
    for c in ("period", "published"):
        d[c] = pd.to_datetime(d[c]).astype("datetime64[ns]")
    return d[~d["is_total"]]


def discharge_quarterly(discharge: pd.DataFrame, as_of: pd.Timestamp | None = None) -> pd.DataFrame:
    """Quarter mean of daily NCtR patients remaining in hospital, per trust, from the latest
    version published by ``as_of`` (all versions if None: the latest)."""
    d = discharge if as_of is None else discharge[discharge["published"] <= as_of]
    d = d.sort_values("published").drop_duplicates(["org_code", "period"], keep="last")
    d = d.assign(quarter_start=d["period"].dt.to_period("Q").dt.start_time)
    q = d.groupby(["org_code", "quarter_start"]).agg(nctr=("remaining_avg", "mean"),
                                                     months=("period", "nunique")).reset_index()
    return q[q["months"] == 3].drop(columns="months")


def validate_nctr(kh03: pd.DataFrame, adm_q: pd.DataFrame, discharge: pd.DataFrame,
                  quarters=VALIDATION_QUARTERS) -> pd.DataFrame:
    """G2: trust ratio + pooled NCtR slope, on the trust-quarters where NCtR exists, against
    the trust-only prediction for the same rows."""
    rows = []
    actual = latest(kh03).merge(adm_q, on=["org_code", "quarter_start"])
    actual = actual[actual["ga_available"].gt(0) & actual["ga_occupied"].gt(0)]
    nq_all = discharge_quarterly(discharge)
    for q in quarters:
        as_of = pd.Timestamp(q)
        nq = discharge_quarterly(discharge, as_of)
        truth = actual[actual["quarter_start"] == q].merge(
            nq_all[nq_all["quarter_start"] == q][["org_code", "nctr"]], on="org_code")
        if truth.empty or nq.empty:
            continue
        c = fit_coefficients(kh03, adm_q, as_of)
        hist = _usable(kh03, as_of).merge(adm_q, on=["org_code", "quarter_start"]).merge(
            nq, on=["org_code", "quarter_start"]).merge(c[["org_code", "log_c"]], on="org_code")
        if hist["org_code"].nunique() < 10 or len(hist) < 30:
            continue
        hist["x"] = hist["nctr"] / hist["ga_available"]
        hist["r"] = np.log(hist["ga_occupied"] * hist["days"] / hist["adm"]) - hist["log_c"]
        xd = hist["x"] - hist.groupby("org_code")["x"].transform("mean")
        rd = hist["r"] - hist.groupby("org_code")["r"].transform("mean")
        b = float((xd * rd).sum() / (xd ** 2).sum())
        xbar = hist.groupby("org_code")["x"].mean()
        t = truth.merge(c[["org_code", "log_c"]], on="org_code")
        t = t[t["org_code"].isin(xbar.index)]
        base = np.exp(t["log_c"]) * t["adm"] / t["days"] / t["ga_available"]
        x = t["nctr"] / t["ga_available"]
        adj = base * np.exp(b * (x - t["org_code"].map(xbar)))
        occ = t["ga_occupied"] / t["ga_available"]
        for variant, pred in (("trust_same_rows", base), ("trust+nctr", adj)):
            rows.append(pd.DataFrame({"quarter_start": q, "org_code": t["org_code"],
                                      "variant": variant, "occ_actual": occ, "occ_pred": pred,
                                      "b": b}))
    if not rows:
        return pd.DataFrame(columns=["quarter_start", "org_code", "variant", "occ_actual",
                                     "occ_pred", "b", "err_pp", "covid_window"])
    v = pd.concat(rows, ignore_index=True)
    v["err_pp"] = 100 * (v["occ_pred"] - v["occ_actual"])
    v["covid_window"] = False
    return v


def persistence_check(v: pd.DataFrame, kh03: pd.DataFrame, adm_q: pd.DataFrame) -> pd.DataFrame:
    """EXPLORATORY (not pre-registered): the registered reconstruction against two naive
    occupancy predictors on the same trust-quarters — the latest occupancy published by the
    quarter's start, and the same quarter a year earlier — restricted to acute trusts
    (≥ 100 G&A beds, median quarterly A&E admissions ≥ 1,500) whose footprint (beds) has
    not changed by more than 30% since the coefficient was fitted."""
    t = v[(v["variant"] == "trust") & ~v["covid_window"]]
    lat = latest(kh03)
    lat = lat[lat["ga_available"].gt(0) & lat["ga_occupied"].gt(0)]
    rows = []
    for q in sorted(t["quarter_start"].unique()):
        u = _usable(kh03, pd.Timestamp(q)).sort_values("quarter_start")
        last = u.groupby("org_code").last()
        ly = u[u["quarter_start"] == pd.Timestamp(q) - pd.DateOffset(years=1)].set_index("org_code")
        c = fit_coefficients(kh03, adm_q, pd.Timestamp(q)).set_index("org_code")
        for org in t.loc[t["quarter_start"] == q, "org_code"]:
            rows.append({"quarter_start": q, "org_code": org, "beds_fit": c["beds"].get(org, np.nan),
                         "persist": (last["ga_occupied"] / last["ga_available"]).get(org, np.nan),
                         "same_q_ly": (ly["ga_occupied"] / ly["ga_available"]).get(org, np.nan)})
    x = t.merge(pd.DataFrame(rows), on=["quarter_start", "org_code"]).merge(
        lat[["org_code", "quarter_start", "ga_available"]], on=["org_code", "quarter_start"])
    size = adm_q.groupby("org_code")["adm"].median()
    keep = ((np.log(x["ga_available"] / x["beds_fit"]).abs() <= np.log(1.3))
            & (x["ga_available"] >= 100) & x["org_code"].map(size).ge(1500))

    def summ(d, col):
        e = (100 * (d[col] - d["occ_actual"])).dropna()
        return {"trust_quarters": len(e), "median_abs_pp": float(e.abs().median()),
                "share_within_10pp": float((e.abs() <= 10).mean())}
    return pd.DataFrame({
        "registered reconstruction, all trust-quarters": summ(x, "occ_pred"),
        "registered reconstruction, acute + unchanged footprint": summ(x[keep], "occ_pred"),
        "naive: latest published occupancy (same rows)": summ(x[keep], "persist"),
        "naive: same quarter last year (same rows)": summ(x[keep], "same_q_ly"),
    }).T


def breach_illustration(scores: pd.DataFrame, kh03: pd.DataFrame, adm_q: pd.DataFrame,
                        model: str, origin: str = "2023-10-01", seed: int = 0) -> pd.DataFrame:
    """Monthly P(occupancy > 92%) from one candidate at one DEV origin (horizons whose
    target is unsealed), with the published occupancy of each month's quarter alongside."""
    o = pd.Timestamp(origin)
    s = scores[(scores["model"] == model) & (scores["target"] == "adm_via_ae")
               & (scores["level"] == "provider") & (scores["origin"] == o)]
    coefs = fit_coefficients(kh03, adm_q, as_of_date(o.date()))
    s = s[s["series"].isin(set(coefs.dropna(subset=["beds"])["org_code"]))].reset_index(drop=True)
    rng = np.random.default_rng(seed)
    draws = sample_quantiles(s[list(QUANTILES)].to_numpy(float), QUANTILES, N_DRAWS, rng)
    c = coefs.set_index("org_code").loc[s["series"]].reset_index()
    occ = occupancy_draws(draws, s["period"].dt.days_in_month.to_numpy(float), c, rng)
    out = pd.concat([s[["origin", "series", "horizon", "period", 0.5, "y"]].rename(
        columns={0.5: "adm_median", "y": "adm_outturn"}), breach_table(occ, c["beds"].to_numpy())],
        axis=1)
    out["beds"], out["c_bed_days_per_adm"] = c["beds"].to_numpy(), np.exp(c["log_c"].to_numpy())
    lat = latest(kh03).assign(occ_published=lambda d: d["ga_occupied"] / d["ga_available"])
    out["quarter_start"] = out["period"].dt.to_period("Q").dt.start_time
    out = out.merge(lat[["org_code", "quarter_start", "occ_published"]], how="left",
                    left_on=["series", "quarter_start"], right_on=["org_code", "quarter_start"])
    return out.drop(columns="org_code")


def select_candidate(par: pd.DataFrame, dl: pd.DataFrame | None, g_passes: bool,
                     mmd_cov_pp: float) -> tuple[str, str]:
    """The STOP 4 rule of the Stage D amendment, applied mechanically. Returns (model, why)."""
    meeting = par[par["meets"]]
    if len(meeting):
        if g_passes and dl is not None and len(dl):
            d = dl[dl["model"].isin(meeting["model"])].sort_values("expense_mean")
            return d["model"].iloc[0], "meets the criterion; lowest decision loss"
        m = meeting.sort_values("gm_rel_to_ets")
        why = ("meets the criterion; lowest winter-h3 WIS (decision loss not used: "
               + ("occupancy check failed its tolerance)" if not g_passes else "unavailable)"))
        return m["model"].iloc[0], why
    best = par["worst_dev"].min()
    tied = par[par["worst_dev"] <= best + mmd_cov_pp / 100].sort_values("gm_rel_to_ets")
    return tied["model"].iloc[0], (f"no candidate meets the criterion; smallest worst-cell deviation "
                                   f"({100 * best:.1f} pp), ties within {mmd_cov_pp:.1f} pp broken by WIS")


def run(kh03_path=PROCESSED_DIR / "kh03.parquet", discharge_path=PROCESSED_DIR / "discharge.parquet",
        meta: dict | None = None) -> str:
    from datetime import date

    from nhs_ae.decide.occupancy import quarterly_admissions
    from nhs_ae.evaluate import stage_d
    from nhs_ae.evaluate.asof import load_vintages
    meta = meta or {}
    RESULTS.mkdir(parents=True, exist_ok=True)
    adm_q = quarterly_admissions(monthly_admissions(load_vintages()))
    kh03, dis = load_kh03(kh03_path), load_discharge(discharge_path)
    v, v2 = validate(kh03, adm_q), validate_nctr(kh03, adm_q, dis)
    allv = pd.concat([v, v2], ignore_index=True)
    allv.to_csv(RESULTS / "occupancy_validation.csv", index=False)
    summ = validation_summary(allv)
    reg = summ[(summ["variant"] == "trust") & ~summ["covid_window"]].iloc[0]
    g_passes = bool(reg["passes"])
    pers = persistence_check(v, kh03, adm_q)
    by_year = (v[(v["variant"] == "trust") & ~v["covid_window"]]
               .assign(year=lambda d: d["quarter_start"].dt.year).groupby("year")["err_pp"]
               .agg(trust_quarters="size", median_abs_pp=lambda x: x.abs().median(),
                    share_within_10pp=lambda x: (x.abs() <= 10).mean(), mean_err_pp="median"))
    coefs = pd.concat([fit_coefficients(kh03, adm_q, as_of_date(date(2023, 12, 1))).assign(as_of="2023-12-14"),
                       fit_coefficients(kh03, adm_q, pd.Timestamp(meta.get("date", "2026-09-10"))).assign(
                           as_of=meta.get("date", "2026-09-10"))])
    coefs.assign(c_bed_days_per_adm=np.exp(coefs["log_c"])).to_csv(RESULTS / "los_coefficients.csv", index=False)
    lines = ["# Stage G — occupancy validation", "",
             f"Run {meta.get('date', '?')} at commit `{meta.get('sha', '?')}`; design and tolerance in the",
             "pre-registration amendments of 2026-09-09 (tolerance) and 2026-09-10 (Stage G design).", "",
             "## Registered check (out of sample, DEV quarters Apr–Jun 2018 to Oct–Dec 2023)", "",
             "Reconstructed occupancy = c_j × realised A&E admissions / days / the quarter's G&A beds,",
             "with c_j fitted only on KH03 quarters published before the quarter began.", "",
             "| variant | COVID window | trust-quarters | median \\|error\\| (pp) | within 10 pp | median error (pp) | passes |",
             "|---|---|---|---|---|---|---|"]
    for _, r in summ.iterrows():
        lines.append(f"| {r['variant']} | {'yes' if r['covid_window'] else 'no'} | {int(r['trust_quarters'])} | "
                     f"{r['median_abs_pp']:.1f} | {r['share_within_10pp']:.0%} | {r['mean_err_pp']:.1f} | "
                     f"{'yes' if r['passes'] else 'no'} |")
    lines += ["", ("Tolerance (registered 2026-09-09): median |error| ≤ 5 pp and ≥ 80% of trust-quarters "
                   "within 10 pp. The test applies to the trust-specific variant outside the COVID window."), "",
              f"**Verdict: {'PASSES' if g_passes else 'FAILS'}** — median {reg['median_abs_pp']:.1f} pp, "
              f"{reg['share_within_10pp']:.0%} within 10 pp. "
              + ("" if g_passes else "Under the registered rule the decision layer is **illustrative only**, "
                 "the memo's bed numbers carry that label, and Stage D's selection falls back to WIS."), "",
              "By year (trust-specific, outside the COVID window; 'mean_err_pp' is the median signed error):", "",
              md_table(by_year.round(2)), "",
              "## Exploratory (not pre-registered): what does predict occupancy?", "",
              md_table(pers.round(3)), "",
              "Occupancy is far more predictable from its own recent level than from A&E admissions: hospitals",
              "run close to capacity and the rest of their admissions flex around emergency demand, so an",
              "admissions forecast carries little of the occupancy signal at quarterly resolution [inference].",
              "This is a candidate redesign for the decision layer (occupancy persistence plus an admissions",
              "surprise term), to be registered before it is tested.", ""]
    (RESULTS / "occupancy_validation.md").write_text("\n".join(lines))
    stop = ["STOP 8 — decision layer",
            (f"  occupancy check (trust-specific, outside COVID): median |err| {reg['median_abs_pp']:.1f} pp, "
             f"{reg['share_within_10pp']:.0%} within 10 pp -> {'PASSES' if g_passes else 'FAILS'} "
             "(tolerance 5 pp / 80%)"),
            "  exploratory: naive persistence " + ", ".join(
                f"{k.split(':')[1].strip().split(' (')[0]} {r['median_abs_pp']:.1f} pp / {r['share_within_10pp']:.0%}"
                for k, r in pers.iterrows() if k.startswith("naive"))]
    scores_path = stage_d.WORK / "scores.parquet"
    par_path = stage_d.RESULTS / "pareto.csv"
    if scores_path.exists() and par_path.exists():
        scores = pd.read_parquet(scores_path)
        scores.columns = [float(c) if str(c).replace(".", "", 1).isdigit() and "." in str(c) else c
                          for c in scores.columns]
        dl, _ = decision_loss(scores, kh03, adm_q)
        dl.to_csv(stage_d.RESULTS / "decision_loss.csv", index=False)
        par = pd.read_csv(par_path)
        mmd = _mmd_cov()
        chosen, why = select_candidate(par, dl, g_passes, mmd)
        wis_best = par.sort_values("gm_rel_to_ets")["model"].iloc[0]
        dl_best = dl["model"].iloc[0]
        _write_decision_loss(dl, chosen, why, wis_best, dl_best, g_passes)
        b = breach_illustration(scores, kh03, adm_q, chosen)
        b.to_csv(RESULTS / "breach_probabilities.csv", index=False)
        dec = b[b["period"] == b["period"].max()].sort_values("p_breach")
        pick = dec.iloc[[0, len(dec) // 2, -1]] if len(dec) >= 3 else dec
        stop += [f"  STOP 4 selection (rule of the Stage D amendment): {stage_d.LABELS.get(chosen, chosen)} — {why}",
                 (f"  lowest decision loss: {stage_d.LABELS.get(dl_best, dl_best)}; lowest WIS: "
                  f"{stage_d.LABELS.get(wis_best, wis_best)}"),
                 (f"  illustration ({'illustrative only' if not g_passes else 'operational'}): origin 2023-10, "
                  f"{dec['period'].max():%b %Y}, three trusts:")]
        for _, r in pick.iterrows():
            stop.append(f"    {r['series']}: P(occ>92%) {r['p_breach']:.2f}, median occ {r['occ_median']:.1%}, "
                        f"escalation beds {int(r['escalation_beds'])}, published Q occ {r['occ_published']:.1%}")
    text = "\n".join(stop)
    (RESULTS / "stop8.txt").write_text(text + "\n")
    (RESULTS / "README.md").write_text(
        "# results/G-decision\n\nStage G of the 2026-09-10 work order "
        f"(run {meta.get('date', '?')}, commit `{meta.get('sha', '?')}`).\n\n"
        "- `occupancy_validation.md` / `.csv`: the registered out-of-sample occupancy check, by variant, "
        "year and trust-quarter, plus the exploratory persistence comparison\n"
        "- `los_coefficients.csv`: bed-days per A&E admission per trust, as of the DEV end and as of the run date\n"
        "- `breach_probabilities.csv`: monthly P(occupancy > 92%) for the Stage D selection at origin 2023-10\n"
        "- `stop8.txt`: the STOP 8 summary\n")
    return text


def _mmd_cov() -> float:
    path = PROJECT_ROOT / "results" / "A-noise-floor" / "noise_table.csv"
    if not path.exists():
        return 0.0
    t = pd.read_csv(path)
    t = t[(t["run"] == "floor") & (t["slice"] == "winter_h3")]
    return float(t["mmd_cov90_pp"].mean()) if len(t) else 0.0


def _write_decision_loss(dl, chosen, why, wis_best, dl_best, g_passes) -> None:
    from nhs_ae.evaluate import stage_d
    lines = ["# Stage D3 — decision loss", "",
             "Definition in the Stage G amendment of 2026-09-10: DEV winter quarters (COVID window excluded),",
             "forecast from the origin two months before the quarter, admissions drawn comonotonically, bed-days",
             "ratio and beds as of that origin; event = published KH03 G&A occupancy > 92%; expense averaged",
             "over cost-loss ratios 0.1, 0.25, 0.5 (loss normalised to 1).", "",
             ("**The occupancy check failed its tolerance, so these losses are illustrative and, under the "
              "registered rule, not used for selection.**" if not g_passes else ""), "",
             md_table(dl.assign(model=dl["model"].map(lambda m: stage_d.LABELS.get(m, m))).round(4), index=False), "",
             f"Selected: **{stage_d.LABELS.get(chosen, chosen)}** — {why}.",
             f"Lowest decision loss: {stage_d.LABELS.get(dl_best, dl_best)}; lowest WIS: "
             f"{stage_d.LABELS.get(wis_best, wis_best)}."
             + (" They differ — reported as a finding." if dl_best != wis_best else " They agree."), ""]
    (stage_d.RESULTS / "decision_loss.md").write_text("\n".join(lines))


def md_table(df: pd.DataFrame, index: bool = True) -> str:
    """A GitHub markdown table without the tabulate dependency."""
    d = df.reset_index() if index else df
    head = "| " + " | ".join(str(c) for c in d.columns) + " |"
    rule = "|" + "---|" * len(d.columns)
    def fmt(x):
        if isinstance(x, float):
            return f"{x:.0f}" if x.is_integer() and abs(x) >= 10 else f"{x:.3g}"
        return str(x)
    body = ["| " + " | ".join(fmt(x) for x in row) + " |" for row in d.itertuples(index=False)]
    return "\n".join([head, rule, *body])
