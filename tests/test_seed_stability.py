"""Seed-stability statistic: ratio to the original fit's 50% width, the verdict rule, the
embargo exclusion and the zero-width convention (docs/sampling_rule_draft.md)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from nhs_ae.evaluate import seed_stability as ss

Q = [0.025, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.975]


def _fits(shift_by: float, period: str = "2023-06-01", width: float = 20.0) -> pd.DataFrame:
    base = 100 + np.linspace(-2, 2, len(Q)) * width / 1.349   # q0.75 - q0.25 is about `width`
    rows = []
    for shift, add in ((0, 0.0), (ss.SHIFT, shift_by)):
        for q, v in zip(Q, base, strict=True):
            rows.append({"model": "m", "shift": shift, "origin": pd.Timestamp("2023-04-01"), "level": "icb",
                         "target": "att_all", "series": "E1", "horizon": 3, "period": pd.Timestamp(period),
                         "quantile": q, "value": v + add})
    return pd.DataFrame(rows)


def test_ratio_is_difference_over_original_50pc_width():
    f = _fits(shift_by=2.0)
    w50 = f.query("shift == 0 and quantile == 0.75")["value"].iloc[0] - f.query("shift == 0 and quantile == 0.25")["value"].iloc[0]
    r = ss.ratios(f)
    assert np.allclose(r["ratio"], 2.0 / w50)


def test_verdict_limits_are_strict():
    assert ss.verdict(pd.Series({"median": 0.0499, "p95": 0.1999})) == "STABLE"
    assert ss.verdict(pd.Series({"median": 0.05, "p95": 0.10})) == "MATERIAL"
    assert ss.verdict(pd.Series({"median": 0.01, "p95": 0.20})) == "MATERIAL"


def test_sealed_target_periods_are_dropped():
    assert ss.ratios(_fits(shift_by=1.0, period="2024-01-01")).empty


def test_zero_width_counts_against_stability():
    f = _fits(shift_by=0.0, width=0.0)
    f.loc[(f["shift"] == ss.SHIFT) & (f["quantile"] == 0.5), "value"] += 1.0
    r = ss.ratios(f)
    assert np.isinf(r.loc[r["quantile"] == 0.5, "ratio"]).all()
    assert (r.loc[r["quantile"] != 0.5, "ratio"] == 0).all()
    s = ss.summarise(r)
    assert s["infinite"].iloc[0] == 1 and np.isfinite(s["p95"].iloc[0])
