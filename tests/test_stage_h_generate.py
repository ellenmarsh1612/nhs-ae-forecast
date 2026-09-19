"""Stage H step 3 (design §2.1, §2.9, §4, §8) on synthetic data with stub forecasters.

Generation runs in real spawn workers (jobs=2), so the worker tripwires, the run's vintage path
in every pool's initargs and the worker hash are exercised where they matter. Values are
invented; calendar dates are real. Nothing reads an outturn or any real data file.
"""

from __future__ import annotations

import importlib
import inspect
import os
import subprocess
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from nhs_ae.calibrate import online
from nhs_ae.evaluate import asof, harness, splits, stage_e, stage_f
from nhs_ae.evaluate.stage_h import common
from nhs_ae.evaluate.stage_h import generate as gen
from nhs_ae.evaluate.stage_h.common import (
    CONF21,
    D7_FOLD,
    DEV_SIDE_KEYS,
    HASH_FILES,
    NAMES,
    P5_INPUTS,
    Context,
    file_sha,
    ts,
)
from nhs_ae.ingest.recover import publication_date
from nhs_ae.models import m2
from nhs_ae.models.base import HORIZONS, QUANTILES, Forecaster, quantile_frame, target_periods

PROVIDERS = ("RJ1", "RJZ", "RAL")      # real codes, so ICBs (QKK, Z9B2Z) and a region form
ORIGINS = (date(2019, 10, 1), date(2019, 11, 1))
GAP = pd.Timestamp("2019-10-01")       # published only at its revision: as-of 2019-11 is truncated
TARGETS = ("att_all", "att_type1", "adm_via_ae")
METRICS = {"att_type1": 1.0, "att_type2": 0.05, "att_other": 0.2, "adm_via_ae_type1": 0.3,
           "adm_via_ae_type2": 0.001, "adm_via_ae_other": 0.002}


def synthetic_vintages(end: str = "2020-06-01", seed: int = 0) -> pd.DataFrame:
    """Invented values from 2016-04: each period published on its second Thursday and revised
    (+5) three months later, except ``GAP``, which first appears at its revision."""
    rng = np.random.default_rng(seed)
    rows = []
    for i, p in enumerate(pd.date_range("2016-04-01", end, freq="MS")):
        pub = pd.Timestamp(publication_date(p.date()))
        season = 1 + 0.1 * np.sin(2 * np.pi * p.month / 12)
        att1 = {org: (1000 + 300 * j) * (1 + 0.005 * i) * season + rng.normal(0, 10)
                for j, org in enumerate(PROVIDERS)}
        for snap, bump in ((pub, 0.0), (pub + pd.DateOffset(months=3), 5.0)):
            if p == GAP and not bump:
                continue
            for metric, share in METRICS.items():
                vals = {org: share * (a + bump) for org, a in att1.items()}
                rows += [(p, org, "NHS England London", f"Trust {org}", metric, v, False, snap)
                         for org, v in vals.items()]
                rows.append((p, "-", "-", "England", metric, sum(vals.values()), True, snap))
    return pd.DataFrame(rows, columns=["period", "org_code", "parent_org", "org_name", "metric",
                                       "value", "is_total", "snapshot"])


# ---- stub forecasters (module level, so spawn workers can unpickle them) -------------------
class Flat(Forecaster):
    """The last observed value times a fixed spread: a well-formed forecast."""
    name = "stub_flat"

    def fit_predict(self, panel, horizons=HORIZONS, quantiles=QUANTILES):
        periods, last = target_periods(panel, horizons), panel.ffill().iloc[-1]
        return quantile_frame({(s, h, periods[h]): {q: float(last[s]) * (0.8 + 0.4 * q)
                                                    for q in quantiles}
                               for s in panel.columns for h in horizons})


class Defects(Flat):
    """Flat, except the first series: h1 NaN, h2 a negative quantile, h3 crossed, h4 all zero."""
    name = "stub_defects"

    def fit_predict(self, panel, horizons=HORIZONS, quantiles=QUANTILES):
        fc = super().fit_predict(panel, horizons, quantiles)
        first = fc["series"] == panel.columns[0]
        fc.loc[first & (fc["horizon"] == 1), "value"] = np.nan
        fc.loc[first & (fc["horizon"] == 2) & (fc["quantile"] == QUANTILES[0]), "value"] = -1.0
        fc.loc[first & (fc["horizon"] == 3) & (fc["quantile"] == QUANTILES[-1]), "value"] = 0.5
        fc.loc[first & (fc["horizon"] == 4), "value"] = 0.0
        return fc


class B0(Flat):
    name = "stub_b0"


class B1(Flat):
    name = "stub_b1"


class B2(Flat):
    name = "stub_b2"


class M1(Flat):
    name = "stub_m1"


class M1Raw(Flat):
    name = "stub_m1_v3_raw"


STUBS = {"flat": Flat, "defects": Defects, "b0": B0, "b1": B1, "b2": B2, "m1": M1,
         "m1_v3_raw": M1Raw}

FORBIDDEN = [(f"nhs_ae.{m}", a) for m, attrs in (
    ("evaluate.asof", ("load_truth",)),
    ("evaluate.harness", ("load_truth", "truth_long", "score_forecasts", "score_rows")),
    ("evaluate.metrics", ("score_rows",)),
    ("evaluate.splits", ("assert_not_sealed",)),
    ("evaluate.stage_e", ("icb_truth", "agg_truth", "load_truth")),
    ("evaluate.stage_f", ("truth_all", "_median_errors", "calibrate")),
    ("calibrate.online", ("first_release", "calibrate")),
    ("calibrate.g1", ("last_observed",)),
    ("evaluate.audit", ("revision_audit", "training_leakage"))) for a in attrs]
FORBIDDEN.append(("matplotlib.figure", "Figure"))


