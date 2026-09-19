"""M2: hierarchical Bayesian model at ICB level (Stage E; specification in the
pre-registration amendments of 2026-09-10, "Stage E infrastructure" and "M2a").

Three negative-binomial series per ICB: Type 1 attendances, other attendances (all types
minus Type 1) and emergency admissions via A&E. All-types attendances are the sum of the
first two, draw by draw, so the three targets stay coherent. Admissions use Type 1
attendances as exposure: the fit conditions on the observed attendances, the forecast on
simulated ones, so attendance uncertainty reaches the admissions forecast.

Scaling. Each series is centred on the log of its ICB's mean over the 12 months before
the origin (admissions: the log admissions-per-Type-1-attendance rate), and time is in
years from the origin. Random intercepts are therefore departures from the recent level,
which keeps one set of priors sensible for ICBs whose sizes differ tenfold.

Every random effect is non-centred (``z ~ N(0, 1)``, effect = scale × z). Rungs beyond
M2a are switched on by ``Rung`` flags as each is registered.

Sampling uses nutpie on the compiled PyMC model; forecasts are posterior-predictive
draws (one predictive draw per posterior draw), summarised as the harness's nine
quantiles.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from nhs_ae.models.base import HORIZONS, QUANTILES

log = logging.getLogger(__name__)

SERIES = ("type1", "other", "adm")
K = 3                              # Fourier harmonics
COVID = (pd.Timestamp("2020-03-01"), pd.Timestamp("2021-06-01"))
BOOKED_FROM = pd.Timestamp("2020-08-01")
EXCLUDE = ("UNMAPPED", "LEGACY")


@dataclass(frozen=True)
class Rung:
    """Which ladder features are on. M2a is all False."""
    name: str = "m2a"
    hier_season: bool = False      # M2b: ICB seasonality around region around national
    struct_disp: bool = False      # M2c: dispersion by ICB and winter
    rw_level: bool = False         # M2d: random-walk level
    dyn_conversion: bool = False   # M2e: admission rate as a random walk + winter term
    shared_factor: bool = False    # M2f: shared national latent factor
    centred: bool = False          # ICB effects sampled centred (amendment after STOP 5)
    booked_flag: bool = True       # M2d drops it: not identified alongside a random-walk level
    clean_data: bool = False       # months <= 0 or < 10% of trailing median treated as missing
    direct_all: bool = False       # all-types attendances modelled directly, not Type 1 + other
    rw_regime: bool = False        # M2d2: separate walk volatility inside the COVID window
    corr_innov: bool = False       # forecast innovations correlated across ICBs (post-fit)
    sparse_factor: bool = False    # M2f-r attempt 1: national walk with Cauchy innovations
    fixed_season: bool = False     # M2f-r attempt 2: seasonality estimated first, then held fixed
    month_effects: bool = False    # M2f-r3: stage 1 uses month-of-year effects + days offset
    national_regime: bool = False  # M2f-r4: national walk gets its own COVID-window volatility

    @property
    def series(self) -> tuple[str, ...]:
        return ("type1", "all", "adm") if self.direct_all else SERIES


M2A = Rung()
M2B = Rung(name="m2b", hier_season=True)
M2C_ON_A = Rung(name="m2c_on_a", struct_disp=True)
M2C_ON_B = Rung(name="m2c_on_b", hier_season=True, struct_disp=True)
M2A_C = Rung(name="m2a_c", centred=True, clean_data=True, direct_all=True)   # M2a, centred: M2d's comparison base
M2D = Rung(name="m2d", centred=True, rw_level=True, booked_flag=False, clean_data=True,
           direct_all=True)
M2D2 = Rung(name="m2d2", centred=True, rw_level=True, booked_flag=False, clean_data=True,
            direct_all=True, rw_regime=True)
M2E_ON_D = Rung(name="m2e_on_d", centred=True, rw_level=True, booked_flag=False, clean_data=True,
                direct_all=True, dyn_conversion=True)
M2E_ON_D2 = Rung(name="m2e_on_d2", centred=True, rw_level=True, booked_flag=False, clean_data=True,
                 direct_all=True, rw_regime=True, dyn_conversion=True)
RW_NU = 4.0                                              # Student-t innovations (fixed)


M2D_CORR = Rung(name="m2d_corr", centred=True, rw_level=True, booked_flag=False, clean_data=True,
                direct_all=True, corr_innov=True)
CORR_SHRINK = 0.2
M2F_R = Rung(name="m2f_r", centred=True, rw_level=True, booked_flag=False, clean_data=True,
             direct_all=True, shared_factor=True, sparse_factor=True)
M2F_R2 = Rung(name="m2f_r2", centred=True, rw_level=True, booked_flag=False, clean_data=True,
              direct_all=True, shared_factor=True, fixed_season=True)
M2F_R3 = Rung(name="m2f_r3", centred=True, rw_level=True, booked_flag=False, clean_data=True,
              direct_all=True, shared_factor=True, fixed_season=True, month_effects=True)
M2F_R4 = Rung(name="m2f_r4", centred=True, rw_level=True, booked_flag=False, clean_data=True,
              direct_all=True, shared_factor=True, fixed_season=True, month_effects=True,
              national_regime=True)


def innovation_corr(level_paths: np.ndarray, shrink: float = CORR_SHRINK) -> np.ndarray:
    """Cholesky factor of the ICB correlation of walk innovations: Spearman ρ between ICBs'
    month-to-month level changes, mapped to a Gaussian-copula correlation 2·sin(πρ/6),
    shrunk towards the identity, eigenvalues clipped."""
    from scipy.stats import rankdata
    innov = np.diff(level_paths, axis=1)                                   # (n, T-1)
    ranks = np.apply_along_axis(rankdata, 1, innov)
    rho = np.corrcoef(ranks)
    r = 2 * np.sin(np.pi * np.nan_to_num(rho) / 6)
    np.fill_diagonal(r, 1.0)
    r = (1 - shrink) * r + shrink * np.eye(len(r))
    w, v = np.linalg.eigh(r)
    r = (v * np.clip(w, 1e-6, None)) @ v.T
    dinv = 1 / np.sqrt(np.diag(r))
    return np.linalg.cholesky(r * dinv[:, None] * dinv[None, :])


def with_factor(base: Rung) -> Rung:
    """M2f on a given base: the base plus a shared national walk."""
    from dataclasses import replace
    return replace(base, name=f"m2f_on_{base.name}", shared_factor=True)


def with_aggregates(base: Rung) -> Rung:
    """The same model under another name, refitted to keep joint draws for aggregation."""
    from dataclasses import replace
    return replace(base, name=f"{base.name}_agg")


@dataclass
class M2Data:
    months: pd.DatetimeIndex
    icbs: list[str]
    y: dict[str, np.ndarray]            # series -> (n_icb, T), NaN where unpublished
    offset: dict[str, np.ndarray]       # series -> (n_icb,)
    region: np.ndarray = field(default_factory=lambda: np.array([]))   # codes, for M2b


def _implausible_to_nan(y: np.ndarray) -> np.ndarray:
    """ICB-months <= 0 or below 10% of the series' trailing 12-month median -> NaN (reporting
    artefacts such as a whole block of providers dropping out of the all-types sum)."""
    med = pd.DataFrame(y.T).rolling(12, min_periods=6).median().shift(1).to_numpy().T
    with np.errstate(divide="ignore", invalid="ignore"):
        bad = (y <= 0) | (np.nan_to_num(y / med, nan=1.0) < 0.1)
    return np.where(bad, np.nan, y)


def prepare(panels: dict[str, pd.DataFrame], region_of: pd.Series | None = None,
            clean: bool = False) -> M2Data:
    """``panels``: target -> (months × ICB) as-of panels ending at the last published month."""
    t1, al, ad = (panels[k] for k in ("att_type1", "att_all", "adm_via_ae"))
    icbs = [c for c in t1.columns if c in al.columns and c in ad.columns and c not in EXCLUDE]
    t1, al, ad = t1[icbs], al[icbs], ad[icbs]
    other = al - t1
    first = max(x.dropna(how="all").index.min() for x in (t1, other, ad))
    months = t1.loc[first:].index
    y = {"type1": t1.loc[months].to_numpy(float).T, "other": other.loc[months].to_numpy(float).T,
         "adm": ad.loc[months].to_numpy(float).T}
    y["other"] = np.where(y["other"] < 0, np.nan, y["other"])
    y["all"] = al.loc[months].to_numpy(float).T
    if clean:
        y = {k: _implausible_to_nan(val) for k, val in y.items()}
    off = {s: np.log(np.maximum(_recent_mean(y[s]), 1.0)) for s in ("type1", "other", "all")}
    off["adm"] = np.log(np.maximum(_recent_mean(y["adm"]), 1.0) / np.maximum(_recent_mean(y["type1"]), 1.0))
    reg = (pd.Categorical(region_of.reindex(icbs).fillna("?")).codes if region_of is not None
           else np.zeros(len(icbs), int))
    return M2Data(months=months, icbs=icbs, y=y, offset=off, region=np.asarray(reg))


def _recent_mean(y: np.ndarray, n: int = 12) -> np.ndarray:
    """Per row, the mean of its ``n`` most recent valid values. Normally that is the 12
    months before the origin; an ICB whose series is missing there (all-types summed over
    providers with complete returns can fall below Type 1, and such months are dropped) is
    centred on its latest valid year instead (amendment of 2026-09-10)."""
    out = np.full(len(y), np.nan)
    for i, row in enumerate(y):
        v = row[~np.isnan(row)]
        if len(v):
            out[i] = v[-n:].mean()
    return np.where(np.isnan(out), 1.0, out)


def design(months: pd.DatetimeIndex, origin_last: pd.Timestamp) -> dict[str, np.ndarray]:
    """Time in years from the last training month, Fourier terms, regime flags."""
    tau = ((months.year - origin_last.year) * 12 + (months.month - origin_last.month)) / 12.0
    m = months.month.to_numpy()
    fourier = np.column_stack([f(2 * np.pi * k * m / 12) for k in range(1, K + 1) for f in (np.sin, np.cos)])
    covid = ((months >= COVID[0]) & (months <= COVID[1])).astype(float)
    booked = (months >= BOOKED_FROM).astype(float)
    winter = np.isin(m, (12, 1, 2, 3)).astype(float)
    moy = np.eye(12)[m - 1]                                                # (T, 12)
    logdays = np.log(months.days_in_month.to_numpy() / 30.4375)
    return {"tau": np.asarray(tau, float), "F": fourier, "covid": np.asarray(covid),
            "booked": np.asarray(booked), "winter": winter, "moy": moy, "logdays": logdays}


def _rw_dist(n: int, T: int, nu: float | None = None):
    """Generative graph of a Student-t random walk with a (n, T−1) matrix of step scales.
    ``pm.RandomWalk`` cannot broadcast a time-varying scale, so the walk is written as a
    cumulative sum; its value variable is still the level path (centred)."""
    def dist(init_sd, sig, size):
        import pymc as pm
        import pytensor.tensor as pt
        init = pm.Normal.dist(0, init_sd, shape=(n, 1))
        innov = pm.StudentT.dist(nu=RW_NU if nu is None else nu, mu=0, sigma=sig, shape=(n, T - 1))
        return pt.cumsum(pt.concatenate([init, innov], axis=1), axis=1)
    return dist


def zero_sum_basis(n: int) -> np.ndarray:
    """Orthonormal basis (n, n-1) of the subspace of vectors summing to zero (Helmert)."""
    h = np.zeros((n, n - 1))
    for k in range(1, n):
        h[:k, k - 1] = 1.0
        h[k, k - 1] = -k
        h[:, k - 1] /= np.sqrt(k * (k + 1))
    return h


def calendar_season(d: M2Data, s: str, months: pd.DatetimeIndex) -> np.ndarray:
    """M2f-r3 stage 1, evaluated at ``months``: month-of-year effects (sum to zero) plus, for
    attendances, the days-in-month offset. Effects are estimated on the training panel by least
    squares with an intercept and trend per ICB, COVID-window months excluded."""
    X = design(d.months, d.months[-1])
    y = np.log(d.y[s]) - (np.log(d.y["type1"]) if s == "adm" else X["logdays"][None, :])
    keep = np.isfinite(y) & (X["covid"] == 0)[None, :]
    n = y.shape[0]
    rows, target = [], []
    for i in range(n):
        for t in np.flatnonzero(keep[i]):
            r = np.zeros(2 * n + 11)
            r[i], r[n + i] = 1.0, X["tau"][t]
            r[2 * n:] = X["moy"][t, 1:]                                   # January is the baseline
            rows.append(r)
            target.append(y[i, t])
    coef, *_ = np.linalg.lstsq(np.asarray(rows), np.asarray(target), rcond=None)
    effects = np.r_[0.0, coef[2 * n:]]
    effects -= effects.mean()                                             # sum to zero
    Xm = design(months, d.months[-1])
    return Xm["moy"] @ effects + (0.0 if s == "adm" else Xm["logdays"])


def seasonal_profile(d: M2Data, s: str) -> np.ndarray:
    """Stage 1 of the two-stage M2f: shared Fourier coefficients (2K,) for series ``s`` by
    least squares on log counts (admissions: log rate per Type 1 attendance), with an
    intercept and a linear trend per ICB, COVID-window months excluded."""
    X = design(d.months, d.months[-1])
    y = np.log(d.y[s]) - (np.log(d.y["type1"]) if s == "adm" else 0.0)
    keep = np.isfinite(y) & (X["covid"] == 0)[None, :]
    n = y.shape[0]
    rows, target = [], []
    for i in range(n):
        for t in np.flatnonzero(keep[i]):
            r = np.zeros(2 * n + 2 * K)
            r[i], r[n + i] = 1.0, X["tau"][t]
            r[2 * n:] = X["F"][t]
            rows.append(r)
            target.append(y[i, t])
    coef, *_ = np.linalg.lstsq(np.asarray(rows), np.asarray(target), rcond=None)
    return coef[2 * n:]


def build_model(d: M2Data, rung: Rung = M2A):
    import pymc as pm
    X = design(d.months, d.months[-1])
    T = len(d.months)
    coords = {"icb": d.icbs, "k": list(range(2 * K)), "t": list(range(T))}
    with pm.Model(coords=coords) as model:
        for s in rung.series:
            if rung.rw_level and rung.fixed_season:   # M2f-r2: zero-sum ICB walks + national walk
                import pytensor.tensor as pt
                n = len(d.icbs)
                Q = zero_sum_basis(n)                                             # (n, n-1)
                srw = pm.Gamma(f"sigma_rw_{s}", alpha=4.0, beta=100.0)
                v = pm.CustomDist(f"v_{s}", 0.5, pt.broadcast_to(srw, (n - 1, T - 1)),
                                  dist=_rw_dist(n - 1, T), shape=(n - 1, T))
                sg = pm.Gamma(f"sigma_g_{s}", alpha=4.0, beta=200.0)
                if rung.national_regime:   # M2f-r4: COVID-window volatility, national walk only
                    sgc = pm.Gamma(f"sigma_gc_{s}", alpha=4.0, beta=50.0)          # mean 0.08
                    g_sigma = pt.broadcast_to(sg + (sgc - sg) * X["covid"][1:], (1, T - 1))
                else:
                    g_sigma = pt.broadcast_to(sg, (1, T - 1))
                g = pm.CustomDist(f"gnat_{s}", 0.01, g_sigma, dist=_rw_dist(1, T), shape=(1, T))
                level = pm.Deterministic(f"ell_{s}", pt.dot(Q, v) + g, dims=("icb", "t"))
            elif rung.rw_level:    # M2d: centred Student-t random-walk level replaces a, b, COVID
                srw = pm.Gamma(f"sigma_rw_{s}", alpha=4.0, beta=100.0)          # mean 0.04, zero at 0
                if rung.rw_regime:  # M2d2: innovations inside the COVID window get their own scale
                    import pytensor.tensor as pt
                    src = pm.Gamma(f"sigma_rwc_{s}", alpha=4.0, beta=50.0)      # mean 0.08
                    step_sigma = pt.broadcast_to(srw + (src - srw) * X["covid"][1:], (len(d.icbs), T - 1))
                    # centred walk built as a cumulative sum; PyMC derives its density
                    level = pm.CustomDist(f"ell_{s}", 0.5, step_sigma, dist=_rw_dist(len(d.icbs), T),
                                          dims=("icb", "t"))
                else:
                    level = pm.RandomWalk(
                        f"ell_{s}", init_dist=pm.Normal.dist(0, 0.5, shape=len(d.icbs)),
                        innovation_dist=pm.StudentT.dist(nu=RW_NU, mu=0, sigma=srw,
                                                         shape=(len(d.icbs), T - 1)),
                        steps=T - 1, dims=("icb", "t"))
                if rung.shared_factor and not rung.fixed_season:   # M2f: national walk (centred)
                    import pytensor.tensor as pt
                    sg = (pm.Gamma(f"sigma_g_{s}", alpha=4.0, beta=400.0) if rung.sparse_factor  # 0.01
                          else pm.Gamma(f"sigma_g_{s}", alpha=4.0, beta=200.0))        # mean 0.02 (gate)
                    if rung.rw_regime:
                        sgc = pm.Gamma(f"sigma_gc_{s}", alpha=4.0, beta=100.0)      # mean 0.04 (gate)
                        g_sigma = pt.broadcast_to(sg + (sgc - sg) * X["covid"][1:], (1, T - 1))
                    else:
                        g_sigma = pt.broadcast_to(sg, (1, T - 1))
                    g = pm.CustomDist(f"gnat_{s}", 0.01, g_sigma,
                                      dist=_rw_dist(1, T, 1.0 if rung.sparse_factor else None), shape=(1, T))
                    # identification: the ICB walks are centred across ICBs every month, so the
                    # national walk is the common movement (G + u is otherwise not identified)
                    level = g + (level - level.mean(axis=0, keepdims=True))
            else:
                sa = pm.HalfNormal(f"sigma_a_{s}", 0.2)
                mub = pm.Normal(f"mu_b_{s}", 0, 0.05)
                sb = pm.HalfNormal(f"sigma_b_{s}", 0.05)
                if rung.centred:
                    a = pm.Normal(f"a_{s}", 0, sa, dims="icb")
                    b = pm.Normal(f"b_{s}", mub, sb, dims="icb")
                else:
                    a = pm.Deterministic(f"a_{s}", sa * pm.Normal(f"z_a_{s}", 0, 1, dims="icb"), dims="icb")
                    b = pm.Deterministic(f"b_{s}", mub + sb * pm.Normal(f"z_b_{s}", 0, 1, dims="icb"),
                                         dims="icb")
                level = a[:, None] + b[:, None] * X["tau"][None, :]
            if rung.month_effects:  # M2f-r3: calendar-aware stage 1, held fixed
                f = None
            elif rung.fixed_season:  # two-stage: seasonality fixed from stage 1, not a parameter
                f = pm.Data(f"f_{s}", seasonal_profile(d, s))
            else:
                f = pm.Normal(f"f_{s}", 0, 0.2, dims="k")
            if rung.month_effects:
                season = calendar_season(d, s, d.months)[None, :]
            elif rung.hier_season:   # M2b: ICB around region around national
                n_reg = int(d.region.max()) + 1
                s_reg = pm.HalfNormal(f"sigma_freg_{s}", 0.05)
                s_icb = pm.HalfNormal(f"sigma_ficb_{s}", 0.05)
                f_reg = f[None, :] + s_reg * pm.Normal(f"z_freg_{s}", 0, 1, shape=(n_reg, 2 * K))
                f_icb = pm.Deterministic(
                    f"f_icb_{s}", f_reg[d.region] + s_icb * pm.Normal(f"z_ficb_{s}", 0, 1, dims=("icb", "k")),
                    dims=("icb", "k"))
                season = pm.math.dot(f_icb, X["F"].T)                         # (icb, T)
            else:
                season = pm.math.dot(X["F"], f)[None, :]
            c = 0.0 if rung.rw_level else pm.Normal(f"c_covid_{s}", 0, 0.5)
            dd = pm.Normal(f"d_booked_{s}", 0, 0.3) if rung.booked_flag else 0.0
            if rung.struct_disp:   # M2c: dispersion by ICB and winter
                k0 = pm.HalfNormal(f"kappa_{s}", 0.1)
                s_k = pm.HalfNormal(f"sigma_kappa_{s}", 0.3)
                z_k = pm.Normal(f"z_kappa_{s}", 0, 1, dims="icb")
                omega = pm.Normal(f"omega_{s}", 0, 0.3)
                pm.Deterministic(f"lk_icb_{s}", pm.math.log(k0) + s_k * z_k, dims="icb")
                log_kappa = (pm.math.log(k0) + s_k * z_k)[:, None] + omega * X["winter"][None, :]
            elif rung.rw_level:    # boundary-avoiding: no degenerate zero-noise mode
                kappa = pm.Gamma(f"kappa_{s}", alpha=4.0, beta=200.0)             # mean 0.02
                log_kappa = None
            else:
                kappa = pm.HalfNormal(f"kappa_{s}", 0.1)
                log_kappa = None
            eta = (d.offset[s][:, None] + level + season + c * X["covid"][None, :]
                   + dd * X["booked"][None, :])
            yv = d.y[s]
            obs = ~np.isnan(yv)
            if s == "adm":
                obs &= ~np.isnan(d.y["type1"]) & (np.nan_to_num(d.y["type1"]) > 0)
                eta = eta + np.log(np.where(obs, d.y["type1"], 1.0))
                if rung.dyn_conversion:   # M2e: ICB winter term on the admission rate (centred)
                    om = pm.Normal("omega_conv", 0, 0.1)
                    s_om = pm.Gamma("sigma_omega_conv", alpha=4.0, beta=200.0)
                    om_i = pm.Normal("omega_conv_icb", om, s_om, dims="icb")
                    eta = eta + om_i[:, None] * X["winter"][None, :]
            ii, tt = np.nonzero(obs)
            alpha = (1.0 / kappa ** 2 if log_kappa is None
                     else pm.math.exp(-2.0 * log_kappa[ii, tt]))
            pm.NegativeBinomial(f"y_{s}", mu=pm.math.exp(eta[ii, tt]), alpha=alpha,
                                observed=yv[ii, tt])
    return model


def fit(model, draws: int = 1000, tune: int = 1000, chains: int = 4, seed: int = 0, cores: int = 4):
    import nutpie
    t0 = time.time()
    compiled = nutpie.compile_pymc_model(model)
    trace = nutpie.sample(compiled, draws=draws, tune=tune, chains=chains, seed=seed,
                          cores=cores, progress_bar=False)
    return trace, time.time() - t0


def _post(trace, name: str) -> np.ndarray:
    x = trace.posterior[name]
    return x.stack(sample=("chain", "draw")).transpose("sample", ...).to_numpy()


def _nb(rng, mu, alpha):
    mu = np.maximum(mu, 1e-9)
    return rng.negative_binomial(alpha, alpha / (alpha + mu)).astype(float)


def forecast(trace, d: M2Data, horizons=HORIZONS, quantiles=QUANTILES, seed: int = 0,
             rung: Rung = M2A) -> pd.DataFrame:
    """Posterior-predictive quantiles, harness contract with ``series`` = ICB code."""
    fut, targets = predictive_draws(trace, d, horizons, seed, rung)
    return _quantile_rows(targets, d.icbs, horizons, fut, quantiles)


def _quantile_rows(targets: dict, names, horizons, fut, quantiles) -> pd.DataFrame:
    rows = []
    for target, x in targets.items():
        q = np.quantile(x, quantiles, axis=0)                              # (Q, n, H)
        for i, name in enumerate(names):
            for j, h in enumerate(horizons):
                for k, lev in enumerate(quantiles):
                    rows.append((target, name, h, fut[j], lev, float(q[k, i, j])))
    return pd.DataFrame(rows, columns=["target", "series", "horizon", "period", "quantile", "value"])


def aggregate_forecast(targets: dict, d: M2Data, region_of: pd.Series, horizons, fut,
                       quantiles=QUANTILES) -> pd.DataFrame:
    """Region and England quantiles from ICB draws summed draw by draw (coherent)."""
    regions = region_of.reindex(d.icbs).fillna("?").to_numpy()
    names = sorted(set(regions))
    out = []
    for level, groups in (("region", names), ("england", ["ENGLAND"])):
        agg = {t: np.stack([x[:, (regions == g) if level == "region" else slice(None), :].sum(axis=1)
                            for g in groups], axis=1) for t, x in targets.items()}
        out.append(_quantile_rows(agg, groups, horizons, fut, quantiles).assign(level=level))
    return pd.concat(out, ignore_index=True)


def predictive_draws(trace, d: M2Data, horizons=HORIZONS, seed: int = 0, rung: Rung = M2A):
    """(future months, {target: draws (S, n_icb, H)}): one predictive draw per posterior draw."""
    rng = np.random.default_rng(seed)
    last = d.months[-1]
    fut = pd.DatetimeIndex([last + pd.DateOffset(months=h) for h in horizons])
    X = design(fut, last)
    sims = {}
    H = max(horizons)
    hidx = np.asarray(horizons) - 1
    for s in rung.series:
        if rung.rw_level and rung.fixed_season:   # zero-sum ICB walks + national walk
            Q = zero_sum_basis(len(d.icbs))
            v_last = _post(trace, f"v_{s}")[:, :, -1]                          # (S, n-1)
            srw = _post(trace, f"sigma_rw_{s}")
            v_steps = rng.standard_t(RW_NU, size=(len(srw), len(d.icbs) - 1, H)) * srw[:, None, None]
            v_path = v_last[:, :, None] + np.cumsum(v_steps, axis=2)[:, :, hidx]
            g_last = _post(trace, f"gnat_{s}")[:, 0, -1]
            sg = _post(trace, f"sigma_g_{s}")
            if rung.national_regime and COVID[0] <= last <= COVID[1]:   # regime assumed to persist
                sg = _post(trace, f"sigma_gc_{s}")
            g_steps = rng.standard_t(RW_NU, size=(len(sg), H)) * sg[:, None]
            level = (np.einsum("ij,sjh->sih", Q, v_path)
                     + (g_last[:, None] + np.cumsum(g_steps, axis=1)[:, hidx])[:, None, :])
        elif rung.rw_level:   # carry the last level forward with fresh Student-t innovations
            last_level = _post(trace, f"ell_{s}")[:, :, -1]                # (S, n_icb)
            srw = _post(trace, f"sigma_rw_{s}")
            if rung.rw_regime and COVID[0] <= last <= COVID[1]:   # regime assumed to persist
                srw = _post(trace, f"sigma_rwc_{s}")
            if rung.corr_innov:    # multivariate t: Gaussian copula + one shared χ² per draw/month
                chol = innovation_corr(_post(trace, f"ell_{s}").mean(axis=0))
                z = np.einsum("ij,sjh->sih", chol, rng.standard_normal((len(srw), len(d.icbs), H)))
                mix = np.sqrt(RW_NU / rng.chisquare(RW_NU, size=(len(srw), 1, H)))
                steps = z * mix * srw[:, None, None]
            else:
                steps = rng.standard_t(RW_NU, size=(len(srw), len(d.icbs), H)) * srw[:, None, None]
            if rung.shared_factor:   # ICB walks stay centred across ICBs, as in the model
                last_level = last_level - last_level.mean(axis=1, keepdims=True)
                steps = steps - steps.mean(axis=1, keepdims=True)
            level = last_level[:, :, None] + np.cumsum(steps, axis=2)[:, :, hidx]
            if rung.shared_factor:   # one national innovation per draw and month, shared by ICBs
                g_last = _post(trace, f"gnat_{s}")[:, 0, -1]
                sg = _post(trace, f"sigma_g_{s}")
                if rung.rw_regime and COVID[0] <= last <= COVID[1]:
                    sg = _post(trace, f"sigma_gc_{s}")
                g_steps = rng.standard_t(1.0 if rung.sparse_factor else RW_NU, size=(len(sg), H)) * sg[:, None]
                level = level + (g_last[:, None] + np.cumsum(g_steps, axis=1)[:, hidx])[:, None, :]
        else:
            a, b = _post(trace, f"a_{s}"), _post(trace, f"b_{s}")        # (S, n_icb)
            level = a[:, :, None] + b[:, :, None] * X["tau"][None, None, :]
        if rung.month_effects:
            season = calendar_season(d, s, fut)[None, None, :]
        elif rung.hier_season:
            season = np.einsum("sik,hk->sih", _post(trace, f"f_icb_{s}"), X["F"])   # (S, icb, H)
        elif rung.fixed_season:
            season = (seasonal_profile(d, s) @ X["F"].T)[None, None, :]
        else:
            season = (_post(trace, f"f_{s}") @ X["F"].T)[:, None, :]
        n_s = trace.posterior.sizes["chain"] * trace.posterior.sizes["draw"]
        dd = _post(trace, f"d_booked_{s}") if rung.booked_flag else np.zeros(n_s)   # (S,)
        c = np.zeros(n_s) if rung.rw_level else _post(trace, f"c_covid_{s}")
        if rung.struct_disp:
            lk = _post(trace, f"lk_icb_{s}")[:, :, None] + _post(trace, f"omega_{s}")[:, None, None] \
                * X["winter"][None, None, :]
            alpha = np.exp(-2.0 * lk)                                          # (S, icb, H)
        else:
            alpha = (1.0 / _post(trace, f"kappa_{s}") ** 2)[:, None, None]
        eta = (d.offset[s][None, :, None] + level
               + season + c[:, None, None] * X["covid"][None, None, :]
               + dd[:, None, None] * X["booked"][None, None, :])
        if s == "adm":
            eta = eta + np.log(np.maximum(sims["type1"], 1.0))
            if rung.dyn_conversion:
                eta = eta + _post(trace, "omega_conv_icb")[:, :, None] * X["winter"][None, None, :]
        sims[s] = _nb(rng, np.exp(eta), alpha)                             # (S, n_icb, H)
    targets = {"att_type1": sims["type1"],
               "att_all": sims["all"] if rung.direct_all else sims["type1"] + sims["other"],
               "adm_via_ae": sims["adm"]}
    return fut, targets


def diagnostics(trace, rung: Rung = M2A) -> dict:
    """R-hat and ESS over every sampled quantity except the non-centred z's; for random-walk
    levels, over the last 12 months (the ones a forecast starts from) to keep it fast."""
    import arviz as az
    post = trace.posterior
    ds = post.to_dataset() if hasattr(post, "to_dataset") else post
    ds = ds[[v for v in ds.data_vars if not v.startswith("z_")]]
    if "t" in ds.dims:
        ds = ds.isel(t=slice(-12, None))
    s = az.summary(ds)
    div = int(trace.sample_stats["diverging"].sum())
    return {"rhat_max": float(s["r_hat"].max()), "ess_bulk_min": float(s["ess_bulk"].min()),
            "ess_tail_min": float(s["ess_tail"].min()), "divergences": div,
            "worst_rhat_param": str(s["r_hat"].idxmax())}
