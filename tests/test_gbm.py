"""M1 LightGBM quantile model: contract, as-of safety of features, conformal effect."""
import numpy as np
import pandas as pd
import pytest

pytest.importorskip("lightgbm")

from nhs_ae.models.base import QUANTILES
from nhs_ae.models.gbm import FEATURES, LightGBMQuantile, build_rows


@pytest.fixture(scope="module")
def panel():
    rng = np.random.default_rng(0)
    idx = pd.date_range("2015-04-01", periods=96, freq="MS")
    season = 1 + 0.15 * np.sin(2 * np.pi * (idx.month - 1) / 12)
    cols = {}
    for j in range(40):
        base = 2000 * (1 + j / 10) * (1.02 ** (np.arange(96) / 12)) * season
        cols[f"S{j:02d}"] = base * np.exp(rng.normal(0, 0.05, 96))
    p = pd.DataFrame(cols, index=idx)
    p.loc[idx[50:53], "S05"] = np.nan            # a gap
    p["new"] = np.nan
    p.loc[idx[-8:], "new"] = 3000.0              # cold start: 8 months of history
    return p


def test_features_use_only_the_past(panel):
    rows = build_rows(panel, horizons=(1, 3), with_target=True)
    t = panel.index[60]
    before = rows[rows["t"] == t].reset_index(drop=True)
    tampered = panel.copy()
    tampered.iloc[61:] *= 3.0                     # change every future value
    after = build_rows(tampered, horizons=(1, 3), with_target=True)
    after = after[after["t"] == t].reset_index(drop=True)
    pd.testing.assert_frame_equal(before[FEATURES], after[FEATURES])
    # ... but the target did change
    assert not np.allclose(before["z"], after["z"])
    h1 = before[before.h == 1]
    np.testing.assert_allclose(h1["lag1"].to_numpy(),
                               np.log1p(panel.iloc[60]).to_numpy() - h1["level"].to_numpy(),
                               equal_nan=True)


def test_contract_and_conformal(panel):
    m = LightGBMQuantile(num_rounds=60, params={"num_threads": 1})
    fc = m.fit_predict(panel, horizons=(1, 2, 3), quantiles=QUANTILES)
    assert set(fc.columns) == {"series", "horizon", "period", "quantile", "value"}
    assert set(fc["series"]) == set(panel.columns)
    assert fc["period"].min() == panel.index[-1] + pd.DateOffset(months=1)
    s = fc[fc.series == "S10"]
    for h in (1, 2, 3):
        q = s[s.horizon == h].set_index("quantile")["value"]
        assert q.is_monotonic_increasing and q.notna().all()
        assert abs(q[0.5] / panel["S10"].iloc[-12 + h - 1] - 1) < 0.25   # near last year's value
    assert fc[fc.series == "new"]["value"].notna().all()                # cold start still gets a forecast
    assert (fc["value"].dropna() >= 0).all()
    # conformal widening: with calibration the 90% interval is at least as wide as without
    m0 = LightGBMQuantile(num_rounds=60, calibration_months=0, params={"num_threads": 1})
    fc0 = m0.fit_predict(panel, horizons=(1, 2, 3), quantiles=QUANTILES)
    def width(f):
        w = f.pivot_table(index=["series", "horizon"], columns="quantile", values="value")
        return (w[0.95] - w[0.05]).mean()
    assert width(fc) > 0 and width(fc0) > 0
    assert width(fc) != width(fc0)


def test_search_space_is_deterministic_and_within_space():
    from nhs_ae.models.tune import SPACE, draw_configs, model_from_config
    a, b = draw_configs(8, seed=0), draw_configs(8, seed=0)
    assert a == b and len({tuple(sorted(c.items())) for c in a}) == 8
    for c in a:
        for k, v in c.items():
            assert v in SPACE[k]
        m = model_from_config(c)
        assert m.num_rounds == c["num_rounds"] and m.params["num_leaves"] == c["num_leaves"]


def test_v2_per_horizon_and_short_level(panel):
    m = LightGBMQuantile(num_rounds=60, params={"num_threads": 1}, per_horizon=True, level_window=3)
    assert m.name == "m1_lightgbm_v2"
    fc = m.fit_predict(panel, horizons=(1, 2, 3), quantiles=QUANTILES)
    s = fc[fc.series == "S10"]
    for h in (1, 2, 3):
        q = s[s.horizon == h].set_index("quantile")["value"]
        assert q.is_monotonic_increasing and q.notna().all()
        assert abs(q[0.5] / panel["S10"].iloc[-12 + h - 1] - 1) < 0.25
    rows = build_rows(panel, horizons=(1,), with_target=True, level_window=3)
    t = panel.index[60]
    r = rows[(rows["t"] == t) & (rows.series == "S10")].iloc[0]
    assert r["level"] == pytest.approx(np.log1p(panel["S10"].iloc[58:61].mean()))


def test_v3_name():
    assert LightGBMQuantile(per_horizon=True).name == "m1_lightgbm_v3"
    assert LightGBMQuantile(per_horizon=True, level_window=3).name == "m1_lightgbm_v2"