def _trips(module: str, attr: str) -> bool:
    try:
        getattr(importlib.import_module(module), attr)()
    except gen.SealTripwire:
        return True
    except Exception:  # noqa: BLE001 - an untripped function fails on the missing arguments
        return False
    return False


class Probe(Flat):
    """Calls every forbidden function inside its worker; its forecasts carry how many raised."""
    name = "stub_probe"

    def fit_predict(self, panel, horizons=HORIZONS, quantiles=QUANTILES):
        fired = sum(_trips(m, a) for m, a in FORBIDDEN)
        return super().fit_predict(panel, horizons, quantiles).assign(value=float(fired))


class CallsTruth(Flat):
    name = "stub_calls_truth"

    def fit_predict(self, panel, horizons=HORIZONS, quantiles=QUANTILES):
        asof.load_truth(None)
        return super().fit_predict(panel, horizons, quantiles)


# ---- stub M2 fits (stage_e._fit_origin's signature and output) -----------------------------
def _m2_forecast(args, shift):
    origin = args[0]
    if tuple(args[1:]) != (m2.M2D_CORR, 1000, 1000, 4):
        raise AssertionError(f"not the frozen settings: {args[1:]}")
    p = stage_e.panels_at(origin, stage_e._W["v"])["att_type1"]
    icbs = [c for c in p.columns if c not in m2.EXCLUDE]
    regions = sorted(set(stage_e._W["regions"].reindex(icbs).fillna("?")))   # as aggregate_forecast
    rows = [(t, s, h, p.index[-1] + pd.DateOffset(months=h), q, 100.0 + shift + q, lv)
            for lv, names in (("icb", icbs), ("region", regions), ("england", ["ENGLAND"]))
            for t in TARGETS for s in names for h in HORIZONS for q in QUANTILES]
    fc = pd.DataFrame(rows, columns=["target", "series", "horizon", "period", "quantile", "value",
                                     "level"])
    fc["origin"] = pd.Timestamp(origin)
    diag = {"origin": pd.Timestamp(origin), "rung": "m2d_corr", "shift": shift, "seconds": 0.0,
            "rhat_max": 1.01, "ess_bulk_min": 400.0, "ess_tail_min": 380.0, "divergences": 0,
            "worst_rhat_param": "sigma_rw"}
    return fc, diag


def fit_ok(args, shift=0):
    return _m2_forecast(args, shift)


def fit_fails_first(args, shift=0):
    if shift == 0:
        raise RuntimeError("sampler failed\nstarting values: {'sigma_rw': 0.1}")
    return _m2_forecast(args, shift)


def fit_second_origin_fails(args, shift=0):
    if args[0] == ORIGINS[1]:
        raise ValueError("no convergence")
    return _m2_forecast(args, shift)


def fit_kills_worker(args, shift=0):
    os._exit(1)


def fit_interrupted(args, shift=0):
    raise KeyboardInterrupt


def fit_calls_calibrate(args, shift=0):
    online.calibrate(None, None)


def fit_without_shift(args):
    return _m2_forecast(args, 0)


def fit_ignores_shift(args, shift=0):
    return _m2_forecast(args, 0)                    # takes a shift, keeps the frozen seeds


def fit_drops_an_icb(args, shift=0):
    fc, diag = _m2_forecast(args, shift)
    last = fc.loc[fc["level"] == "icb", "series"].max()
    return fc[fc["series"] != last], diag


# ---- fixtures ------------------------------------------------------------------------------
def _ctx(tmp: Path, vpath: Path, mode: str = "dry", origins=ORIGINS) -> Context:
    return Context(mode, tuple(origins), tuple(origins), {}, max(origins), tmp / "work",
                   tmp / "results", vpath, 2)


@pytest.fixture(scope="module")
def vpath(tmp_path_factory):
    path = tmp_path_factory.mktemp("vintages") / "ae_monthly_all_vintages.parquet"
    synthetic_vintages().to_parquet(path, index=False)
    return path


@pytest.fixture(scope="module")
def run(tmp_path_factory, vpath):
    """Provider (both modes) and ICB forecasts of two stubs, the aggregates and M2 with a first
    attempt that fails at every origin; every pool created through a spy."""
    ctx = _ctx(tmp_path_factory.mktemp("step3"), vpath)
    seen = []

    class Spy(ProcessPoolExecutor):
        def __init__(self, *args, **kwargs):
            seen.append(kwargs["initargs"])
            super().__init__(*args, **kwargs)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(gen, "ProcessPoolExecutor", Spy)
        mp.setattr(gen, "MODELS", STUBS)
        mp.setattr(stage_e, "_fit_origin", fit_fails_first)
        files = gen.harness_block(ctx, ("flat", "defects"), "provider", ("asof", "final"), ORIGINS)
        files |= gen.harness_block(ctx, ("flat", "defects"), "icb", ("asof",), ORIGINS)
        files |= gen.aggregate_block(ctx, ORIGINS)
        path, fits = gen.fit_m2(ctx, ORIGINS)
    files[("m2", "all", "asof")] = path
    return {"ctx": ctx, "files": files, "fits": fits, "initargs": seen,
            "qa": gen.qa(files, ctx, fits)}


# ---- pools, files, QA, hashes --------------------------------------------------------------
def test_every_pool_loads_the_run_vintage_table(run):
    ctx = run["ctx"]
    assert len(run["initargs"]) == 4                         # provider, ICB, aggregates, M2
    assert all(Path(a[0]) == ctx.vintages_path for a in run["initargs"])
    assert set(run["files"]) == {
        *((k, "provider", m) for k in ("flat", "defects") for m in ("asof", "final")),
        *((k, "icb", "asof") for k in ("flat", "defects")),
        *((k, lv, "asof") for k in ("b1", "b2", "m1_v3_raw") for lv in ("region", "england")),
        ("m2", "all", "asof")}
    for path in run["files"].values():
        assert path.parent == ctx.work / "forecasts"
        assert list(pd.read_parquet(path).columns) == gen.COLS
    with (pytest.raises(ValueError, match="vintage table"),        # a pool on any other table
          gen._pool(ctx, 1, gen._m2_init, (ctx.work / "other.parquet",))):
        pass


