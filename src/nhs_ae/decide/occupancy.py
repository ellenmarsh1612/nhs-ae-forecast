"""Decision layer, Stage G: admissions forecast → occupied beds → P(occupancy > 92%).

Occupancy model (replaces the pre-registered fixed lognormal length of stay; amendment of
2026-09-10, Stage G). For trust j and quarter q, with A the emergency admissions via A&E
in the quarter, D its days and O the KH03 average daily occupied general & acute beds,

    log(O·D / A) = log c_j + ε,     ε ~ N(0, s_j²),

so c_j is *effective occupied bed-days per A&E admission*. It absorbs everything the
admissions series leaves out — elective and GP-direct admissions, case mix, age, SDEC
coding, discharge delays — as a trust-level ratio, and the residual s_j carries what the
ratio cannot. Estimation, as of a date: for each quarter the latest KH03 version
*published* by then; only quarters after the trust's latest footprint break (a >30%
quarter-on-quarter jump in beds or admissions: mergers where the absorbing trust keeps its
code); the most recent ``WINDOW`` of those, COVID-window quarters excluded; log
c_j is shrunk towards the national mean by empirical Bayes (normal–normal, method of
moments), and s_j towards the pooled residual SD with ``K0`` pseudo-degrees of freedom.

Breach probability for a month: admissions are drawn from the forecast's quantile
function (log value linear in the normal score of the quantile level, extrapolated
linearly past the outermost quantiles), occupied beds = c_j·A/D·exp(ε), and
P(occupied / beds > 0.92) is the share of draws above. Beds are KH03 G&A beds available
in the latest quarter published by the origin (pre-registration §8). Escalation beds are
the extra beds that bring that probability down to 20%. The cost-loss grid (0.1, 0.25,
0.5) turns probabilities into escalate/do-not-escalate calls.

The quarterly residual s_j understates month-to-month variation, so monthly breach
probabilities are a decision aid rather than calibrated risks; the memo says so.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

THRESHOLD = 0.92
COST_LOSS = (0.1, 0.25, 0.5)
TARGET_P = 0.20
WINDOW = 8          # KH03 quarters per trust used to estimate c_j
K0 = 4.0            # pseudo-degrees of freedom shrinking s_j towards the pooled SD
COVID = (pd.Timestamp("2020-03-01"), pd.Timestamp("2021-06-01"))


def quarter_start(period: pd.Series) -> pd.Series:
    p = pd.to_datetime(period)
    return p.dt.to_period("Q").dt.start_time


def quarterly_admissions(monthly: pd.DataFrame) -> pd.DataFrame:
    """``org_code, period, adm`` (monthly) → ``org_code, quarter_start, adm, days``;
    only quarters with all three months present."""
    m = monthly.assign(quarter_start=quarter_start(monthly["period"]),
                       days=pd.to_datetime(monthly["period"]).dt.days_in_month)
    q = m.groupby(["org_code", "quarter_start"]).agg(adm=("adm", "sum"), days=("days", "sum"),
                                                     months=("adm", "count")).reset_index()
    return q[q["months"] == 3].drop(columns="months")


BREAK = np.log(1.3)  # quarter-on-quarter jump in beds or admissions that marks a new footprint


def _usable(kh03: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Per trust and quarter, the latest KH03 version published by ``as_of``; zero-bed and
    zero-occupied rows (missing returns entered as zero) and COVID-window quarters dropped."""
    k = kh03[kh03["published"] <= as_of].sort_values("published", kind="stable")
    k = k.drop_duplicates(["org_code", "quarter_start"], keep="last")
    if "is_total" in k.columns:
        k = k[~k["is_total"]]
    k = k[k["ga_occupied"].gt(0) & k["ga_available"].gt(0)]
    q_end = k["quarter_start"] + pd.offsets.QuarterEnd(0)
    return k[~((k["quarter_start"] <= COVID[1]) & (q_end >= COVID[0]))]


def _after_breaks(d: pd.DataFrame) -> pd.DataFrame:
    """Keep each trust's quarters after its latest footprint break: a quarter-on-quarter
    change of more than 30% in G&A beds or in A&E admissions (a merger in which the
    absorbing trust keeps its code moves both, not always in the same quarter)."""
    d = d.sort_values(["org_code", "quarter_start"])
    jump = (d.groupby("org_code")["ga_available"].transform(lambda x: np.log(x).diff().abs()) > BREAK) | \
           (d.groupby("org_code")["adm"].transform(lambda x: np.log(x).diff().abs()) > BREAK)
    seg = jump.astype(int).groupby(d["org_code"]).cumsum()
    return d[seg == seg.groupby(d["org_code"]).transform("max")]


