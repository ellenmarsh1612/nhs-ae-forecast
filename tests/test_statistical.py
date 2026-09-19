"""B1 ETS and B2 STL+ARIMA on synthetic series (statsmodels required)."""
import numpy as np
import pandas as pd
import pytest

pytest.importorskip("statsmodels")

from nhs_ae.models.base import QUANTILES
from nhs_ae.models.statistical import ETS, STLArima


@pytest.fixture(scope="module")
def panel():
    rng = np.random.default_rng(0)
    idx = pd.date_range("2016-04-01", periods=72, freq="MS")
    season = 1 + 0.15 * np.sin(2 * np.pi * (idx.month - 1) / 12)
    a = 10_000 * (1.03 ** (np.arange(72) / 12)) * season * (1 + rng.normal(0, 0.02, 72))
    p = pd.DataFrame({"a": a}, index=idx)
    p["gap"] = p["a"] * 0.5
    p.loc[idx[30:33], "gap"] = np.nan          # three missing months inside the history
    p["short"] = np.nan
    p.loc[idx[-10:], "short"] = 500.0          # too little history
    p["ended"] = p["a"]
    p.loc[idx[-1], "ended"] = np.nan           # last month missing
    return p


@pytest.mark.parametrize("model_cls", [ETS, STLArima])
def test_statistical_models_contract(panel, model_cls):
    fc = model_cls().fit_predict(panel, horizons=(1, 2, 3), quantiles=QUANTILES)
    assert set(fc.columns) == {"series", "horizon", "period", "quantile", "value"}
    assert set(fc["series"]) == set(panel.columns)
    assert fc["period"].min() == panel.index[-1] + pd.DateOffset(months=1)
    a = fc[fc.series == "a"]
    assert a["value"].notna().all()
    for h in (1, 2, 3):
        q = a[a.horizon == h].set_index("quantile")["value"]
        assert q.is_monotonic_increasing
        # sensible: median within 20% of the same month last year grown 3%
        last_year = panel["a"].iloc[-12 + h - 1] * 1.03
        assert abs(q[0.5] / last_year - 1) < 0.2
    # intervals widen with horizon
    w = a.groupby("horizon").apply(lambda g: g.set_index("quantile")["value"][0.95] - g.set_index("quantile")["value"][0.05], include_groups=False)
    assert w[3] > w[1]
    # gaps inside the history are fine; too short and no last value are not
    assert fc[fc.series == "gap"]["value"].notna().all()
    assert fc[fc.series == "short"]["value"].isna().all()
    assert fc[fc.series == "ended"]["value"].isna().all()
    assert (fc["value"].dropna() >= 0).all()


def test_ets_prefers_multiplicative_only_when_positive(panel):
    m = ETS()
    y = panel["a"].copy(); y.index.freq = "MS"
    assert m._fit_one(y) is not None
    y0 = y.copy(); y0.iloc[5] = 0.0
    res = m._fit_one(y0)
    assert res is not None and res.model.error == "add"