def test_qa_counts_nan_negative_crossed_and_all_zero_forecasts(run):
    t = run["qa"]
    prov = t[t["level"] == "provider"]
    assert len(prov) == 2 * 2 * 2 * 3                         # models x origins x modes x targets
    for model, n in (("defects", 1), ("flat", 0)):
        g = t[(t["model_key"] == model)]
        for col in ("nan_rows", "negative_rows", "crossed_rows", "all_zero_rows"):
            assert (g[col] == n).all(), (model, col)
    assert (t.loc[t["model_key"].isin(["b1", "b2", "m1_v3_raw", "m2"]), "nan_rows"] == 0).all()
    assert t["grid_ok"].all() and (t["duplicate_rows"] == 0).all() and (t["incomplete"] == 0).all()
    assert not t["absent"].any() and not t["absent_by_rule"].any()
    series = t.groupby("level")["series"].unique().map(set).to_dict()
    assert series == {"provider": {3}, "icb": {2}, "region": {1}, "england": {1}}
    assert (t["expected_series"] == t["series"]).all()               # M2's sets too
    assert (t["missing_series"] == 0).all() and (t["extra_series"] == 0).all()
    assert t.loc[t["model_key"] != "m2", "keys_match"].astype(bool).all()
    assert t.loc[t["model_key"] == "m2", "keys_match"].isna().all()
    assert len(t[t["model_key"] == "m2"]) == 2 * 3 * 3                # origins x levels x targets


def test_horizon_period_rule_uses_the_asof_end_month(run):
    t = run["qa"]
    assert t["period_ok"].all() and (t["bad_periods"] == 0).all()
    end = t.groupby(["origin", "mode"])["end_month"].unique().map(set).to_dict()
    sep, oct_ = pd.Timestamp("2019-09-01"), pd.Timestamp("2019-10-01")
    assert end == {(ts(ORIGINS[0]), "asof"): {sep}, (ts(ORIGINS[0]), "final"): {sep},
                   (ts(ORIGINS[1]), "asof"): {sep},              # truncated: 2019-10 not yet out
                   (ts(ORIGINS[1]), "final"): {oct_}}


def test_qa_flags_a_nominal_period_and_a_missing_series(run, tmp_path):
    files, ctx = run["files"], run["ctx"]
    f = pd.read_parquet(files["flat", "provider", "asof"])
    late = f["origin"] == ts(ORIGINS[1])
    f.loc[late, "period"] = f.loc[late, "period"] + pd.DateOffset(months=1)   # nominal end month
    d = pd.read_parquet(files["defects", "provider", "asof"])
    bad = {("flat", "provider", "asof"): tmp_path / "flat.parquet",
           ("defects", "provider", "asof"): tmp_path / "defects.parquet"}
    f.to_parquet(bad["flat", "provider", "asof"], index=False)
    d[d["series"] != "RJZ"].to_parquet(bad["defects", "provider", "asof"], index=False)
    t = gen.qa(bad, ctx)
    ft, dt = t[t["model_key"] == "flat"], t[t["model_key"] == "defects"]
    wrong = ft[ft["origin"] == ts(ORIGINS[1])]
    assert not wrong["period_ok"].any() and (wrong["bad_periods"] == wrong["forecasts"]).all()
    assert ft.loc[ft["origin"] == ts(ORIGINS[0]), "period_ok"].all()
    assert (dt["missing_series"] == 1).all() and not dt["keys_match"].astype(bool).any()


def test_qa_lists_the_cells_a_harness_model_owed_and_did_not_forecast(run, tmp_path):
    files, ctx = run["files"], run["ctx"]
    f = pd.read_parquet(files["flat", "provider", "asof"])
    cut = (f["origin"] == ts(ORIGINS[1])) & (f["target"] == "adm_via_ae")
    f[~cut].to_parquet(tmp_path / "flat.parquet", index=False)
    t = gen.qa({("flat", "provider", "asof"): tmp_path / "flat.parquet",
                ("defects", "provider", "asof"): files["defects", "provider", "asof"]}, ctx)
    assert len(t) == 2 * 2 * 3                                     # the absent cell has its row
    gone = t[t["absent"]].iloc[0]
    assert t["absent"].sum() == 1 and (gone["model_key"], gone["target"]) == ("flat", "adm_via_ae")
    assert gone["missing_series"] == gone["expected_series"] == 3 and gone["rows"] == 0
    assert not gone["grid_ok"] and gone["end_month"] == pd.Timestamp("2019-09-01")
    cell = (t["origin"] == ts(ORIGINS[1])) & (t["target"] == "adm_via_ae")
    assert not t.loc[cell, "keys_match"].astype(bool).any()        # defects' keys now differ too
    assert t.loc[~cell, "keys_match"].astype(bool).all()
    pd.DataFrame(columns=gen.COLS).to_parquet(tmp_path / "empty.parquet", index=False)
    e = gen.qa({("flat", "provider", "final"): tmp_path / "empty.parquet"}, ctx)
    assert len(e) == 2 * 3 and e["absent"].all() and (e["mode"] == "final").all()
    assert (e["missing_series"] == 3).all() and not e["keys_match"].astype(bool).any()


