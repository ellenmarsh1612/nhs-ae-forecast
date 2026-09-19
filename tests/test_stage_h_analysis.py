"""Stage H analysis (design §7.13, §9): the DEV side, and each CONF value set against DEV's
range, on synthetic scored frames held in fake stores.

Every value here is invented; the calendar dates are real so that W5, CONF19, the DEV winter
seasons and the one-origin 2023/24 fragment are the ones the run will use.
"""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from nhs_ae.evaluate.stage_f import F2_REFERENCE
from nhs_ae.evaluate.stage_h import analysis as an
from nhs_ae.evaluate.stage_h import hypotheses as hy
from nhs_ae.evaluate.stage_h import report
from nhs_ae.evaluate.stage_h.common import (
    CONF19,
    CONF21,
    D7_FOLD,
    DEV,
    G1_BASES,
    LEVELS,
    NAMES,
    RUN_END,
    W5,
    Context,
)

T = pd.Timestamp
TARGETS3 = ("att_all", "att_type1", "adm_via_ae")
QS = (0.025, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.975)
SERIES = {"provider": ["P1", "P2", "P3", "P4"], "icb": ["QA", "QB"], "region": ["Y1"],
          "england": ["ENGLAND"]}
MEDIAN = {"P1": 100, "P2": 200, "P3": 300, "P4": 400, "QA": 300, "QB": 700, "Y1": 1000,
          "ENGLAND": 1000}
ICB_OF, REGION_OF = {"P1": "QA", "P2": "QA", "P3": "QB", "P4": "QB"}, {"QA": "Y1", "QB": "Y1"}
AGG = ("icb", "region", "england")
# DEV: two in-range winter seasons (four winter-h3 origins each), the 2023/24 fragment
# (2023-10), and six more 2022 origins so that 2022 is an assessable coverage origin-year.
DEV_WINTER = ([date(2018, m, 1) for m in (10, 11, 12)] + [date(2019, 1, 1)]
              + [date(2022, m, 1) for m in (10, 11, 12)] + [date(2023, 1, 1), date(2023, 10, 1)])
DEV_ORIGINS = sorted([*DEV_WINTER, *(date(2022, m, 1) for m in range(4, 10))])
SEASONS = {"2018/19", "2022/23", "2023/24"}
ALL_STATS = set(an.SEASONS)


