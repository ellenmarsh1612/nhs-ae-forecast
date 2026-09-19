"""Live command: the horizon map, the snapshot guard and the ship-blocking checks."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from nhs_ae import live
from nhs_ae.models.base import QUANTILES

REGIONS = pd.Series({"I1": "R1", "I2": "R1", "I3": "R2"})
ORIGIN = date(2026, 10, 1)


def test_winter_sits_at_h3_to_h6_from_a_2026_10_origin():
    p = live.expected_periods(ORIGIN)
    assert [f"{p[h]:%Y-%m}" for h in (1, 3, 4, 5, 6)] == ["2026-10", "2026-12", "2027-01", "2027-02", "2027-03"]
    live.check_horizons(ORIGIN, p)
    shifted = {h: v - pd.DateOffset(months=1) for h, v in p.items()}     # training one month short
    with pytest.raises(live.ShipBlock):
        live.check_horizons(ORIGIN, shifted)


def test_snapshot_must_be_the_latest_vintage_on_the_as_of_date():
    v = pd.DataFrame({"snapshot": pd.to_datetime(["2026-08-13", "2026-09-10"])})
    with pytest.raises(live.ShipBlock, match="not the latest"):          # 2026-10 needs the 2026-10-08 vintage
        live.load_live(ORIGIN, pd.Timestamp("2026-10-08"), v)
    with pytest.raises(live.ShipBlock, match="after the as-of"):
        live.load_live(date(2026, 9, 1), pd.Timestamp("2026-09-11"), v)
    with pytest.raises(live.ShipBlock, match="sealed"):
        live.load_live(date(2025, 3, 1), pd.Timestamp("2025-03-13"), v)


def _fc(scale_region: float = 1.0) -> pd.DataFrame:
    """Coherent medians: each region is the sum of its ICBs, England the sum of regions."""
    rows = []
    base = {"I1": 100.0, "I2": 200.0, "I3": 50.0, "R1": 300.0 * scale_region, "R2": 50.0, "ENGLAND": 350.0}
    level = {"I1": "icb", "I2": "icb", "I3": "icb", "R1": "region", "R2": "region", "ENGLAND": "england"}
    for s, m in base.items():
        for t in live.TARGETS:
            for h, per in live.expected_periods(ORIGIN).items():
                for q, z in zip(QUANTILES, np.linspace(-1, 1, len(QUANTILES)), strict=True):
                    rows.append({"level": level[s], "target": t, "series": s, "horizon": h, "period": per,
                                 "quantile": q, "value": m * (1 + 0.1 * z)})
    return pd.DataFrame(rows)


def test_clean_forecast_passes_every_check():
    assert live.ship_checks(_fc(), ORIGIN, REGIONS) == []


def test_each_check_blocks():
    f = _fc()
    zero = (f["series"] == "I3") & (f["horizon"] == 2) & (f["target"] == "att_all")
    f.loc[zero, "value"] = 0.0
    assert any("G1" in x for x in live.ship_checks(f, ORIGIN, REGIONS))
    f = _fc()
    f.loc[(f["series"] == "I1") & (f["quantile"] == 0.975), "value"] = 1.0
    assert any("crossed" in x for x in live.ship_checks(f, ORIGIN, REGIONS))
    assert any("absent" in x for x in live.ship_checks(_fc()[lambda d: d["series"] != "I2"], ORIGIN, REGIONS))
    assert any("coherence gap at region" in x for x in live.ship_checks(_fc(scale_region=1.05), ORIGIN, REGIONS))