def test_forecast_hashes_are_stable_under_row_order(run, tmp_path):
    src = run["files"]["defects", "provider", "asof"]
    f = pd.read_parquet(src)
    f.sample(frac=1, random_state=0).to_parquet(tmp_path / "shuffled.parquet", index=False)
    g = f.copy()
    g.loc[g["value"].first_valid_index(), "value"] += 1.0
    g.to_parquet(tmp_path / "changed.parquet", index=False)
    h = gen.forecast_hashes({("a", "provider", "asof"): src,
                             ("b", "provider", "asof"): tmp_path / "shuffled.parquet",
                             ("c", "provider", "asof"): tmp_path / "changed.parquet"})
    assert {"file", "sha256", "row_hash", "rows", "origins"} <= set(h.columns)
    assert h.loc[0, "row_hash"] == h.loc[1, "row_hash"] != h.loc[2, "row_hash"]
    assert h.loc[0, "sha256"] != h.loc[1, "sha256"]
    assert h.loc[0, "rows"] == len(f) and h.loc[0, "origins"] == "2019-10;2019-11"


# ---- M2 fit policy -------------------------------------------------------------------------
def test_m2_retries_once_with_both_seeds_shifted(run):
    fits = run["fits"]
    attempts = fits[["attempt", "shift", "failed"]].values.tolist()
    assert attempts == [[0, 0, True], [1, 1000, False]] * 2
    assert (fits.loc[fits["failed"], "error"] == "RuntimeError: sampler failed").all()   # 1st line
    assert fits["fit_seed"].tolist() == [201910, 202910, 201911, 202911]     # year*100+month(+1000)
    assert fits["pred_seed"].tolist() == [10, 1010, 11, 1011]                  # month (+1000)
    ok = fits.loc[~fits["failed"]]
    assert (ok["rhat_max"] == 1.01).all() and (ok["ess_tail_min"] == 380.0).all()
    fc = pd.read_parquet(run["files"]["m2", "all", "asof"])
    assert set(fc["level"]) == {"icb", "region", "england"} and set(fc["model"]) == {"m2d_corr"}
    assert set(fc["origin"]) == {ts(o) for o in ORIGINS}
    assert (fc["value"] > 1000).all()                                # every row from the retry


def test_fit_origin_shift_moves_both_seeds_and_zero_keeps_them(monkeypatch):
    seen = {}

    def draws(trace, d, horizons, seed, rung):
        seen["pred"] = seed
        return [pd.Timestamp("2019-10-01")] * len(horizons), {}

    monkeypatch.setattr(stage_e, "_W", {"v": None, "regions": pd.Series(dtype=str)})
    monkeypatch.setattr(stage_e, "panels_at", lambda origin, v: {})
    monkeypatch.setattr(m2, "prepare", lambda panels, region_of, clean: SimpleNamespace(icbs=["I1"]))
    monkeypatch.setattr(m2, "build_model", lambda d, rung: "model")
    monkeypatch.setattr(m2, "fit", lambda model, draws, tune, cores, seed: (seen.update(fit=seed), 1.0))
    monkeypatch.setattr(m2, "diagnostics", lambda trace, rung: {"rhat_max": 1.0})
    monkeypatch.setattr(m2, "predictive_draws", draws)
    monkeypatch.setattr(m2, "_quantile_rows", lambda *a: pd.DataFrame({"series": ["I1"]}))
    monkeypatch.setattr(m2, "aggregate_forecast", lambda *a: pd.DataFrame({"series": ["R1"]}))
    args = (date(2019, 10, 1), m2.M2D_CORR, 10, 10, 1)
    stage_e._fit_origin(args)                                         # as run_rung calls it
    assert seen == {"fit": 201910, "pred": 10}
    _, diag = stage_e._fit_origin(args, shift=1000)
    assert seen == {"fit": 202910, "pred": 1010} and diag["shift"] == 1000


def test_m2_second_failure_leaves_the_origin_out_and_force_retry(vpath, tmp_path, monkeypatch):
    monkeypatch.setattr(stage_e, "_fit_origin", fit_second_origin_fails)
    ctx = _ctx(tmp_path, vpath)
    path, fits = gen.fit_m2(ctx, ORIGINS, force_retry={ORIGINS[0]})
    first, second = fits[fits["origin"] == ts(ORIGINS[0])], fits[fits["origin"] == ts(ORIGINS[1])]
    assert first["failed"].tolist() == [True, False] and "on purpose" in first["error"].iloc[0]
    assert second["failed"].tolist() == [True, True] and second["shift"].tolist() == [0, 1000]
    assert second["error"].str.startswith("ValueError: no convergence").all()
    fc = pd.read_parquet(path)
    assert set(fc["origin"]) == {ts(ORIGINS[0])} and (fc["value"] > 1000).all()
    files = {("m2", "all", "asof"): path}
    unknown = gen.qa(files, ctx)                                    # no fits table: not by rule
    gone = unknown[unknown["absent"]]
    assert len(gone) == 3 * 3 and set(gone["origin"]) == {ts(ORIGINS[1])}   # levels x targets
    assert set(gone["level"]) == {"icb", "region", "england"} and (gone["model"] == "m2d_corr").all()
    assert (gone["missing_series"] == gone["expected_series"]).all() and not gone["grid_ok"].any()
    assert not unknown["absent_by_rule"].any()
    fits.to_csv(ctx.work / "m2_fits.csv", index=False)              # as generate writes it
    for t in (gen.qa(files, ctx, fits), gen.qa(files, ctx)):
        assert t["absent_by_rule"].equals(t["absent"]) and t["absent"].sum() == 9