def fit_coefficients(kh03: pd.DataFrame, adm_q: pd.DataFrame, as_of: pd.Timestamp,
                     window: int = WINDOW, pooled_only: bool = False) -> pd.DataFrame:
    """Per trust: log c (shrunk), raw mean, n, residual SD (shrunk), latest beds available."""
    k = _usable(kh03, as_of)
    latest_beds = (k.sort_values("quarter_start").groupby("org_code")
                    .agg(beds=("ga_available", "last"), beds_quarter=("quarter_start", "last")))
    d = k.merge(adm_q, on=["org_code", "quarter_start"], how="inner")
    d = _after_breaks(d[d["adm"] > 0])
    d = d.sort_values("quarter_start").groupby("org_code").tail(window)
    d["y"] = np.log(d["ga_occupied"] * d["days"] / d["adm"])
    g = d.groupby("org_code")["y"].agg(["mean", "var", "count"]).rename(
        columns={"mean": "ybar", "var": "s2", "count": "n"})
    if g.empty:
        return g
    s2_pool = float(np.average(g["s2"].fillna(0), weights=np.maximum(g["n"] - 1, 0) + 1e-9))
    mu = float(np.average(g["ybar"], weights=g["n"]))
    tau2 = max(float(g["ybar"].var(ddof=1) - np.mean(s2_pool / g["n"])), 1e-6)
    w = 0.0 if pooled_only else tau2 / (tau2 + s2_pool / g["n"])
    g["log_c"] = w * g["ybar"] + (1 - w) * mu
    df = np.maximum(g["n"] - 1, 0)
    g["s"] = np.sqrt((df * g["s2"].fillna(0) + K0 * s2_pool) / (df + K0))
    g["mu"], g["tau"], g["s_pool"] = mu, np.sqrt(tau2), np.sqrt(s2_pool)
    return g.join(latest_beds, how="left").reset_index()


def sample_quantiles(qvals: np.ndarray, levels, n_draws: int, rng, u: np.ndarray | None = None):
    """Draws from each row's quantile function: log value linear in Φ⁻¹(level), with the
    outermost segments extended for the tails. ``u`` (n_draws,) makes rows comonotone."""
    z = stats.norm.ppf(levels)
    lv = np.log(np.maximum(qvals, 1e-9))
    u = rng.uniform(size=n_draws) if u is None else u
    zu = stats.norm.ppf(np.clip(u, 1e-6, 1 - 1e-6))
    out = np.empty((len(qvals), n_draws))
    lo_slope = (lv[:, 1] - lv[:, 0]) / (z[1] - z[0])
    hi_slope = (lv[:, -1] - lv[:, -2]) / (z[-1] - z[-2])
    for i in range(len(qvals)):
        v = np.interp(zu, z, lv[i])
        v = np.where(zu < z[0], lv[i, 0] + lo_slope[i] * (zu - z[0]), v)
        v = np.where(zu > z[-1], lv[i, -1] + hi_slope[i] * (zu - z[-1]), v)
        out[i] = np.exp(v)
    return out


def occupancy_draws(adm_draws: np.ndarray, days: np.ndarray, coefs: pd.DataFrame, rng) -> np.ndarray:
    """Occupied beds (rows × draws) = c·A/D·exp(ε), ε ~ N(0, s²) per row."""
    eps = rng.standard_normal(adm_draws.shape) * coefs["s"].to_numpy()[:, None]
    return np.exp(coefs["log_c"].to_numpy()[:, None]) * adm_draws / days[:, None] * np.exp(eps)


def breach_table(occ: np.ndarray, beds: np.ndarray) -> pd.DataFrame:
    """P(occupancy > 92%), escalation beds to bring it to 20%, cost-loss calls."""
    p = (occ / beds[:, None] > THRESHOLD).mean(axis=1)
    extra = np.maximum(0.0, np.quantile(occ, 1 - TARGET_P, axis=1) / THRESHOLD - beds)
    out = pd.DataFrame({"p_breach": p, "escalation_beds": np.ceil(extra),
                        "occ_median": np.median(occ, axis=1) / beds})
    for r in COST_LOSS:
        out[f"escalate_at_{r}"] = p > r
    return out


def cost_loss_expense(p: np.ndarray, event: np.ndarray, ratio: float) -> float:
    """Mean expense with loss normalised to 1: pay ``ratio`` if escalating, else 1 if the
    breach happens."""
    act = p > ratio
    return float(np.mean(np.where(act, ratio, event.astype(float))))
