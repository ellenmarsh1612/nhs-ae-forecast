"""As-of loader, metrics, B0 baseline and the harness, all on synthetic data."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from nhs_ae.evaluate.asof import (
    LEVELS,
    as_of_date,
    last_period,
    load_asof,
    load_truth,
    slice_vintages,
)
from nhs_ae.evaluate.harness import BacktestConfig, run_backtest
from nhs_ae.evaluate.metrics import (
    mase_scale,
    paired_bootstrap,
    pinball,
    pit,
    score_rows,
    wis_interval_form,
)
from nhs_ae.features.hierarchy import UNMAPPED, current_region_map, normalise_region
from nhs_ae.ingest.recover import publication_date
from nhs_ae.models.base import QUANTILES
from nhs_ae.models.baselines import SeasonalNaive


# ---- synthetic vintage archive ---------------------------------------------------------
def make_vintages(months=40, providers=("RAA", "RBB", "RCC"), seed=0) -> pd.DataFrame:
    """Every month published once (second Thursday of the next month) and revised the
    following May/November; RCC never submits in month 10; values are invented."""
    rng = np.random.default_rng(seed)
    periods = pd.date_range("2016-04-01", periods=months, freq="MS")
    rows = []
    for i, p in enumerate(periods):
        pub = pd.Timestamp(publication_date(p.date()))
        nxt_rev = next(d for d in pd.date_range(pub, periods=13, freq="MS")
                       if d.month in (5, 11)) + pd.Timedelta(days=12)
        for j, org in enumerate(providers):
            if org == "RCC" and i == 10:
                continue
            season = 1 + 0.1 * np.sin(2 * np.pi * (p.month - 1) / 12)
            base = (1000 + 300 * j) * (1 + 0.005 * i) * season
            att1 = base + rng.normal(0, 10)
            for snap, bump in ((pub, 0.0), (nxt_rev, 5.0)):
                for metric, val in (("att_type1", att1 + bump), ("att_type2", 50.0),
                                    ("att_other", 200.0), ("adm_via_ae_type1", 0.3 * att1),
                                    ("adm_via_ae_type2", 1.0), ("adm_via_ae_other", 2.0)):
                    rows.append((p, org, "NHS England London" if j < 2 else "NHS ENGLAND MIDLANDS (WEST)",
                                 f"Trust {org}", metric, val, False, snap))
        # England total row (matches sum of published providers)
        for snap in (pub, nxt_rev):
            for metric in ("att_type1", "att_type2", "att_other", "adm_via_ae_type1",
                           "adm_via_ae_type2", "adm_via_ae_other"):
                tot = sum(r[5] for r in rows if r[0] == p and r[4] == metric and r[7] == snap and not r[6])
                rows.append((p, "-", "-", "England", metric, tot, True, snap))
    return pd.DataFrame(rows, columns=["period", "org_code", "parent_org", "org_name", "metric",
                                       "value", "is_total", "snapshot"])


@pytest.fixture(scope="module")
def vintages():
    v = make_vintages()
    v.loc[v["is_total"], "org_code"] = "ENGLAND"
    return v


# ---- hierarchy --------------------------------------------------------------------------
def test_normalise_region():
    assert normalise_region("NHS England Midlands (West Midlands)") == "MIDLANDS"
    assert normalise_region("NHS ENGLAND NORTH EAST AND YORKSHIRE") == "NORTH EAST AND YORKSHIRE"
    assert normalise_region("London Commissioning Region") == "LEGACY"
    assert normalise_region(None) == "LEGACY"


def test_current_region_map(vintages):
    m = current_region_map(vintages)
    assert m["RAA"] == "LONDON" and m["RCC"] == "MIDLANDS" and "ENGLAND" not in m.index


# ---- as-of loader -----------------------------------------------------------------------
def test_origin_conventions():
    assert as_of_date(date(2026, 10, 1)) == pd.Timestamp("2026-10-08")   # second Thursday
    assert last_period(date(2026, 10, 1)) == pd.Timestamp("2026-09-01")


def test_asof_vs_final_and_missing_provider(vintages):
    origin = date(2017, 3, 1)               # sees periods to 2017-02; Feb 2017 not yet revised
    asof = load_asof(origin, "asof", vintages)
    final = load_asof(origin, "final", vintages)
    assert asof.last_period == final.last_period == pd.Timestamp("2017-02-01")
    pa, pf = asof.panel("att_type1", "provider"), final.panel("att_type1", "provider")
    assert pa.shape == pf.shape and list(pa.columns) == ["RAA", "RBB", "RCC"]
    # the most recent months are unrevised in as-of mode, revised (+5) in final mode
    assert pf.loc["2017-02-01", "RAA"] - pa.loc["2017-02-01", "RAA"] == pytest.approx(5.0)
    # a month long since revised is identical in both modes
    assert pf.loc["2016-04-01", "RAA"] == pa.loc["2016-04-01", "RAA"]
    # RCC did not submit for month index 10 (2017-02): NaN, not zero, and no row was invented
    assert np.isnan(pa.loc["2017-02-01", "RCC"]) and np.isnan(pf.loc["2017-02-01", "RCC"])
    assert pa.isna().sum().sum() == 1
    # england level comes from the published total row; region level sums providers
    e = asof.panel("att_type1", "england")
    assert list(e.columns) == ["ENGLAND"] and e.loc["2016-04-01", "ENGLAND"] == pytest.approx(pa.loc["2016-04-01"].sum())
    r = asof.panel("att_type1", "region")
    assert set(r.columns) == {"LONDON", "MIDLANDS"}
    assert r.loc["2016-04-01", "LONDON"] == pytest.approx(pa.loc["2016-04-01", ["RAA", "RBB"]].sum())
    # targets are sums of components; all-or-nothing
    t = asof.targets
    row = t[(t.period == "2016-04-01") & (t.org_code == "RAA")].set_index("target")["value"]
    assert row["att_all"] == pytest.approx(row["att_type1"] + 250)
    assert row["adm_via_ae"] == pytest.approx(0.3 * (row["att_type1"] - 5) + 3)  # adm built from unrevised att


def test_icb_level_is_opt_in_and_sums_providers(vintages):
    assert "icb" not in LEVELS                          # default backtests are unchanged
    icb_map = pd.Series({"RAA": "QAA", "RBB": "QAA"})
    asof = load_asof(date(2017, 3, 1), "asof", vintages, icb_map=icb_map)
    p, prov = asof.panel("att_type1", "icb"), asof.panel("att_type1", "provider")
    assert list(p.columns) == ["QAA", UNMAPPED]         # RCC is in no ICB
    assert p.loc["2016-04-01", "QAA"] == pytest.approx(prov.loc["2016-04-01", ["RAA", "RBB"]].sum())
    # RCC alone in its bucket and absent in 2017-02: NaN (min_count=1), never an invented zero
    assert np.isnan(p.loc["2017-02-01", UNMAPPED])
    with pytest.raises(ValueError, match="icb"):
        asof.panel("att_type1", "stp")


def test_icb_level_through_the_harness(vintages, monkeypatch):
    """Requested explicitly, the icb level runs end to end on the default reference table
    (here a synthetic one), with no ICB map passed through the harness."""
    import nhs_ae.ingest.icb_mapping as im
    ref = pd.DataFrame({"org_code": ["raa", "RBB", "RCC"], "icb_code": ["QAA", "QAA", "QBB"]})
    monkeypatch.setattr(im, "load_reference", lambda *a, **k: ref)
    cfg = BacktestConfig(origins=[date(2018, 9, 1)], levels=("icb", "england"),
                         targets=("att_type1",), horizons=(1, 2))
    forecasts, scores, _ = run_backtest([SeasonalNaive()], vintages, cfg)
    assert set(forecasts.loc[forecasts["level"] == "icb", "series"]) == {"QAA", "QBB"}
    icb_scores = scores[scores["level"] == "icb"]
    assert len(icb_scores) == 2 * 2 * 2 and icb_scores["y"].notna().all()   # series x h x mode


def test_unavailable_latest_period_shortens_training(vintages):
    """If the newest month has no archived version at the origin, training ends earlier."""
    v = vintages[~((vintages["period"] == "2017-02-01") & (vintages["snapshot"] < "2017-05-01"))]
    asof = load_asof(date(2017, 3, 1), "asof", v)        # Feb 2017 only exists as a May revision
    assert asof.last_period == pd.Timestamp("2017-01-01")
    assert asof.panel("att_type1", "provider").index[-1] == pd.Timestamp("2017-01-01")
    final = load_asof(date(2017, 3, 1), "final", v)      # final mode still sees the revision
    assert final.last_period == pd.Timestamp("2017-02-01")


def test_slice_vintages_picks_latest_available(vintages):
    s = slice_vintages(vintages, pd.Timestamp("2016-06-01"), None)
    assert s["period"].max() == pd.Timestamp("2016-04-01")   # May data not out until 9 June
    truth = load_truth(vintages)
    assert truth.panel("att_type1", "provider").index[-1] == vintages["period"].max()


# ---- metrics ----------------------------------------------------------------------------
def _scored_frame():
    rng = np.random.default_rng(1)
    rows = []
    for i in range(200):
        centre = 100 + rng.normal(0, 5)
        q = {t: centre + 20 * (t - 0.5) for t in QUANTILES}
        rows.append({**q, "y": 100 + rng.normal(0, 6), "series": f"S{i % 10}", "scale": 4.0})
    return pd.DataFrame(rows)


def test_pinball_and_wis_identity():
    assert pinball(np.array([10.0]), np.array([8.0]), 0.9)[0] == pytest.approx(1.8)
    assert pinball(np.array([10.0]), np.array([12.0]), 0.9)[0] == pytest.approx(0.2)
    f = _scored_frame()
    s = score_rows(f)
    np.testing.assert_allclose(s["wis"], wis_interval_form(f), rtol=1e-9)
    assert (s["mase"] == s["abs_err"] / 4.0).all()
    z = score_rows(f.assign(scale=0.0))
    assert z["mase"].isna().all() and (z["wis"] == s["wis"]).all()   # constant series: no MASE
    assert 0.3 < s["cov50"].mean() < 0.7 and 0.6 < s["cov90"].mean() <= 1.0


def test_pit_bounds_and_monotone():
    f = _scored_frame().iloc[:1].copy()
    lo = f.assign(y=f[0.025] - 1)
    hi = f.assign(y=f[0.975] + 1)
    mid = f.assign(y=f[0.5])
    assert pit(lo)[0] == 0.0 and pit(hi)[0] == 1.0 and pit(mid)[0] == pytest.approx(0.5)


def test_mase_scale():
    idx = pd.date_range("2020-01-01", periods=26, freq="MS")
    p = pd.DataFrame({"a": np.arange(26.0), "b": [np.nan] * 26}, index=idx)
    s = mase_scale(p)
    assert s["a"] == pytest.approx(12.0) and np.isnan(s["b"])


def test_paired_bootstrap_identical_models_gives_zero():
    f = _scored_frame()
    s = score_rows(f)
    s["origin"], s["horizon"], s["period"] = 1, 1, np.arange(len(s))
    r = paired_bootstrap(s, s)
    assert r["diff"] == 0 and r["diff_lo"] == 0 == r["diff_hi"] and r["n_units"] == 10


# ---- B0 ---------------------------------------------------------------------------------
def test_seasonal_naive_point_and_quantiles():
    idx = pd.date_range("2015-04-01", periods=48, freq="MS")
    season = 1 + 0.2 * np.sin(2 * np.pi * (idx.month - 1) / 12)
    y = pd.DataFrame({"a": 1000 * (1.05 ** (np.arange(48) / 12)) * season}, index=idx)
    y["b"] = np.nan                                  # never observed
    fc = SeasonalNaive().fit_predict(y, horizons=(1, 3), quantiles=QUANTILES)
    assert set(fc.columns) == {"series", "horizon", "period", "quantile", "value"}
    a1 = fc[(fc.series == "a") & (fc.horizon == 1)].set_index("quantile")["value"]
    growth = y["a"].iloc[-12:].sum() / y["a"].iloc[-24:-12].sum()
    model = SeasonalNaive()
    assert model.point(y, len(y) - 1, 1)["a"] == pytest.approx(y["a"].iloc[-12] * growth, rel=1e-9)
    assert np.isnan(model.point(y, len(y) - 1, 1)["b"])
    assert a1.is_monotonic_increasing
    # the rule under-forecasts a growing series, so its own residuals shift the median up
    assert a1[0.5] > model.point(y, len(y) - 1, 1)["a"]
    assert fc[(fc.series == "a") & (fc.horizon == 3)]["period"].iloc[0] == idx[-1] + pd.DateOffset(months=3)
    assert fc[fc.series == "b"]["value"].isna().all()


# ---- harness ----------------------------------------------------------------------------
def test_run_backtest_end_to_end(vintages):
    cfg = BacktestConfig(origins=[date(2018, 9, 1), date(2018, 10, 1)], levels=("provider", "england"),
                         targets=("att_type1",), horizons=(1, 2, 3))
    forecasts, scores, info = run_backtest([SeasonalNaive()], vintages, cfg)
    assert info["origins"] == 2 and len(forecasts) > 0
    assert set(forecasts["mode"]) == {"asof", "final"} and set(forecasts["level"]) == {"provider", "england"}
    assert forecasts["period"].min() == pd.Timestamp("2018-09-01")   # origin Sep sees Aug, h=1 -> Sep
    assert {"wis", "mase", "cov90", "pit", "winter", "y", "scale"} <= set(scores.columns)
    # every scored row has a full quantile set and an outturn
    assert scores[[c for c in scores.columns if isinstance(c, float)]].notna().all().all()
    assert scores["y"].notna().all()
    # as-of and final forecasts differ at the newest months only through revisions
    a = scores[(scores["mode"] == "asof")].set_index(["series", "origin", "horizon", "level"])["wis"]
    f = scores[(scores["mode"] == "final")].set_index(["series", "origin", "horizon", "level"])["wis"]
    assert len(a) == len(f) and not np.allclose(a.sort_index(), f.sort_index())


# ---- revision audit ---------------------------------------------------------------------
def test_revision_audit_and_training_leakage(vintages):
    from nhs_ae.evaluate.audit import revision_audit, training_leakage
    a = revision_audit(vintages)
    row = a[(a.period == "2016-04-01") & (a.measure == "att_type1")].iloc[0]
    assert row.n_versions == 2 and row.providers_changed == 3 and row.late_submitters == 0
    assert row.national_latest - row.national_first == pytest.approx(15.0)   # +5 per provider
    assert row.max_abs_change == pytest.approx(5.0)
    adm = a[(a.period == "2016-04-01") & (a.measure == "adm_via_ae")].iloc[0]
    assert adm.providers_changed == 0 and adm.national_rel_change == 0
    gap = a[(a.period == "2017-02-01") & (a.measure == "att_type1")].iloc[0]
    assert gap.providers_first == 2 == gap.providers_latest                    # RCC absent in both
    # at a March 2017 origin the last ~10 months are unrevised: most provider-months differ
    lk = training_leakage(vintages, [date(2017, 3, 1)])
    r = lk[lk.measure == "att_type1"].iloc[0]
    assert r.provider_months > 0 and 0.3 < r.share_changed < 0.6 and r.only_in_final == 0  # 5 of 12 months unrevised
    assert 0 < r.mean_abs_rel_diff < 0.01