def test_qa_holds_m2_to_the_series_its_fit_owes(vpath, tmp_path, monkeypatch):
    monkeypatch.setattr(stage_e, "_fit_origin", fit_drops_an_icb)
    ctx = _ctx(tmp_path, vpath)
    path, _ = gen.fit_m2(ctx, ORIGINS)
    t = gen.qa({("m2", "all", "asof"): path}, ctx)
    assert len(t) == 2 * 3 * 3 and not t["absent"].any()             # origins x levels x targets
    icb, agg = t[t["level"] == "icb"], t[t["level"] != "icb"]
    assert (icb["expected_series"] == 2).all() and (icb["missing_series"] == 1).all()
    assert (agg["missing_series"] == 0).all() and (t["extra_series"] == 0).all()


def test_force_retry_is_for_the_dry_run_only(vpath, tmp_path):
    with pytest.raises(ValueError, match="dry run"):
        gen.fit_m2(_ctx(tmp_path, vpath, mode="run"), ORIGINS, force_retry={ORIGINS[0]})


@pytest.mark.parametrize("fit, crash", [(fit_kills_worker, BrokenProcessPool),
                                        (fit_interrupted, KeyboardInterrupt)])
def test_a_broken_pool_or_an_interrupt_is_a_crash_not_a_fit_failure(fit, crash, vpath, tmp_path,
                                                                    monkeypatch):
    monkeypatch.setattr(stage_e, "_fit_origin", fit)
    ctx, omp = _ctx(tmp_path, vpath), os.environ.get("OMP_NUM_THREADS")
    with pytest.raises(crash):
        gen.fit_m2(ctx, ORIGINS)
    assert not gen.forecast_path(ctx, "m2", "all", "asof").exists()
    assert os.environ.get("OMP_NUM_THREADS") == omp                # the parent's setting is undone


def test_a_fit_function_without_a_shift_is_refused_before_any_pool(vpath, tmp_path, monkeypatch):
    monkeypatch.setattr(stage_e, "_fit_origin", fit_without_shift)
    monkeypatch.setattr(gen, "ProcessPoolExecutor", None)          # any pool would fail here
    with pytest.raises(TypeError, match="shift"):
        gen.fit_m2(_ctx(tmp_path, vpath), ORIGINS)


def test_a_fit_that_ignores_its_shift_is_refused(vpath, tmp_path, monkeypatch):
    monkeypatch.setattr(stage_e, "_fit_origin", fit_ignores_shift)
    ctx = _ctx(tmp_path, vpath)
    with pytest.raises(RuntimeError, match="given shift 1000 but reports 0"):
        gen.fit_m2(ctx, ORIGINS, force_retry={ORIGINS[0]})           # the retry reports shift 0
    assert not gen.forecast_path(ctx, "m2", "all", "asof").exists()


# ---- tripwires (design §2.1) and worker hashes (§2.9) --------------------------------------
def test_tripwires_fire_inside_workers(vpath, tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "MODELS", {"probe": Probe})
    files = gen.harness_block(_ctx(tmp_path, vpath), ("probe",), "provider", ("asof",), ORIGINS)
    assert (pd.read_parquet(files["probe", "provider", "asof"])["value"] == len(FORBIDDEN)).all()


@pytest.mark.parametrize("block", ["harness", "aggregate", "m2"])
def test_a_tripwire_in_any_worker_stops_the_run(block, vpath, tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, vpath)
    monkeypatch.setattr(gen, "MODELS", {**STUBS, "b1": CallsTruth})
    monkeypatch.setattr(stage_e, "_fit_origin", fit_calls_calibrate)
    run_block = {"harness": lambda: gen.harness_block(ctx, ("b1",), "provider", ("asof",), ORIGINS),
                 "aggregate": lambda: gen.aggregate_block(ctx, ORIGINS),
                 "m2": lambda: gen.fit_m2(ctx, ORIGINS)}[block]
    with pytest.raises(gen.SealTripwire, match="calibrate" if block == "m2" else "load_truth"):
        run_block()


def test_parent_tripwires_cover_aliases_and_are_removed():
    before = (asof.load_truth, harness.score_forecasts, online.calibrate, splits.assert_not_sealed)
    with gen.tripwires():
        for f in (asof.load_truth, stage_e.load_truth, harness.load_truth, stage_f.load_truth,
                  stage_f.calibrate, harness.score_rows, splits.assert_not_sealed,
                  stage_f.truth_all):
            with pytest.raises(gen.SealTripwire):
                f()
        with gen.tripwires():                          # nested, as a block inside generate
            pass
        with pytest.raises(gen.SealTripwire):
            asof.load_truth()
        assert not hasattr(asof.load_asof, "tripwire")  # generation itself is untouched
    after = (asof.load_truth, harness.score_forecasts, online.calibrate, splits.assert_not_sealed)
    assert after == before
    assert stage_e.load_truth is asof.load_truth is harness.load_truth is stage_f.load_truth


def _forbidden(*args, **kwargs):
    asof.load_truth(None)


def test_parent_tripwires_are_on_inside_every_step3_function(vpath, tmp_path, monkeypatch):
    step3 = gen._step3(lambda: None).__code__
    for name in ("harness_block", "aggregate_block", "fit_m2", "generate", "step3_tables", "qa",
                 "forecast_hashes", "d7_check", "p13_check", "hash_commit", "dev_side"):
        assert getattr(gen, name).__code__ is step3, name          # the tripwire wrapper itself
    ctx, sha = _ctx(tmp_path, vpath), file_sha(vpath)
    fc = {("b0", "provider", "asof"): tmp_path / "b0.parquet"}
    tables = {name: pd.DataFrame() for name in HASH_FILES}
    calls = [(gen, "_origins", lambda: gen.harness_block(ctx, ("b1",), "icb", ("asof",), ORIGINS)),
             (gen, "_origins", lambda: gen.aggregate_block(ctx, ORIGINS)),
             (gen, "_origins", lambda: gen.fit_m2(ctx, ORIGINS)),
             (gen, "_origins", lambda: gen.generate(ctx, vintage_sha=sha)),
             (gen.pd, "read_parquet", lambda: gen.qa(fc, ctx)),
             (gen.pd, "read_parquet", lambda: gen.forecast_hashes(fc)),
             (gen.pd, "read_parquet", lambda: gen.d7_check(fc)),
             (gen.pq, "read_schema", lambda: gen.p13_check(fc, tmp_path / "forecasts.parquet")),
             (gen, "_git", lambda: gen.hash_commit(ctx, tables)),
             (gen, "harness_block", lambda: gen.dev_side(tmp_path / "prep", 2, vintages_path=vpath)),
             (gen, "forecast_hashes", lambda: gen.step3_tables(ctx, fc))]
    for owner, attr, call in calls:
        with monkeypatch.context() as mp:
            mp.setattr(owner, attr, _forbidden)                     # reached first, in the parent
            with pytest.raises(gen.SealTripwire):
                call()
    assert not hasattr(asof.load_truth, "tripwire")