def scored(series, origins, *, model, level="provider", mode="asof", seed=0, failed=False,
           mase=1.0, cov90=0.9) -> pd.DataFrame:
    """Rows as ``harness.score_forecasts`` returns them, horizons 1-6 (period = origin - 1 +
    horizon months); ``failed`` None leaves out the G1 column (a model outside G1's scope)."""
    g = pd.MultiIndex.from_product(
        [list(series), TARGETS3, pd.DatetimeIndex([T(o) for o in origins]), range(1, 7)],
        names=["series", "target", "origin", "horizon"]).to_frame(index=False)
    m = g["origin"].dt.year * 12 + g["origin"].dt.month - 2 + g["horizon"]
    g["period"] = pd.to_datetime(pd.DataFrame({"year": m // 12, "month": m % 12 + 1, "day": 1}))
    rng = np.random.default_rng(seed)
    g["wis"] = rng.uniform(10.0, 20.0, len(g))
    g["mase"] = rng.uniform(0.5, 1.5, len(g)) * mase
    g["cov50"] = rng.random(len(g)) < 0.5
    g["cov90"] = rng.random(len(g)) < cov90
    g["winter"] = g["period"].dt.month.isin((12, 1, 2, 3))
    if failed is not None:
        g["failed"] = False
    return g.assign(model=model, level=level, mode=mode)


def score_tables(origins, *, seed=0, m1_mase=1.0, m1_cov90=0.9) -> dict[str, pd.DataFrame]:
    """Every scores-store table the analysis reads, at ``origins`` (names without the part)."""
    seeds = iter(range(seed, seed + 1000))
    t = {}
    for k in an.H4_KEYS:
        g1 = False if k in G1_BASES else None
        for mode in an.MODES:
            t[f"raw_{k}_provider_{mode}"] = scored(
                SERIES["provider"], origins, model=NAMES[k], mode=mode, seed=next(seeds),
                failed=g1, mase=m1_mase if k == "m1" else 1.0,
                cov90=m1_cov90 if k == "m1" else 0.9)
    t["raw_b1_provider_asof_seeded"] = scored(SERIES["provider"], origins, model=NAMES["b1"],
                                              seed=next(seeds))
    t["raw_b1_icb_asof"] = scored(SERIES["icb"], origins, model=NAMES["b1"], level="icb",
                                  seed=next(seeds))
    for k in G1_BASES:
        name = f"{NAMES[k]}+pooled"
        t[f"cal_d_{k}"] = scored(SERIES["provider"], origins, model=name, seed=next(seeds))
        for lv in LEVELS:
            t[f"cal_f_{k}_{lv}"] = scored(SERIES[lv], origins, model=name, level=lv,
                                          seed=next(seeds))
        t[f"mint_{k}"] = pd.concat([scored(SERIES[lv], origins, model=f"{name}+mint", level=lv,
                                           seed=next(seeds)) for lv in LEVELS], ignore_index=True)
    t["m2"] = pd.concat([scored(SERIES[lv], origins, model=NAMES["m2"], level=lv, failed=None,
                                seed=next(seeds)) for lv in AGG], ignore_index=True)
    return t


def forecasts(model: str, levels, origins) -> pd.DataFrame:
    """Long quantile forecasts with coherent medians (MEDIAN) at every origin and horizon."""
    g = pd.concat([pd.MultiIndex.from_product(
        [SERIES[lv], TARGETS3, pd.DatetimeIndex([T(o) for o in origins]), range(1, 7), QS],
        names=["series", "target", "origin", "horizon", "quantile"]).to_frame(index=False)
        .assign(level=lv) for lv in levels], ignore_index=True)
    return g.assign(value=g["series"].map(MEDIAN) * (0.8 + 0.4 * g["quantile"]), model=model,
                    mode="asof")


def h4b_components(origins) -> pd.DataFrame:
    return pd.DataFrame([{"origin": T(o), "target": t, "V": 1.0, "L": 2.0 if i % 3 else 0.5,
                          "lost_originals_n": int(i == 0)}
                         for i, o in enumerate(origins) for t in TARGETS3])


class FakeStore:
    """The part of ``store.Store`` the analysis uses: ``names`` and ``load``."""

    def __init__(self, frames: dict):
        self._frames = dict(frames)

    def names(self) -> list[str]:
        return sorted(self._frames)

    def load(self, name: str) -> pd.DataFrame:
        return self._frames[name].copy()


def contender_forecasts(origins) -> dict[str, pd.DataFrame]:
    return {label: forecasts(f"{NAMES[key]}+pooled" + ("+mint" if kind == "mint" else ""),
                             LEVELS, origins)
            for label, (kind, key) in an.F2_CONTENDERS.items()}


def step4(new_origins=(), dev_origins=DEV_ORIGINS, m2_dev=True) -> FakeStore:
    fc = contender_forecasts([*dev_origins, *new_origins])
    s4 = {"members": pd.DataFrame({"series": list(ICB_OF), "icb": list(ICB_OF.values())}),
          "regions": pd.DataFrame({"icb": list(REGION_OF), "region": list(REGION_OF.values())}),
          "h4b_dev": h4b_components(DEV), "h4b_new": h4b_components(new_origins),
          "failed_counts": pd.DataFrame({"model": ["ETS"], "failed": [0]})}
    for label, (kind, key) in an.F2_CONTENDERS.items():
        if kind == "cal_f":
            for lv in LEVELS:
                s4[f"cal_f_{key}_{lv}"] = fc[label][fc[label]["level"] == lv]
        else:
            s4[f"mint_{key}"] = fc[label]
    if m2_dev:
        s4["m2_dev"] = forecasts(NAMES["m2"], AGG, dev_origins)
    return FakeStore(s4)


def scores(dev=None, new=None, drop=()) -> FakeStore:
    parts = {**{f"{k}__dev": v for k, v in (dev or {}).items()},
             **{f"{k}__new": v for k, v in (new or {}).items()}}
    return FakeStore({k: v for k, v in parts.items() if k not in drop})


@pytest.fixture(scope="module")
def dev_tables():
    return score_tables(DEV_ORIGINS)


@pytest.fixture(scope="module")
def full_dev(dev_tables):
    """dev_side with every DEV input present."""
    return an.dev_side(an.Scores(step4(), scores(dev=dev_tables)),
                       contender_forecasts(DEV_ORIGINS), ICB_OF, REGION_OF)


def keys_of(t: pd.DataFrame, name: str) -> set:
    return set(map(tuple, t[[*an.SEASONS[name][0], "stat"]].to_numpy().tolist()))


# ---- the DEV side (§7.13) ----------------------------------------------------------------
def test_dev_side_with_every_dev_input_has_every_registered_statistic(full_dev):
    D = full_dev
    assert "_errors" not in D, D.get("_errors")
    assert set(D["seasons"]) == ALL_STATS
    assert set(D["coverage"]) == set(an.COVERAGE)
    for name, t in D["seasons"].items():
        assert set(t["season"]) == SEASONS, name
        assert t.loc[t["fragment"], "season"].unique().tolist() == ["2023/24"]
        assert not t.loc[t["fragment"], "in_range"].any()
        for col, value in {"split": "dev", "months": "winter", "horizons": "3",
                           "g1": hy.AS_ISSUED, "mode": an.SEASONS[name][1]["mode"]}.items():
            assert set(t[col]) == {value}, (name, col)
        assert {"level", *an.SEASONS[name][0], "stat", "value"} <= set(t.columns), name
    h1 = D["seasons"]["h1"]
    assert set(h1["model"]) == {NAMES["m1"], NAMES["m1_v3_raw"]}      # both tested models
    assert set(D["seasons"]["h4_original"]["stat"]) == {"delta_pp"}
    assert set(D["seasons"]["f2_wis"]["model"]) == {*an.F2_CONTENDERS, an.F2_M2}
    for c in D["coverage"].values():
        assert set(c["g1"]) == {hy.AS_ISSUED} and set(c["oyear"]) == {2022}
    # H4b: every DEV origin, counts only, no verdict (§7.10)
    h4b = D["h4b"]["table"]
    assert set(h4b["role"]) == {"descriptive"} and set(h4b["n_origins"]) == {len(DEV)}
    assert not any("verdict" in c for c in h4b.columns)
    # F2 over every DEV origin, with M2's DEV contender and a finite coherence gap
    f2 = D["f2"]["table"]
    assert an.F2_M2 in set(f2["model"]) and not np.isinf(f2["coh_gap_mean"]).any()
    no_children = (f2["model"] == an.F2_M2).to_numpy() & (f2["level"] == "icb").to_numpy()
    assert f2.loc[no_children, "coh_gap_n"].tolist() == [0]            # M2 has no providers
    assert (f2.loc[~no_children, "coh_gap_n"] > 0).all()
    assert set(D["f2"]["table"]["origin_set"]) == {f"{len(DEV_ORIGINS)} origins 2018-10..2023-10"}


def test_dev_season_tables_are_long_and_the_writer_splits_them_by_level(full_dev):
    h3, f2 = full_dev["seasons"]["h3"], full_dev["seasons"]["f2_wis"]
    assert not h3["stat"].str.contains("provider|icb|region|england").any()  # no level in a name
    assert set(h3["level"]) == set(LEVELS) and set(f2["level"]) == set(AGG)
    for name, t in (("h3", h3), ("f2_wis", f2)):
        parts = report.split_slices(f"dev.seasons.{name}", t)
        assert len(parts) == len(set(t["level"]))
        assert all(p["level"].nunique() == 1 for p in parts.values())


def test_conf_and_dev_statistics_share_keys(full_dev):
    """Each CONF value comes from the function behind its DEV seasons, so the keys match."""
    conf = score_tables(W5, seed=500)
    h1 = an._cat([conf[f"raw_{k}_provider_asof"] for k in an.H1_KEYS])
    h3 = {**{(k, "base"): an._cat([conf[f"cal_f_{k}_{lv}"] for lv in LEVELS]) for k in G1_BASES},
          **{(k, "mint"): conf[f"mint_{k}"] for k in G1_BASES}}
    h4 = {(k, mode): conf[f"raw_{k}_provider_{mode}"] for k in an.H4_KEYS for mode in an.MODES}
    f2 = {label: h3[(key, "base" if kind == "cal_f" else "mint")]
          for label, (kind, key) in an.F2_CONTENDERS.items()}
    f2[an.F2_M2] = conf["m2"]
    values = {"h1": an._h1_stat(h1, W5), "h3": an._h3_stat(h3, W5), "h4": an._h4_stat(h4, W5),
              "h4_original": an._h4o_stat(h4, W5), "f2_wis": an._f2_wis_stat(f2, W5)}
    for name, v in values.items():
        dev = full_dev["seasons"][name]
        assert keys_of(v, name) == keys_of(dev, name), name
        for s, g in dev.groupby("season"):
            assert keys_of(g, name) == keys_of(v, name), (name, s)
        tagged = an._conf_tagged(v, W5, name)
        assert (tagged["split"].iloc[0], tagged["origin_set"].iloc[0]) == ("conf", "W5")


def test_a_missing_dev_table_is_an_error_and_a_flag_with_a_reason(dev_tables):
    D = an.dev_side(an.Scores(step4(m2_dev=False), scores(dev=dev_tables,
                                                          drop=("raw_b0_provider_asof__dev",))),
                    contender_forecasts(DEV_ORIGINS), ICB_OF, REGION_OF)
    err = D["_errors"]
    for name in ("seasons.h1", "seasons.h4", "seasons.h4_original"):
        assert err[name].startswith(an.ABSENT) and "raw_b0_provider_asof__dev" in err[name]
    assert "m2_dev" in err["f2.m2"]                                     # M2 left out, and said
    assert {"h1", "h4", "h4_original"}.isdisjoint(D["seasons"])
    assert {"h3", "f2_wis"} <= set(D["seasons"])
    conf = an._conf_tagged(pd.DataFrame({"model": NAMES["m1"], "target": list(TARGETS3),
                                         "stat": "rel", "value": [0.1, 0.2, 0.3]}), W5, "h1")
    F = an.dev_compare({"h1": conf}, {}, {}, D)
    f = F["h1"]
    assert len(f) == 3 and f["outside"].isna().all() and f["dev_min"].isna().all()
    assert f["reason"].str.contains("not computed: DEV rows absent").all()
    assert F["outside"]["h1"] == {"n": 3, "n_outside": 0, "n_unflagged": 3, "flagged": []}
    assert F["_errors"]["h3"].startswith("no CONF value")               # never dropped silently
    assert F["_errors"]["coverage_primary"].startswith("no CONF cells")


# ---- CONF against DEV's range (§7.13) ----------------------------------------------------
def season_table(values: dict, fragment: float) -> pd.DataFrame:
    """A DEV h1 season table: values[target] per in-range season, and the fragment."""
    rows = []
    for s in ("2018/19", "2019/20", "2020/21", "2021/22", "2022/23", "2023/24"):
        for t, v in values.items():
            rows.append({"season": s, "fragment": s == "2023/24", "in_range": s != "2023/24",
                         "model": NAMES["m1"], "target": t, "stat": "rel",
                         "value": fragment if s == "2023/24" else v[int(s[:4]) - 2018]})
    return pd.DataFrame(rows)


def test_outside_devs_range_and_the_2023_24_fragment_left_out():
    dev = season_table({t: [-0.1, 0.0, 0.1, 0.2, 0.3] for t in TARGETS3}, fragment=5.0)
    conf = an._conf_tagged(pd.DataFrame({"model": NAMES["m1"], "target": list(TARGETS3),
                                         "stat": "rel", "value": [0.3, 1.0, -0.5]}), W5, "h1")
    F = an.dev_compare({"h1": conf}, {}, {}, {"seasons": {"h1": dev}})
    f = F["h1"].set_index("target")
    assert (f["dev_min"] == -0.1).all() and (f["dev_max"] == 0.3).all()   # not 5.0
    assert (f["n_seasons"] == 5).all()
    assert [hy._flag(f.loc[t, "outside"]) for t in TARGETS3] == [False, True, True]
    assert F["outside"]["h1"]["n_outside"] == 2
    assert F["outside"]["h1"]["flagged"] == [f"{NAMES['m1']} att_type1 rel",
                                             f"{NAMES['m1']} adm_via_ae rel"]
    assert set(f["split"]) == {"conf"} and set(f["origin_set"]) == {"W5"}
    assert set(f["months"]) == {"winter"} and set(f["level"]) == {"provider"}


def test_conf_statistics_against_real_dev_seasons(full_dev):
    """Default M1's CONF MASE at half the reference's: rel near -0.5, outside every DEV
    season's rel near 0."""
    conf = score_tables(W5, seed=700, m1_mase=0.5)
    h1 = an._cat([conf[f"raw_{k}_provider_asof"] for k in an.H1_KEYS])
    v = an._conf_tagged(an._h1_stat(h1, W5), W5, "h1")
    f = an.dev_compare({"h1": v}, {}, {}, full_dev)["h1"]
    m1 = f[(f["model"] == NAMES["m1"]).to_numpy()]
    assert (m1["conf"] < -0.3).all() and (m1["dev_max"] > -0.3).all()
    assert m1["outside"].map(hy._flag).tolist() == [True] * len(m1)
    assert (f["n_seasons"] == 2).all()                                  # 2023/24 left out


def test_coverage_flags_on_the_conf_cells(full_dev):
    conf = score_tables(CONF19, seed=900, m1_cov90=0.0)["raw_m1_provider_asof"]
    cells = an._cells(conf, CONF19)
    pooled = pd.DataFrame({"horizon": range(1, 7), "point": 0.5})
    F = an.dev_compare({}, {"h2_m1": cells}, {"h2_m1": pooled}, full_dev)
    f = F["coverage_h2_m1"]
    assert sorted(set(f["oyear"])) == [2024, 2025] and len(f) == 12
    assert f["outside"].map(hy._flag).tolist() == [True] * 12           # 0 against DEV's ~0.9
    assert (f["conf_pooled"] == 0.5).all() and (f["dev_cells"] == 1).all()
    for col, value in {"split": "conf", "origin_set": "CONF19", "model": NAMES["m1"],
                       "stat": "cov90", "g1": hy.AS_ISSUED, "level": "provider"}.items():
        assert set(f[col]) == {value}, col


def test_winter_origins_must_be_w5_in_every_table_in_run_mode():
    rows = scored(SERIES["provider"], CONF19, model=NAMES["b0"])
    short = rows[rows["origin"] != T(W5[1])]
    assert an._winter_origins({"a": rows}, CONF19, "run") == [T(o) for o in W5]
    assert an._winter_origins({"a": rows, "b": short}, CONF19, "dry") == \
        [T(o) for o in W5 if o != W5[1]]
    out: dict = {}
    an._guard("h1", lambda: an._winter_origins({"a": rows, "b": short}, CONF19, "run"), out)
    assert "h1" not in out
    assert out["_errors"]["h1"].startswith("not evaluable: origins ['2024-10'] missing")
    assert "'b': ['2024-10']" in out["_errors"]["h1"]


# ---- compute, end to end ------------------------------------------------------------------
def fits() -> pd.DataFrame:
    return pd.DataFrame([{"origin": T(o), "attempt": 0, "failed": False, "rhat_max": 1.05,
                          "ess_bulk_min": 60.0, "divergences": 0} for o in CONF21])


def run(tmp_path, dev_tables, new=None) -> dict:
    ctx = Context("run", CONF21, CONF19, dict(D7_FOLD), RUN_END, tmp_path, tmp_path,
                  tmp_path / "vintages.parquet")
    m2_path = tmp_path / "m2.parquet"
    forecasts(NAMES["m2"], AGG, CONF21).to_parquet(m2_path)
    new = score_tables(CONF21, seed=300) if new is None else new
    return an.compute(ctx, step4(new_origins=CONF21), scores(dev=dev_tables, new=new),
                      {("m2", "all", "asof"): m2_path}, fits())


@pytest.fixture(scope="module")
def results(tmp_path_factory, dev_tables):
    return run(tmp_path_factory.mktemp("run"), dev_tables)


def test_compute_sets_every_conf_value_against_devs_range(results):
    R = results
    assert "_errors" not in R, R.get("_errors")
    assert "_errors" not in R["dev"], R["dev"].get("_errors")
    F = R["dev_flags"]
    assert set(F) == {*ALL_STATS, *(f"coverage_{c}" for c in an.COVERAGE), "outside"}
    for name, t in F.items():
        if name == "outside":
            continue
        ref = ((t["model"] == F2_REFERENCE).to_numpy() if name == "f2_wis"
               else np.zeros(len(t), dtype=bool))
        assert t["dev_min"].notna().all() and t.loc[~ref, "outside"].notna().all(), name
        assert set(F["outside"][name]) == {"n", "n_outside", "n_unflagged", "flagged"}
    f2 = F["f2_wis"]
    ref = f2[(f2["model"] == F2_REFERENCE).to_numpy()]
    assert len(ref) and ref["outside"].isna().all() and set(ref["reason"]) == {an.SELF}
    assert F["outside"]["f2_wis"]["n_unflagged"] == len(ref)          # not counted as in range
    for name in ALL_STATS:
        assert set(F[name]["split"]) == {"conf"} and set(F[name]["origin_set"]) == {"W5"}
    prim = R["primary"]["alongside"]["dev_range"]
    assert prim is F["coverage_primary"] and len(prim) == 12 and prim["conf_pooled"].notna().all()
    pd.testing.assert_series_equal(
        prim["conf"], R["primary"]["alongside"]["as_issued"]["cells"]["value"],
        check_names=False)                                              # the same CONF19 cells
    assert set(F["coverage_headline_pooled_b1"]["model"]) == {f"{NAMES['b1']}+pooled"}
    assert "conf21" in R["h4b"] and set(R["h4b"]["table"]["origin_set"]) == {"CONF19"}
    assert set(R["h4b"]["conf21"]["table"]["origin_set"]) == {"CONF21"}
    wis = R["f2"]["wis"]
    rel = F["f2_wis"].set_index(["model", "level", "target"])["conf"]
    assert np.allclose(rel.loc[list(zip(wis["model"], wis["level"], wis["target"]))].to_numpy(),
                       wis["rel"].to_numpy(float))                      # F2's own WIS table


def test_compute_records_an_incomplete_w5_as_not_evaluable(tmp_path, dev_tables):
    new = score_tables(CONF21, seed=300)
    b0 = new["raw_b0_provider_asof"]
    new["raw_b0_provider_asof"] = b0[b0["origin"] != T(W5[1])]
    R = run(tmp_path, dev_tables, new=new)
    missing = "not evaluable: origins ['2024-10'] missing"
    for name in ("h1", "h4", "h4_original"):
        assert name not in R and missing in R["_errors"][name], name
        assert R["_errors"][f"dev_flags.{name}"].startswith(f"no CONF value: {missing}")
    assert R["_errors"]["h1"].startswith(missing)
    assert R["_errors"]["h4_original"].startswith("not computed: H4 has no result")
    assert "h3" in R and "primary" in R and "h3" in R["dev_flags"]


def test_h3_checks_w5_level_by_level(tmp_path, dev_tables):
    """One level's table short of a W5 origin makes H3 not evaluable, although the other
    levels of the same base still carry that origin."""
    new = score_tables(CONF21, seed=300)
    reg = new["cal_f_b1_region"]
    new["cal_f_b1_region"] = reg[reg["origin"] != T(W5[1])]
    R = run(tmp_path, dev_tables, new=new)
    assert "h3" not in R
    assert R["_errors"]["h3"].startswith("not evaluable: origins ['2024-10'] missing")
    assert "b1/base/region" in R["_errors"]["h3"]
    assert "h1" in R and "h4" in R
