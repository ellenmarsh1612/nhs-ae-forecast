"""Stage H statistics primitives (design §7.2-§7.5, §7.13, §11) on synthetic scored frames.

Every frame here is invented; the calendar dates are real so that the D7 fold, W5 and the
gap cases are exercised on the origins the run will use.
"""
import time
from datetime import date
from fractions import Fraction

import numpy as np
import pandas as pd
import pytest

from nhs_ae.evaluate.metrics import paired_bootstrap
from nhs_ae.evaluate.stage_h import stats
from nhs_ae.evaluate.stage_h.common import CONF19, CONF21, D7_FOLD, DRY, K5, W5

TARGETS3 = ("att_all", "att_type1", "adm_via_ae")
T = pd.Timestamp


def scored(n_series=10, origins=W5, horizons=(3,), targets=TARGETS3, p=0.9, seed=0, models=None,
           **const) -> pd.DataFrame:
    """Synthetic scored rows: one per series x target x origin x horizon (x model), with
    period = origin - 1 + horizon months (``asof.last_period``)."""
    levels = [[f"R{i:03d}" for i in range(n_series)], list(targets),
              pd.DatetimeIndex([T(o) for o in origins]), list(horizons)]
    names = ["series", "target", "origin", "horizon"]
    if models is not None:
        levels, names = [list(models), *levels], ["model", *names]
    g = pd.MultiIndex.from_product(levels, names=names).to_frame(index=False)
    m = g["origin"].dt.year * 12 + g["origin"].dt.month - 2 + g["horizon"]
    g["period"] = pd.to_datetime(pd.DataFrame({"year": m // 12, "month": m % 12 + 1, "day": 1}))
    rng = np.random.default_rng(seed)
    g["cov90"] = rng.random(len(g)) < p
    g["mase"] = rng.uniform(0.5, 1.5, len(g))
    g["wis"] = rng.uniform(10.0, 20.0, len(g))
    base = {"mode": "asof", "level": "provider"}
    if models is None:
        base["model"] = "b0_seasonal_naive"
    return g.assign(**{**base, **const})


def draws_for(rows, origins=CONF19, fold=None, **kw):
    uo = stats.origin_units(origins, fold)
    return stats.make_draws(rows["series"], uo.values(), **kw), uo


def test_fixture_period_follows_the_origin_convention():
    from nhs_ae.evaluate.asof import last_period
    rows = scored(n_series=2, origins=CONF21, horizons=range(1, 7))
    expected = [last_period(o) + pd.DateOffset(months=h)
                for o, h in zip(rows["origin"], rows["horizon"])]
    assert rows["period"].tolist() == expected
    w5 = scored(origins=W5, horizons=(3,))["period"]
    assert w5.dt.month.isin(stats.WINTER_MONTHS).all()
    assert sorted(set(w5)) == [T(p) for p in ("2024-03", "2024-12", "2025-01", "2025-02",
                                              "2025-03")]


# ---- compare (§7.2) ----------------------------------------------------------------------
def test_compare_tested_at_0_8_of_reference():
    ref = scored()
    tested = ref.assign(model="m1_lightgbm", mase=0.8 * ref["mase"])
    r = stats.compare(ref, tested, "mase")
    assert r["rel"] == pytest.approx(-0.20)
    assert r["rel_lo"] == pytest.approx(-0.20) and r["rel_hi"] == pytest.approx(-0.20)
    assert r["n_pairs"] == len(ref) == r["n_ref"] == r["n_tested"]      # targets pooled
    assert r["unpaired_ref"] == r["unpaired_tested"] == 0
    assert r["n_units"] == 10 and r["evaluable"] is True
    direct = paired_bootstrap(ref, tested, "mase", "series", 1000, 0, K5)
    assert {k: r[k] for k in direct} == direct


def test_default_keys_pair_across_targets_negative_control():
    ref = scored()
    tested = ref.assign(model="m1_lightgbm", mase=0.8 * ref["mase"])
    assert paired_bootstrap(ref, tested, metric="mase")["n_pairs"] == 3 * len(ref)
    with pytest.raises(ValueError, match="duplicate"):
        stats.compare(ref, tested, "mase", keys=("series", "origin", "horizon", "period"))


@pytest.mark.parametrize("col, other", [("model", "m1_lightgbm"), ("mode", "final"),
                                        ("level", "icb")])
def test_compare_refuses_a_frame_mixing_slices(col, other):
    ref = scored()
    mixed = ref.copy()
    mixed.loc[0, col] = other
    with pytest.raises(ValueError, match=col):
        stats.compare(mixed, ref.assign(model="m1_lightgbm"), "mase")
    with pytest.raises(ValueError, match=col):
        stats.compare(ref, mixed, "mase")


def test_compare_counts_unpaired_rows_when_one_frame_has_extra_rows():
    ref = scored(n_series=10)                                    # 150 rows
    tested = scored(n_series=12, seed=1, model="m1_lightgbm")    # 180 rows; first 150 share keys
    assert (tested.loc[:149, list(K5)].to_numpy() == ref[list(K5)].to_numpy()).all()
    ref.loc[[0, 1, 2], "mase"] = np.nan
    tested.loc[[2, 3, 4, 5, 6, 160], "mase"] = np.nan
    r = stats.compare(ref, tested, "mase")
    assert r["n_ref"] == 147 and r["n_tested"] == 174
    assert r["n_pairs"] == 150 - 7                               # keys 0..6 lose a side
    assert r["unpaired_ref"] == 4                                # rows 3..6
    assert r["unpaired_tested"] == 2 + 29                        # rows 0, 1 and the extra series
    assert r["n_units"] == 10 and r["evaluable"]


def test_compare_empty_join_is_not_evaluable():
    ref = scored()
    tested = scored(origins=[date(2024, 2, 1)], model="m1_lightgbm")
    r = stats.compare(ref, tested, "mase")
    assert r["evaluable"] is False and r["n_units"] == 0 and r["n_pairs"] == 0
    assert all(np.isnan(r[k]) for k in ("diff", "diff_lo", "diff_hi", "rel", "rel_lo", "rel_hi"))
    assert r["unpaired_ref"] == len(ref) and r["unpaired_tested"] == len(tested)


# ---- origin units and draws (§7.4) -------------------------------------------------------
def test_d7_folding_maps_21_origins_to_19_units():
    u = stats.origin_units(CONF21, D7_FOLD)
    assert len(u) == 21 and len(set(u.values())) == 19
    assert u[T("2025-08-01")] == u[T("2025-09-01")] == T("2025-07-01")
    assert all(k == v for k, v in u.items() if k < T("2025-08-01"))
    identity = {T(o): T(o) for o in CONF19}
    assert stats.origin_units(CONF19, {}) == identity
    assert stats.origin_units(CONF19, D7_FOLD) == identity      # fold keys outside are ignored


def test_n19_gives_block_starts_0_to_16_and_19_slots():
    d = stats.make_draws([f"R{i}" for i in range(50)], CONF19)
    assert d.units == [T(o) for o in CONF19]
    assert d.starts.shape == (1000, 7) and d.starts.min() == 0 and d.starts.max() == 16
    assert d.slots.shape == (1000, 19)
    assert d.W.shape == (1000, 50) and d.V.shape == (1000, 19)
    assert np.issubdtype(d.W.dtype, np.integer) and np.issubdtype(d.V.dtype, np.integer)
    assert (d.W.sum(axis=1) == 50).all() and (d.V.sum(axis=1) == 19).all()


def test_draws_reproducible_under_seed_0_series_drawn_first():
    series = [f"R{i:02d}" for i in range(30)]
    a = stats.make_draws(series, CONF19)
    b = stats.make_draws(series[::-1] + series[:3], list(CONF19)[::-1])   # order, duplicates
    assert a.series == b.series and a.units == b.units
    assert np.array_equal(a.W, b.W) and np.array_equal(a.V, b.V)
    rng = np.random.default_rng(0)
    idx = rng.integers(0, 30, size=(1000, 30))
    starts = rng.integers(0, 17, size=(1000, 7))
    assert np.array_equal(a.W, stats._multiplicities(idx, 30))
    assert np.array_equal(a.starts, starts)
    assert not np.array_equal(a.V, stats.make_draws(series, CONF19, seed=1).V)


def test_end_effect_multiplicities_by_exact_enumeration():
    """V is a sum over blocks, and block j's kept slots depend only on its own start, so
    E[V_u] = sum_j P(u in block j) = mean over s = 0..16 of V_u with every block at s."""
    n, length = 19, 3
    k = -(-n // length)
    every = np.repeat(np.arange(n - length + 1)[:, None], k, axis=1)
    counts = stats._multiplicities(stats._block_slots(every, n, length), n).sum(axis=0)
    assert counts.tolist() == [7, 13, *[19] * 15, 12, 6]
    e = [Fraction(int(c), n - length + 1) for c in counts]
    assert (e[0], e[1], e[9], e[17], e[18]) == (Fraction(7, 17), Fraction(13, 17),
                                                Fraction(19, 17), Fraction(12, 17), Fraction(6, 17))
    assert [round(float(x), 2) for x in (e[0], e[1], e[9], e[17], e[18])] == \
        [0.41, 0.76, 1.12, 0.71, 0.35]                           # the figures in §7.4
    assert sum(e) == n


@pytest.mark.parametrize("n_units", [1, 2])
def test_fewer_than_three_units_fix_every_origin_weight(n_units):
    units = CONF19[:n_units]
    rows = scored(n_series=5, origins=units, horizons=(1, 2))
    d, uo = draws_for(rows, units)
    assert d.starts.shape == (1000, 1) and (d.starts == 0).all() and (d.V == 1).all()
    t = stats.two_way(rows, ["horizon"], "cov90", d, uo)
    assert t["degenerate"].all() and (t["n_units"] == n_units).all()
    assert t["lo"].equals(t["lo_within"]) and t["hi"].equals(t["hi_within"])


def test_make_draws_refuses_no_series_or_no_units():
    with pytest.raises(ValueError):
        stats.make_draws([], CONF19)
    with pytest.raises(ValueError):
        stats.make_draws(["RAA"], [])


def test_gap_in_the_origin_list():
    present = [o for o in CONF19 if o != date(2024, 6, 1)]     # a failed fit at 2024-06
    rows = scored(n_series=8, origins=present, horizons=(1, 2))
    d, uo = draws_for(rows, present)
    assert len(d.units) == 18 and d.starts.shape == (1000, 6) and d.starts.max() == 15
    t = stats.two_way(rows, ["horizon"], "cov90", d, uo)
    assert (t["n_units"] == 18).all() and not t["degenerate"].any()
    i = d.units.index(T("2024-05-01"))                          # a block may span the gap
    assert [d.units[j] for j in stats._block_slots(np.array([[i]]), 18, 3)[0]] == \
        [T("2024-05-01"), T("2024-07-01"), T("2024-08-01")]
    assert (d.starts == i).any()
    with pytest.raises(ValueError, match="without a unit"):
        stats.two_way(scored(n_series=8, origins=CONF19), ["horizon"], "cov90", d, uo)


def test_draws_must_come_from_the_units_and_series_present():
    """§7.4: after a failed fit the units are the origins present. Draws over all CONF19
    units, or over a series with no row, would change k and the interval silently."""
    present = [o for o in CONF19 if o != date(2024, 6, 1)]
    rows = scored(n_series=8, origins=present, horizons=(1, 2))
    d19, uo19 = draws_for(rows, CONF19)
    with pytest.raises(ValueError, match=r"present in the table.*units \['2024-06'\]"):
        stats.two_way(rows, ["horizon"], "cov90", d19, uo19)
    with pytest.raises(ValueError, match=r"units \['2024-06'\]"):
        stats.two_way_diff(rows, rows, ["horizon"], "cov90", d19, uo19)
    phantom, uo = draws_for(pd.concat([rows, rows.iloc[:1].assign(series="RZZ")]), present)
    with pytest.raises(ValueError, match=r"series \['RZZ'\]"):
        stats.two_way(rows, ["horizon"], "cov90", phantom, uo)
    d, _ = draws_for(rows, present)
    ok = stats.two_way(rows, ["horizon"], "cov90", d, uo)
    assert (ok["n_units"] == 18).all() and d.starts.shape[1] == 6 and d19.starts.shape[1] == 7
    per_model = stats.two_way(rows, ["horizon"], "cov90", phantom, uo, partial=True)
    assert (per_model["n_series"] == 8).all()
    diff = stats.two_way_diff(rows.iloc[:0], rows, ["horizon"], "cov90", d, uo)   # union counts
    assert diff["point"].isna().all()
    with pytest.raises(ValueError, match="present in the table"):
        stats.two_way(rows[rows["horizon"] == 1].iloc[:8], ["horizon"], "cov90", d, uo)


# ---- two_way (§7.4) ----------------------------------------------------------------------
def test_all_rows_covered_gives_one_one():
    rows = scored(n_series=15, origins=CONF19, horizons=range(1, 7)).assign(cov90=True)
    d, uo = draws_for(rows)
    t = stats.two_way(rows, ["target", "horizon"], "cov90", d, uo)
    assert len(t) == 18
    for c in ("point", "lo", "hi", "lo_within", "hi_within"):
        assert (t[c] == 1.0).all()
    assert (t["zero_den"] == 0).all() and (t["boot_mean_minus_point"] == 0).all()
    assert (t["n_rows"] == 15 * 19).all() and (t["n_series"] == 15).all()


def test_two_way_reproducible_under_seed_0():
    rows = scored(n_series=20, origins=CONF19, horizons=range(1, 7), p=0.88)
    d1, uo = draws_for(rows)
    t1 = stats.two_way(rows, ["horizon"], "cov90", d1, uo)
    shuffled = rows.sample(frac=1.0, random_state=3)
    d2, _ = draws_for(shuffled)
    t2 = stats.two_way(shuffled, ["horizon"], "cov90", d2, uo)
    pd.testing.assert_frame_equal(t1, t2)
    assert (t1["lo"] < t1["point"]).all() and (t1["point"] < t1["hi"]).all()


def test_rows_weighted_equally():
    units = CONF19[:6]
    a = scored(n_series=1, origins=units, targets=TARGETS3[:2]).assign(series="A", cov90=True)
    b = scored(n_series=1, origins=units[:3], targets=TARGETS3[:1]).assign(series="B", cov90=False)
    rows = pd.concat([a, b], ignore_index=True)                # 12 covered rows, 3 not
    d, uo = draws_for(rows, units)
    t = stats.two_way(rows, [], "cov90", d, uo)
    assert t["point"].iloc[0] == pytest.approx(12 / 15)         # not 1/2 (series-weighted)
    _, [(K, N)] = stats._prepare([rows], [], "cov90", d, uo, "series")
    num, den, _, _ = stats._resample(K, N, d)
    s = pd.Index(d.series).get_indexer(rows["series"])
    u = pd.DatetimeIndex(d.units).get_indexer(rows["origin"])
    w = d.W[:, s] * d.V[:, u]                                   # each row's resample weight
    assert np.array_equal(num[:, 0], w @ rows["cov90"].to_numpy(float))
    assert np.array_equal(den[:, 0], w.sum(axis=1).astype(float))


def test_resampled_share_matches_row_level_weights_on_an_unbalanced_table():
    rows = scored(n_series=12, origins=CONF19, horizons=(1, 2, 3), p=0.85, seed=4)
    rows = rows.sample(frac=0.6, random_state=5).reset_index(drop=True)
    d, uo = draws_for(rows)
    keys, [(K, N)] = stats._prepare([rows], ["target", "horizon"], "cov90", d, uo, "series")
    num, den, num_w, den_w = stats._resample(K, N, d)
    s = pd.Index(d.series).get_indexer(rows["series"])
    u = pd.DatetimeIndex(d.units).get_indexer(rows["origin"])
    w, w1 = d.W[:, s] * d.V[:, u], d.W[:, s].astype(float)
    k = rows["cov90"].to_numpy(float)
    t = stats.two_way(rows, ["target", "horizon"], "cov90", d, uo)
    for c, key in keys.iterrows():
        m = ((rows["target"] == key["target"]) & (rows["horizon"] == key["horizon"])).to_numpy()
        assert np.array_equal(num[:, c], w[:, m] @ k[m])
        assert np.array_equal(den[:, c], w[:, m].sum(axis=1).astype(float))
        assert np.array_equal(num_w[:, c], w1[:, m] @ k[m])
        assert np.array_equal(den_w[:, c], w1[:, m].sum(axis=1))
        ok = den[:, c] > 0
        r = num[ok, c] / den[ok, c]
        assert t.loc[c, "point"] == pytest.approx(k[m].mean(), abs=1e-15)
        assert [t.loc[c, "lo"], t.loc[c, "hi"]] == list(np.percentile(r, [2.5, 97.5]))
        assert t.loc[c, "boot_mean_minus_point"] == pytest.approx(r.mean() - k[m].mean())
        assert t.loc[c, "zero_den"] == int((~ok).sum())


def test_two_way_d7_folding_weights_late_rows_by_the_2025_07_unit():
    """Rows at 2025-08 and 2025-09 keep their origin and take 2025-07's origin weight.
    Relabelling their origin instead would duplicate keys, which two_way refuses."""
    rows = scored(n_series=10, origins=CONF21, horizons=range(1, 7), p=0.87, seed=2)
    d, uo = draws_for(rows, CONF21, D7_FOLD)
    assert len(d.units) == 19 and d.units[-1] == T("2025-07-01")
    t = stats.two_way(rows, ["horizon"], "cov90", d, uo)
    assert (t["n_units"] == 19).all() and (t["n_rows"] == 10 * 3 * 21).all()
    _, [(_, N)] = stats._prepare([rows], ["horizon"], "cov90", d, uo, "series")
    assert (N[:, :, -1] == 9).all() and (N[:, :, :-1] == 3).all()
    s = pd.Index(d.series).get_indexer(rows["series"])
    u = pd.DatetimeIndex(d.units).get_indexer(rows["origin"].map(uo))
    w, k = d.W[:, s] * d.V[:, u], rows["cov90"].to_numpy(float)
    for c, h in enumerate(t["horizon"]):
        m = (rows["horizon"] == h).to_numpy()
        r = (w[:, m] @ k[m]) / w[:, m].sum(axis=1)
        assert [t.loc[c, "lo"], t.loc[c, "hi"]] == list(np.percentile(r, [2.5, 97.5]))
    late = rows["origin"] > T("2025-07-01")
    relabelled = rows.assign(origin=rows["origin"].where(~late, T("2025-07-01")))
    with pytest.raises(ValueError, match="duplicate"):
        stats.two_way(relabelled, ["horizon"], "cov90", d, stats.origin_units(CONF19, {}))


def test_within_period_interval_equals_every_origin_weight_one():
    rows = scored(n_series=15, origins=CONF19, horizons=range(1, 7), p=0.9, seed=6)
    d, uo = draws_for(rows)
    ones = stats.Draws(d.series, d.units, d.W, np.ones_like(d.V))
    t = stats.two_way(rows, ["horizon"], "cov90", d, uo)
    t1 = stats.two_way(rows, ["horizon"], "cov90", ones, uo)
    assert not t["degenerate"].any()
    assert np.array_equal(t["lo_within"], t1["lo"]) and np.array_equal(t["hi_within"], t1["hi"])
    assert np.array_equal(t1["lo"], t1["lo_within"]) and not np.array_equal(t["lo"], t1["lo"])


def test_zero_denominator_resamples_dropped_and_counted():
    full = scored(n_series=10, origins=CONF19, horizons=(1,), seed=7)
    tail = scored(n_series=10, origins=CONF19[16:], horizons=(2,), seed=8)    # last 3 units
    last = scored(n_series=10, origins=CONF19[18:], horizons=(3,), seed=9)    # last unit
    rows = pd.concat([full, tail, last], ignore_index=True)
    d, uo = draws_for(rows)
    t = stats.two_way(rows, ["horizon"], "cov90", d, uo).set_index("horizon")
    assert t.loc[1, "zero_den"] == 0
    dropped = int((d.V[:, 16:].sum(axis=1) == 0).sum())
    assert t.loc[2, "zero_den"] == dropped > 0 and not t.loc[2, "degenerate"]
    _, [(K, N)] = stats._prepare([tail], [], "cov90", d, uo, "series", partial=True)
    num, den, _, _ = stats._resample(K, N, d)
    keep = den[:, 0] > 0
    assert keep.sum() == 1000 - dropped
    assert [t.loc[2, "lo"], t.loc[2, "hi"]] == \
        list(np.percentile(num[keep, 0] / den[keep, 0], [2.5, 97.5]))
    assert t.loc[3, "zero_den"] == int((d.V[:, 18] == 0).sum()) > 0
    assert t.loc[3, "degenerate"] and t.loc[3, "n_units"] == 1
    assert t.loc[3, "lo"] == t.loc[3, "lo_within"] and t.loc[3, "hi"] == t.loc[3, "hi_within"]
    assert (t["zero_den_within"] == 0).all()


def test_origin_degenerate_cells_in_a_dry_run_like_table():
    """Six origins, a unit list fixed across horizons, and horizon h scored at the first
    7 - h origins (design §10): cells at h5 and h6 are origin-degenerate. Zero-denominator
    resamples occur at h4 too, when both block starts are 3 (p = 1/16, exact enumeration)."""
    parts = [scored(n_series=12, origins=DRY[:7 - h], horizons=(h,), seed=h) for h in range(1, 7)]
    rows = pd.concat(parts, ignore_index=True)
    d, uo = draws_for(rows, DRY)
    assert len(d.units) == 6 and d.starts.shape == (1000, 2)
    t = stats.two_way(rows, ["horizon"], "cov90", d, uo).set_index("horizon")
    assert t["n_units"].tolist() == [6, 5, 4, 3, 2, 1]
    assert t["degenerate"].tolist() == [False] * 4 + [True] * 2
    for h in range(1, 7):
        assert t.loc[h, "zero_den"] == int((d.V[:, :7 - h].sum(axis=1) == 0).sum())
    assert t.loc[6, "zero_den"] > t.loc[5, "zero_den"] > t.loc[4, "zero_den"] > 0
    pairs = np.array([[a, b] for a in range(4) for b in range(4)])        # every start pair
    v = stats._multiplicities(stats._block_slots(pairs, 6, 3), 6)
    p_zero = [Fraction(int((v[:, :7 - h].sum(axis=1) == 0).sum()), 16) for h in range(1, 7)]
    assert p_zero == [0, 0, 0, Fraction(1, 16), Fraction(1, 4), Fraction(9, 16)]
    deg = t[t["degenerate"]]
    assert deg["lo"].equals(deg["lo_within"]) and deg["hi"].equals(deg["hi_within"])


def test_two_way_refuses_rows_it_cannot_place():
    rows = scored(n_series=6, origins=CONF19, horizons=(1,))
    d, uo = draws_for(rows)
    with pytest.raises(ValueError, match="series outside"):
        stats.two_way(rows.assign(series="Z" + rows["series"]), ["horizon"], "cov90", d, uo)
    with pytest.raises(ValueError, match="boolean"):
        stats.two_way(rows.assign(cov90=np.where(rows["cov90"], 1.0, np.nan)), ["horizon"],
                      "cov90", d, uo)
    with pytest.raises(ValueError, match="boolean"):
        stats.two_way(rows.assign(cov90=0.5), ["horizon"], "cov90", d, uo)


def test_an_empty_table_raises_unless_partial():
    """A filter that matches nothing (a mistyped model name) must not write an empty table."""
    rows = scored(n_series=6, origins=CONF19, horizons=(1,))
    d, uo = draws_for(rows)
    none = rows[rows["model"] == "b0_seasonal_niave"]
    with pytest.raises(ValueError, match="empty table"):
        stats.two_way(none, ["horizon"], "cov90", d, uo)
    with pytest.raises(ValueError, match="empty table"):
        stats.two_way_diff(none, none, ["horizon"], "cov90", d, uo)
    t = stats.two_way(none, ["horizon"], "cov90", d, uo, partial=True)
    assert t.empty and list(t.columns) == ["horizon", *stats._TWO_WAY_COLS]
    t = stats.two_way_diff(none, none, ["horizon"], "cov90", d, uo, partial=True)
    assert t.empty and list(t.columns) == ["horizon", *stats._DIFF_COLS]


CONF_TABLE = {"n_series": 6, "origins": CONF19, "horizons": range(1, 7), "targets": TARGETS3[:1]}


@pytest.mark.parametrize("col, other", [("model", "m1_lightgbm"), ("mode", "final"),
                                        ("level", "icb")])
def test_two_way_refuses_a_frame_mixing_slices(col, other):
    rows = scored(**CONF_TABLE)
    d, uo = draws_for(rows)
    mixed = rows.copy()
    mixed.loc[0, col] = other                                   # no duplicate keys
    with pytest.raises(ValueError, match=rf"rows frame holds 2 {col}s outside the cells"):
        stats.two_way(mixed, ["horizon"], "cov90", d, uo)
    with pytest.raises(ValueError, match=rf"rows_b frame holds 2 {col}s"):
        stats.two_way_diff(rows, mixed, ["horizon"], "cov90", d, uo)
    t = stats.two_way(mixed, [col, "horizon"], "cov90", d, uo)  # as a cell: fine
    assert len(t) == 7 and t["n_rows"].sum() == len(rows)


def test_two_way_refuses_asof_and_final_concatenated():
    """The 684-row CONF19 table plus a copy labelled final with cov90 inverted would give
    point 0.5 at every horizon if pooled."""
    rows = scored(**CONF_TABLE)
    both = pd.concat([rows, rows.assign(mode="final", cov90=~rows["cov90"])], ignore_index=True)
    assert len(rows) == 684
    d, uo = draws_for(both)
    with pytest.raises(ValueError, match="2 modes"):
        stats.two_way(both, ["horizon"], "cov90", d, uo)
    t = stats.two_way(both, ["mode", "horizon"], "cov90", d, uo).set_index(["mode", "horizon"])
    asof = stats.two_way(rows, ["horizon"], "cov90", d, uo).set_index("horizon")
    assert np.allclose(t.loc["asof", "point"], asof["point"], rtol=0, atol=1e-15)
    assert np.allclose(t.loc["final", "point"], 1 - asof["point"], rtol=0, atol=1e-15)


def test_two_way_refuses_duplicate_rows():
    rows = scored(**CONF_TABLE)
    d, uo = draws_for(rows)
    dup = pd.concat([rows, rows.sample(50, random_state=0)], ignore_index=True)
    with pytest.raises(ValueError, match="50 duplicate rows"):
        stats.two_way(dup, ["horizon"], "cov90", d, uo)
    with pytest.raises(ValueError, match="rows_a frame has 50 duplicate rows"):
        stats.two_way_diff(dup, rows, ["horizon"], "cov90", d, uo)
    icb = rows.rename(columns={"series": "icb"})                # the key follows series_col
    dup_icb = dup.rename(columns={"series": "icb"})
    assert not stats.two_way(icb, ["horizon"], "cov90", d, uo, series_col="icb").empty
    with pytest.raises(ValueError, match=r"50 duplicate rows on \('icb'"):
        stats.two_way(dup_icb, ["horizon"], "cov90", d, uo, series_col="icb")


def test_two_way_refuses_both_g1_variants_concatenated():
    rows = scored(**CONF_TABLE)
    rows["failed"] = np.random.default_rng(14).random(len(rows)) < 0.05
    issued, dropped = rows, rows[~rows["failed"]]               # hypotheses.variants
    d, uo = draws_for(rows)
    with pytest.raises(ValueError, match="duplicate"):
        stats.two_way(pd.concat([issued, dropped]), ["horizon"], "cov90", d, uo)
    for v in (issued, dropped):
        t = stats.two_way(v, ["horizon"], "cov90", d, uo)
        assert t["n_rows"].tolist() == v.groupby("horizon").size().tolist()


def test_two_way_allows_several_models_as_cells():
    rows = scored(n_series=6, origins=CONF19, horizons=(1, 2), models=("b1_ets", "b2_stl_arima"))
    d, uo = draws_for(rows)
    t = stats.two_way(rows, ["model", "target", "horizon"], "cov90", d, uo)
    assert len(t) == 2 * 3 * 2 and (t["n_rows"] == 6 * 19).all()
    with pytest.raises(ValueError, match="2 models"):
        stats.two_way(rows, ["target", "horizon"], "cov90", d, uo)
    with pytest.raises(ValueError, match="duplicate"):
        stats.two_way(pd.concat([rows, rows.iloc[:1]]), ["model", "target", "horizon"], "cov90",
                      d, uo)


def test_two_way_is_fast_at_conf_scale():
    """About 300 series x 19 units x 6 horizons x 3 targets x 4 models (410,400 rows)."""
    rows = scored(n_series=300, origins=CONF19, horizons=range(1, 7), seed=10,
                  models=("b1_ets", "b2_stl_arima", "m1_lightgbm_v3_raw", "m2d_corr"))
    start = time.perf_counter()
    d, uo = draws_for(rows)
    t = stats.two_way(rows, ["model", "target", "horizon"], "cov90", d, uo)
    elapsed = time.perf_counter() - start
    assert len(t) == 72 and (t["n_rows"] == 300 * 19).all()
    assert elapsed < 10, f"two_way took {elapsed:.1f} s"


# ---- two_way_diff ------------------------------------------------------------------------
def test_two_way_diff_uses_shared_draws():
    a = scored(n_series=15, origins=CONF19, horizons=range(1, 7), p=0.8, seed=11)
    d, uo = draws_for(a)
    same = stats.two_way_diff(a, a, ["horizon"], "cov90", d, uo)
    for c in ("point", "lo", "hi", "lo_within", "hi_within"):
        assert (same[c] == 0).all()
    flip = stats.two_way_diff(a.assign(cov90=False), a.assign(cov90=True), ["horizon"], "cov90",
                              d, uo)
    assert (flip["point"] == 1).all() and (flip["lo"] == 1).all() and (flip["hi"] == 1).all()
    b = a.assign(cov90=np.random.default_rng(12).random(len(a)) < 0.9)
    t = stats.two_way_diff(a, b, ["horizon"], "cov90", d, uo)
    ta, tb = (stats.two_way(x, ["horizon"], "cov90", d, uo) for x in (a, b))
    assert np.allclose(t["point"], tb["point"] - ta["point"], rtol=0, atol=1e-15)
    for c, h in enumerate(t["horizon"]):
        (_, [(Ka, Na)]), (_, [(Kb, Nb)]) = (
            stats._prepare([x[x["horizon"] == h]], [], "cov90", d, uo, "series") for x in (a, b))
        ra, rb = stats._resample(Ka, Na, d), stats._resample(Kb, Nb, d)
        diff = rb[0, :, 0] / rb[1, :, 0] - ra[0, :, 0] / ra[1, :, 0]
        assert [t.loc[c, "lo"], t.loc[c, "hi"]] == list(np.percentile(diff, [2.5, 97.5]))
    assert (t["lo"] < t["point"]).all() and (t["point"] < t["hi"]).all()
    assert (t["zero_den"] == 0).all() and not t["degenerate"].any()


def test_two_way_diff_cell_on_one_side_only_is_empty_not_invented():
    a = scored(n_series=6, origins=CONF19, horizons=(1, 2), seed=13)
    b = a[a["horizon"] == 1]
    d, uo = draws_for(a)
    t = stats.two_way_diff(a, b, ["horizon"], "cov90", d, uo).set_index("horizon")
    assert np.isnan(t.loc[2, ["point", "lo", "hi"]].to_numpy(float)).all()
    assert t.loc[2, "zero_den"] == 1000 and t.loc[2, "n_units"] == 0 and t.loc[2, "degenerate"]
    assert t.loc[1, "point"] == 0 and t.loc[1, "zero_den"] == 0


# ---- verdicts (§7.5) ---------------------------------------------------------------------
BELOW_85, ABOVE_95 = np.nextafter(0.85, 0), np.nextafter(0.95, 1)


def vt(per_h=None, default=(0.90, 0.88, 0.92)) -> pd.DataFrame:
    """A verdict table: horizon, point, lo, hi."""
    r = {h: default for h in range(1, 7)}
    r.update(per_h or {})
    return pd.DataFrame([{"horizon": h, "point": p, "lo": lo, "hi": hi}
                         for h, (p, lo, hi) in r.items()])


@pytest.mark.parametrize("x, status", [(0.85, "inside"), (0.95, "inside"), (0.9, "inside"),
                                       (BELOW_85, "under"), (ABOVE_95, "over")])
def test_band_status_edges_inclusive(x, status):
    assert stats.band_status(x) == status


def test_band_status_and_crosses_refuse_nan():
    with pytest.raises(ValueError):
        stats.band_status(np.nan)
    with pytest.raises(ValueError):
        stats.crosses(np.nan, 0.9)


@pytest.mark.parametrize("lo, hi, expected", [
    (0.85, 0.90, True), (0.80, 0.85, True), (0.95, 0.97, True), (0.80, 0.99, True),
    (np.nextafter(0.85, 1), np.nextafter(0.95, 0), False), (0.80, BELOW_85, False),
    (ABOVE_95, 0.99, False)])
def test_crosses_edges(lo, hi, expected):
    assert stats.crosses(lo, hi) is expected


@pytest.mark.parametrize("per_h, verdict, outside", [
    ({h: (0.9, 0.85, 0.95) for h in range(1, 7)}, "within tolerance", {}),
    ({2: (0.82, 0.80, BELOW_85)}, "outside tolerance", {2: "under"}),
    ({5: (0.97, ABOVE_95, 0.99)}, "outside tolerance", {5: "over"}),
    ({2: (0.82, 0.80, 0.84), 5: (0.97, 0.96, 0.99)}, "outside tolerance",
     {2: "under", 5: "over"}),
    ({3: (0.83, 0.80, 0.85)}, "inconclusive", {}),                      # hi exactly 0.85
    ({4: (0.96, 0.95, 0.97)}, "inconclusive", {}),                      # lo exactly 0.95
    ({1: (0.87, BELOW_85, 0.90)}, "inconclusive", {}),
])
def test_verdict_primary(per_h, verdict, outside):
    assert stats.verdict_primary(vt(per_h)) == {"verdict": verdict, "outside": outside}


def test_verdict_tables_need_horizons_1_to_6_once():
    with pytest.raises(ValueError, match="horizons"):
        stats.verdict_primary(vt().iloc[:5])
    with pytest.raises(ValueError, match="horizons"):
        stats.verdict_h2_m1(pd.concat([vt(), vt().iloc[:1]]))
    assert stats.verdict_h2_m2(vt().set_index("horizon"))["verdict"] == "confirmed"


@pytest.mark.parametrize("per_h, verdict, named", [
    ({1: (0.85, 0.83, 0.87), 6: (0.95, 0.93, 0.97)}, "refuted", {}),   # edges are inside
    ({5: (0.96, 0.955, 0.97)}, "confirmed", {5: "over"}),
    ({6: (0.80, 0.78, 0.82)}, "confirmed", {6: "under"}),
    ({4: (0.84, 0.82, 0.86), 2: (0.97, 0.96, 0.98)}, "confirmed", {2: "over", 4: "under"}),
    ({2: (0.84, 0.82, 0.86)}, "neither", {2: "under"}),
    ({1: (0.97, 0.96, 0.98), 4: (0.85, 0.84, 0.86)}, "neither", {1: "over"}),
])
def test_verdict_h2_m1(per_h, verdict, named):
    v = stats.verdict_h2_m1(vt(per_h))
    assert v["verdict"] == verdict
    assert {h: s for h, s in v["directions"].items() if s != "inside"} == named
    assert set(v["directions"]) == set(range(1, 7)) == set(v["crossings"])


@pytest.mark.parametrize("fn, point, verdict, status", [
    (stats.verdict_h2_m1, 0.85, "refuted", "inside"),
    (stats.verdict_h2_m1, 0.95, "refuted", "inside"),
    (stats.verdict_h2_m1, BELOW_85, "confirmed", "under"),
    (stats.verdict_h2_m1, ABOVE_95, "confirmed", "over"),
    (stats.verdict_h2_m2, 0.85, "confirmed", "inside"),
    (stats.verdict_h2_m2, 0.95, "confirmed", "inside"),
    (stats.verdict_h2_m2, BELOW_85, "refuted", "under"),
    (stats.verdict_h2_m2, ABOVE_95, "refuted", "over"),
])
def test_h2_verdicts_at_the_band_edges(fn, point, verdict, status):
    v = fn(vt({4: (point, point - 0.01, point + 0.01)}))
    assert v["verdict"] == verdict and v["directions"][4] == status


def test_verdict_h2_m2():
    assert stats.verdict_h2_m2(vt({1: (0.85, 0.86, 0.9)}))["verdict"] == "confirmed"
    v = stats.verdict_h2_m2(vt({3: (0.97, 0.96, 0.98), 5: (0.83, 0.80, 0.84)}))
    assert v["verdict"] == "refuted"
    assert {h: s for h, s in v["directions"].items() if s != "inside"} == {3: "over", 5: "under"}
    assert stats.verdict_h2_m2(None, evaluable=False) == {
        "verdict": "not evaluable", "directions": {}, "crossings": {}, "fragile": None}


NO, CROSS85, CROSS95 = (0.90, 0.88, 0.92), (0.86, 0.84, 0.88), (0.94, 0.93, 0.96)


@pytest.mark.parametrize("fn, per_h, verdict, fragile", [
    # H2 M1 confirmed: fragile only if every outside h >= 4 crosses
    (stats.verdict_h2_m1, {4: (0.80, 0.78, 0.83), 5: (0.83, 0.80, 0.86)}, "confirmed", False),
    (stats.verdict_h2_m1, {4: (0.83, 0.80, 0.86), 5: (0.84, 0.81, 0.86)}, "confirmed", True),
    (stats.verdict_h2_m1, {1: CROSS85, 4: (0.80, 0.78, 0.83)}, "confirmed", False),
    # H2 M1 refuted: fragile if any h crosses
    (stats.verdict_h2_m1, {}, "refuted", False),
    (stats.verdict_h2_m1, {2: CROSS95}, "refuted", True),
    # H2 M1 neither: any h >= 4 crosses, or every outside h <= 3 crosses
    (stats.verdict_h2_m1, {1: (0.80, 0.78, 0.82), 2: (0.84, 0.82, 0.86)}, "neither", False),
    (stats.verdict_h2_m1, {1: (0.84, 0.82, 0.86), 2: (0.84, 0.83, 0.87)}, "neither", True),
    (stats.verdict_h2_m1, {1: (0.80, 0.78, 0.82), 5: CROSS95}, "neither", True),
    (stats.verdict_h2_m1, {1: (0.80, 0.78, 0.82), 3: CROSS85}, "neither", False),
    # H2 M2 confirmed: any h crosses
    (stats.verdict_h2_m2, {}, "confirmed", False),
    (stats.verdict_h2_m2, {6: CROSS85}, "confirmed", True),
    # H2 M2 refuted: every outside h crosses
    (stats.verdict_h2_m2, {2: (0.80, 0.78, 0.82), 5: (0.96, 0.94, 0.98), 1: CROSS85},
     "refuted", False),
    (stats.verdict_h2_m2, {2: (0.84, 0.82, 0.86), 5: (0.96, 0.94, 0.98)}, "refuted", True),
])
def test_fragility_table(fn, per_h, verdict, fragile):
    v = fn(vt(per_h))
    assert v["verdict"] == verdict and v["fragile"] is fragile


# ---- leave-one-origin-out, seasons and DEV ranges (§7.3, §7.13) ---------------------------
@pytest.mark.parametrize("values, fragile", [
    ([-0.2, -0.15, -0.1], True), ([-0.15, -0.1], True), ([-0.2, -0.15], True),
    ([-0.2, np.nextafter(-0.15, -1)], False), ([-0.14, 0.1], False), ([-0.3], False), ([], False)])
def test_range_fragile(values, fragile):
    assert stats.range_fragile(values, -0.15) is fragile


@pytest.mark.parametrize("values", [[np.nan, -0.2, -0.1], [np.nan, -0.2], [np.nan], [None, 0.1]])
def test_range_fragile_refuses_a_non_evaluable_subset(values):
    with pytest.raises(ValueError, match="NaN"):
        stats.range_fragile(values, -0.15)


def test_loo_drops_each_origin_once():
    rows = scored(n_series=4, origins=W5)
    seen = []

    def fn(sub):
        seen.append(set(sub["origin"]))
        return {"n": len(sub), "origins": sub["origin"].nunique()}

    out = stats.loo(fn, rows, list(W5)[::-1])
    assert list(out.columns) == ["dropped", "n", "origins"]
    assert out["dropped"].tolist() == [T(o) for o in W5]
    assert (out["n"] == len(rows) // 5 * 4).all() and (out["origins"] == 4).all()
    assert all(o not in s and len(s) == 4 for o, s in zip(out["dropped"], seen))
    for few in ([W5[0]], []):
        empty = stats.loo(fn, rows, few)
        assert empty.empty and list(empty.columns) == ["dropped"]
    as_dates = rows.assign(origin=[o.date() for o in rows["origin"]])     # object column
    assert stats.loo(fn, as_dates, W5)["n"].tolist() == out["n"].tolist()


def test_loo_refuses_an_origin_without_rows():
    """Dropping an absent origin would report the full sample as a subset."""
    rows = scored(n_series=4, origins=W5)
    rest = rows[rows["origin"] != T("2024-01-01")]
    with pytest.raises(ValueError, match=r"\['2024-01'\]"):
        stats.loo(lambda sub: {"n": len(sub)}, rest, W5)
    four = stats.loo(lambda sub: {"n": len(sub)}, rest, W5[1:])
    assert (four["n"] == len(rest) // 4 * 3).all()
    dry = scored(n_series=4, origins=[date(2023, 10, 1)])       # §10: one winter-h3 origin
    with pytest.raises(ValueError, match=r"\['2023-07', '2023-08', '2023-09', '2023-11'"):
        stats.loo(lambda sub: {"n": len(sub)}, dry, DRY)
    assert stats.loo(lambda sub: {"n": len(sub)}, dry, sorted(set(dry["origin"]))).empty


@pytest.mark.parametrize("period, label", [
    ("2018-12-01", "2018/19"), ("2019-01-01", "2018/19"), ("2019-03-01", "2018/19"),
    (date(2022, 12, 1), "2022/23"), (T("2000-02-01"), "1999/00"), ("2023-12-01", "2023/24")])
def test_season(period, label):
    assert stats.season(period) == label


@pytest.mark.parametrize("period", ["2018-11-01", "2019-04-01", "2021-11-01"])
def test_season_refuses_non_winter_months(period):
    with pytest.raises(ValueError, match="winter"):
        stats.season(period)


def test_dev_range_and_outside():
    assert stats.dev_range([0.3, np.nan, 0.1, 0.2]) == (0.1, 0.3)
    assert all(np.isnan(x) for x in stats.dev_range([np.nan]) + stats.dev_range([]))
    assert not stats.outside(0.1, 0.1, 0.3) and not stats.outside(0.3, 0.1, 0.3)
    assert stats.outside(np.nextafter(0.1, 0), 0.1, 0.3) and stats.outside(0.31, 0.1, 0.3)
    with pytest.raises(ValueError):
        stats.outside(0.2, *stats.dev_range([]))


def test_local_constants_match_the_harness():
    from nhs_ae.evaluate.harness import WINTER_MONTHS
    from nhs_ae.models.base import HORIZONS
    assert stats.WINTER_MONTHS == WINTER_MONTHS and stats.HORIZONS == HORIZONS