def test_a_worker_hash_other_than_the_run_table_is_refused(vpath, tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "MODELS", STUBS)
    with pytest.raises(RuntimeError, match="vintage table"):
        gen.harness_block(_ctx(tmp_path, vpath), ("flat",), "provider", ("asof",), ORIGINS,
                          vintage_sha="0" * 64)


def test_the_worker_hash_is_taken_before_and_after_the_load(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "_WORKER", {})
    table = tmp_path / "v.parquet"
    table.write_bytes(b"as pinned")
    gen._load(lambda path: None, table)
    assert gen._WORKER["sha"] == file_sha(table)
    gen._load(lambda path: Path(path).write_bytes(b"replaced during the load"), table)
    assert gen._WORKER["sha"] == gen.CHANGED


def test_blocks_refuse_aggregate_levels_and_origins_after_e(vpath, tmp_path):
    ctx = _ctx(tmp_path, vpath)
    with pytest.raises(ValueError, match="aggregate_block"):
        gen.harness_block(ctx, ("b1",), "region", ("asof",), ORIGINS)
    with pytest.raises(ValueError, match="E ="):
        gen.harness_block(ctx, ("b1",), "provider", ("asof",), [date(2019, 12, 1)])


# ---- generate and the DEV side -------------------------------------------------------------
def test_generate_runs_every_block_and_writes_its_tables(vpath, tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "MODELS", STUBS)
    monkeypatch.setattr(stage_e, "_fit_origin", fit_ok)
    monkeypatch.setattr(gen, "DRY_FORCED_RETRY", ORIGINS[0])      # the dry run's forced retry
    ctx = _ctx(tmp_path, vpath)
    files = gen.generate(ctx, vintage_sha=file_sha(vpath))          # as step 2 recorded it
    assert len(files) == 5 * 2 + 3 + 3 * 2 + 1
    timings = pd.read_csv(ctx.work / "timings.csv")
    provider = [f"provider {k}" for k in ("b0", "b1", "b2", "m1", "m1_v3_raw")]
    assert timings["block"].tolist() == [*provider, "icb", "region+england", "m2"]
    assert (timings["rows"] > 0).all() and set(timings["vintage_sha"]) == {file_sha(vpath)}
    fits = pd.read_csv(ctx.work / "m2_fits.csv")
    assert fits["failed"].tolist() == [True, False, False]         # forced at ORIGINS[0], then fine
    tables = gen.step3_tables(ctx, files)
    assert list(tables) == list(HASH_FILES) and len(tables["forecast_hashes.csv"]) == len(files)
    q = tables["qa_counts.csv"]
    assert not q["absent"].any() and (q["missing_series"] == 0).all()
    with pytest.raises(FileExistsError):                             # never over a finished step 3
        gen.generate(ctx, vintage_sha=file_sha(vpath))


def test_generate_refuses_without_step2s_vintage_hash_before_any_pool(vpath, tmp_path,
                                                                      monkeypatch):
    monkeypatch.setattr(gen, "ProcessPoolExecutor", None)          # any pool would fail here
    for mode in ("run", "dry"):
        ctx = _ctx(tmp_path / mode, vpath, mode=mode)
        with pytest.raises(ValueError, match="step 2"):
            gen.generate(ctx)
        with pytest.raises(RuntimeError, match="step 2"):           # the file is not that table
            gen.generate(ctx, vintage_sha="0" * 64)
        assert not ctx.work.exists()
    with pytest.raises(ValueError, match="step 2"):                 # a run-mode block, too
        gen.fit_m2(_ctx(tmp_path, vpath, mode="run"), ORIGINS)


def test_dev_side_generates_the_missing_dev_forecasts(vpath, tmp_path, monkeypatch):
    assert len(gen.DEV_WINTER_H3) == 23 and {o.month for o in gen.DEV_WINTER_H3} == {10, 11, 12, 1}
    assert gen.DEV_WINTER_H3 is common.DEV_WINTER_H3        # the origins pin and check 11 expect
    monkeypatch.setattr(gen, "MODELS", STUBS)
    dev = (date(2019, 9, 1), *ORIGINS)
    monkeypatch.setattr(gen, "DEV", dev)
    monkeypatch.setattr(gen, "DEV_WINTER_H3", ORIGINS)
    monkeypatch.setattr(gen, "DEV_SIDE_ORIGINS", _side_origins(dev, ORIGINS))
    files = gen.dev_side(tmp_path / "prep", 2, vintages_path=vpath)
    h = gen.forecast_hashes(files).set_index(["model_key", "mode"])["origins"].to_dict()
    three, two = "2019-09;2019-10;2019-11", "2019-10;2019-11"
    assert h == {("b0", "asof"): three, ("m1", "asof"): three, ("b1", "asof"): two,
                 **{(k, "final"): two for k in ("b0", "b1", "b2", "m1", "m1_v3_raw")}}
    assert all(p.parent == tmp_path / "prep" / "forecasts" for p in files.values())
    assert set(files) == set(DEV_SIDE_KEYS)
    written = {f"dev_side/{p.relative_to(tmp_path / 'prep').as_posix()}" for p in files.values()}
    assert written == {n for n in P5_INPUTS if n.startswith("dev_side/")}   # prepare's layout
    monkeypatch.setattr(gen, "DEV", (CONF21[0],))
    monkeypatch.setattr(gen, "DEV_SIDE_ORIGINS", _side_origins((CONF21[0],), ORIGINS))
    with pytest.raises(ValueError, match="DEV origins only"):
        gen.dev_side(tmp_path / "prep2", 2, vintages_path=vpath)


def _side_origins(dev, winter) -> dict:
    """common.DEV_SIDE_ORIGINS with DEV and the DEV winter-h3 origins replaced."""
    return {k: (tuple(dev) if o == tuple(common.DEV) else tuple(winter))
            for k, o in common.DEV_SIDE_ORIGINS.items()}


@pytest.mark.parametrize("change", ["file", "origins"])
def test_dev_side_refuses_a_plan_other_than_the_pinned_files_before_any_pool(tmp_path,
                                                                             monkeypatch, change):
    """Report-commands:1: dev_side and pin share DEV_SIDE_ORIGINS; a drift in the files or in
    one file's origins fails at once, not after hours of generation (and before any rebuild:
    the vintage path given does not exist)."""
    monkeypatch.setattr(gen, "ProcessPoolExecutor", None)          # any pool would fail here
    pinned = dict(common.DEV_SIDE_ORIGINS)
    if change == "file":
        pinned.pop(("b1", "provider", "asof"))                      # e.g. no seeded B1
    else:
        pinned[("b1", "provider", "asof")] = pinned[("b1", "provider", "asof")][:-1]
    monkeypatch.setattr(gen, "DEV_SIDE_ORIGINS", pinned)
    with pytest.raises(ValueError, match="not the DEV_SIDE_ORIGINS that pin requires"):
        gen.dev_side(tmp_path / "prep", 2, vintages_path=tmp_path / "absent.parquet")
    assert not (tmp_path / "prep").exists()


def test_dev_side_takes_its_vintage_table_from_the_caller(tmp_path, monkeypatch):
    """No default rebuild: one under ``out_dir`` (INPUTS/dev_side) would be a 22nd input, which
    pin refuses after hours of generation. checks.prepare_inputs rebuilds outside INPUTS."""
    monkeypatch.setattr(gen, "ProcessPoolExecutor", None)          # any pool would fail here
    param = inspect.signature(gen.dev_side).parameters["vintages_path"]
    assert param.default is inspect.Parameter.empty
    with pytest.raises(TypeError, match="vintages_path"):
        gen.dev_side(tmp_path / "prep", 2)
    assert not (tmp_path / "prep").exists()


# ---- D7, P13 and the hash commit -----------------------------------------------------------
def _frame(origin, model, mode="asof", level="provider", periods_from=None,
           shift=0.0) -> pd.DataFrame:
    """Two series x 6 horizons x 9 quantiles of one target; a 50% width of 10."""
    start = ts(periods_from or origin)
    rows = [(ts(origin), mode, model, level, "att_all", s, h, start + pd.DateOffset(months=h - 1),
             q, 1000.0 + 100 * i + h + 20 * (q - 0.5) + shift, np.nan)
            for i, s in enumerate(("P1", "P2")) for h in HORIZONS for q in QUANTILES]
    return pd.DataFrame(rows, columns=gen.COLS)


def test_d7_check_reports_differences_and_the_seed_statistic(tmp_path):
    dup, dup2 = sorted(D7_FOLD)
    first = D7_FOLD[dup]
    b0 = [_frame(o, NAMES["b0"], periods_from=first) for o in (first, dup, dup2)]
    b0[2].loc[3, "value"] += 2.0
    mm = [_frame(o, NAMES["m2"], level="icb", periods_from=first, shift=s)
          for o, s in ((first, 0.0), (dup, 0.2), (dup2, 3.0))]
    final = [_frame(o, NAMES["b0"], mode="final", shift=float(i))
             for i, o in enumerate((first, dup, dup2))]
    files = {}
    for key, frames in ((("b0", "provider", "asof"), b0), (("m2", "all", "asof"), mm),
                        (("b0", "provider", "final"), final)):
        files[key] = tmp_path / f"{key[0]}_{key[2]}.parquet"
        pd.concat(frames, ignore_index=True).to_parquet(files[key], index=False)
    t = gen.d7_check(files).set_index(["model_key", "origin"])
    assert set(t["mode"]) == {"asof"} and len(t) == 4 and (t["reference"] == ts(first)).all()
    same, changed = t.loc[("b0", ts(dup))], t.loc[("b0", ts(dup2))]
    assert same["identical"] and same["max_abs_diff"] == 0 and same["n_ref"] == same["n_new"] == 108
    assert not changed["identical"] and changed["max_abs_diff"] == pytest.approx(2.0)
    close, far = t.loc[("m2", ts(dup))], t.loc[("m2", ts(dup2))]
    assert close["statistic"] == "seed stability" and close["level"] == "icb"
    assert close["median_ratio"] == pytest.approx(0.02) and close["within_limits"]
    assert far["p95_ratio"] == pytest.approx(0.3) and not far["within_limits"]
    lost = tmp_path / "m2_lost.parquet"                            # M2 failed at 2025-07 only
    pd.concat(mm[1:], ignore_index=True).to_parquet(lost, index=False)
    u = gen.d7_check({("m2", "all", "asof"): lost})
    assert len(u) == 2 and (u["n_ref"] == 0).all() and (u["only_new"] == 108).all()
    assert not u["identical"].any() and u["median_ratio"].isna().all()
    assert u["within_limits"].isna().all() and (u["statistic"] == "seed stability").all()


def test_p13_check_compares_values_on_the_filtered_slice_only(tmp_path):
    conf = [CONF21[0], CONF21[5]]
    new = {(k, "provider", mode): pd.concat([_frame(o, NAMES[k], mode) for o in conf],
                                            ignore_index=True)
           for k, mode in (("b0", "asof"), ("b1", "asof"), ("b0", "final"))}
    files = {}
    for key, f in new.items():
        files[key] = tmp_path / f"{key[0]}_provider_{key[2]}.parquet"
        f.to_parquet(files[key], index=False)
    b1_old = new["b1", "provider", "asof"].copy()
    b1_old.loc[3, "value"] *= 1.01
    outside = [_frame(date(2023, 12, 1), NAMES["b0"]), _frame(conf[0], NAMES["b0"], level="region"),
               _frame(conf[0], "m1_lightgbm_v3"), _frame(date(2025, 10, 1), NAMES["b0"])]
    old = pd.concat([new["b0", "provider", "asof"], b1_old, new["b0", "provider", "final"].iloc[1:],
                     *outside], ignore_index=True)
    quarantined = tmp_path / "forecasts.parquet"
    old.to_parquet(quarantined, index=False)
    t = gen.p13_check(files, quarantined).set_index(["model_key", "mode"])
    n = len(new["b0", "provider", "asof"])
    b0 = t.loc[("b0", "asof")]
    assert b0["identical"] and b0["n_old"] == b0["n_new"] == n and b0["share_identical"] == 1.0
    b1 = t.loc[("b1", "asof")]
    assert not b1["identical"] and b1["share_identical"] == pytest.approx((n - 1) / n)
    assert b1["max_rel_diff"] == pytest.approx(0.01 / 1.01) and b1["expected"].startswith("differs")
    fin = t.loc[("b0", "final")]
    assert fin["only_new"] == 1 and fin["only_old"] == 0 and not fin["identical"]
    for name, frame in (("scores.parquet", old), ("forecasts_y.parquet", old.assign(y=1.0))):
        frame.to_parquet(tmp_path / name, index=False)
        with pytest.raises(ValueError, match="forecast"):
            gen.p13_check(files, tmp_path / name)
    for name in ("scores.parquet", "summary.csv"):                 # refused unopened: not there
        with pytest.raises(ValueError, match="forecast"):
            gen.p13_check(files, tmp_path / "backtest" / name)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                          text=True).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    """A temporary repository with one commit and a pre-commit hook that refuses everything."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    for key, value in (("user.name", "Test"), ("user.email", "test@example.com"),
                       ("commit.gpgsign", "false")):
        _git(repo, "config", key, value)
    (repo / "README.md").write_text("start\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "start")
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    return repo


TABLES = {name: pd.DataFrame({"file": [name], "rows": [i]}) for i, name in enumerate(HASH_FILES)}


def test_hash_commit_adds_exactly_the_four_files_in_one_commit(tmp_path):
    repo = _repo(tmp_path)
    start = _git(repo, "rev-parse", "HEAD")
    (repo / "other.txt").write_text("staged, but not part of H1\n")
    _git(repo, "add", "other.txt")
    ctx = Context("run", ORIGINS, ORIGINS, {}, ORIGINS[-1], tmp_path / "work",
                  repo / "results" / "H-confirmatory", tmp_path / "v.parquet")
    tables = TABLES
    head = gen.hash_commit(ctx, tables)
    assert head == _git(repo, "rev-parse", "HEAD") != start
    assert _git(repo, "rev-list", "--parents", "-n", "1", head).split()[1:] == [start]
    assert sorted(_git(repo, "diff", "--name-status", start, head).splitlines()) == sorted(
        f"A\tresults/H-confirmatory/{name}" for name in HASH_FILES)
    assert _git(repo, "diff", "--cached", "--name-only") == "other.txt"    # staged, not committed
    assert pd.read_csv(ctx.results / "m2_fits.csv").equals(tables["m2_fits.csv"])
    with pytest.raises(FileExistsError):
        gen.hash_commit(ctx, tables)
    with pytest.raises(ValueError, match="exactly"):
        gen.hash_commit(ctx, {HASH_FILES[0]: tables[HASH_FILES[0]]})
    assert _git(repo, "rev-parse", "HEAD") == head
    for name in HASH_FILES:                                        # gone from the tree, still tracked
        (ctx.results / name).unlink()
    with pytest.raises(FileExistsError, match="tracks"):           # refused before writing or committing
        gen.hash_commit(ctx, tables)
    assert _git(repo, "rev-parse", "HEAD") == head and not any(ctx.results.iterdir())


def test_each_dry_run_hash_commit_adds_its_own_files(tmp_path):
    repo = _repo(tmp_path)
    heads = [_git(repo, "rev-parse", "HEAD")]
    for _ in range(2):                                             # "now, and again before the tag"
        ctx = Context("dry", ORIGINS, ORIGINS, {}, ORIGINS[-1],
                      tmp_path / "stage_h_dry" / heads[-1][:12], repo / "results" / "H-dryrun",
                      tmp_path / "v.parquet")
        heads.append(gen.hash_commit(ctx, TABLES))
        added = sorted(_git(repo, "diff", "--name-status", heads[-2], heads[-1]).splitlines())
        assert added == sorted(f"A\tresults/H-dryrun/{heads[-2][:12]}/{name}" for name in HASH_FILES)
        assert _git(repo, "rev-list", "--parents", "-n", "1", heads[-1]).split()[1:] == [heads[-2]]
    assert len(set(heads)) == 3
