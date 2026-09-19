"""P11 guards inside calibration and reconciliation (spec §4): ``online.first_release``,
``online.calibrate`` and ``stage_f._median_errors`` / ``reconcile_frames`` raise on sealed rows
without the token, pass DEV inputs shaped as Stages D, E and F build them, and hand the token
to ``splits.assert_not_sealed``. Synthetic data only; the token is a dummy that the spy never
forwards; ``conftest`` holds the seal in its pre-run state (``splits._post_run`` False)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy import stats
from test_calibrate import synthetic

from nhs_ae.calibrate import online
from nhs_ae.evaluate import splits, stage_f
from nhs_ae.models.base import QUANTILES

TOKEN = "t" * 40
DEV_END = pd.Timestamp("2023-12-01")
LAST_DEV_PERIOD = pd.Timestamp("2023-11-01")   # the latest period published by the DEV end


@pytest.fixture
def spy(monkeypatch):
    """Every call of ``splits.assert_not_sealed`` as (frame, token); the call passes."""
    calls = []

    def fake(*args, **kwargs):
        calls.append((args[0], args[1] if len(args) > 1 else kwargs.get("unseal_token")))
    monkeypatch.setattr(splits, "assert_not_sealed", fake)
    return calls


def _n_sealed(frame: pd.DataFrame) -> int:
    return int(splits.sealed_mask(frame).sum())


# ---- first_release -----------------------------------------------------------------------
class _AsOf:
    """``load_asof`` stand-in: two providers, every month from 2023-01 to the one before the
    origin, as published at the origin."""

    def __init__(self, origin):
        self.origin = pd.Timestamp(origin)

    def panel(self, target, level):
        idx = pd.date_range("2023-01-01", self.origin - pd.DateOffset(months=1), freq="MS")
        return pd.DataFrame({"P1": 100.0, "P2": 200.0}, index=idx)


def _first_release(monkeypatch, end, **kw):
    monkeypatch.setattr(online, "load_asof", lambda o, mode, v, rmap: _AsOf(o))
    origins = pd.date_range("2023-06-01", end, freq="MS")
    return online.first_release(None, origins, targets=("att_all",),
                                region_map=pd.Series(dtype=object), **kw)


def test_first_release_passes_dev_and_raises_on_a_sealed_period_without_a_token(monkeypatch):
    fr = _first_release(monkeypatch, DEV_END)                 # as Stages D, E: origins to 2023-12
    assert fr["period"].max() == LAST_DEV_PERIOD and fr["resolved"].max() == DEV_END
    with pytest.raises(splits.SealedOriginError):
        _first_release(monkeypatch, "2024-02-01")                 # holds period 2024-01


def test_first_release_hands_its_token_to_the_guard(monkeypatch, spy):
    fr = _first_release(monkeypatch, "2024-03-01", unseal_token=TOKEN)
    assert len(spy) == 1
    frame, token = spy[0]
    assert token == TOKEN and list(frame.columns) == ["period"]
    assert set(frame["period"]) == set(fr["period"]) and _n_sealed(frame) > 0


# ---- calibrate ---------------------------------------------------------------------------
def _dev_style(n_origins=36, n_series=6):
    """``synthetic`` moved so that its last origin is 2023-12 (horizons 2 and 3 reach 2024
    targets). Returns the forecasts, the first releases as Stages D, E and F build them
    (resolved by 2023-12, so periods to 2023-11) and the full first releases, which run into
    the sealed periods."""
    fc, fr = synthetic(n_origins=n_origins, n_series=n_series)
    last = fc["origin"].max()
    shift = pd.DateOffset(months=(DEV_END.year - last.year) * 12 + DEV_END.month - last.month)
    for f in (fc, fr):
        for col in ("origin", "period", "resolved"):
            if col in f:
                f[col] = f[col] + shift
    return fc, fr[fr["resolved"] <= DEV_END].reset_index(drop=True), fr


def test_calibrate_passes_dev_style_inputs():
    fc, fr, _ = _dev_style()
    assert fc["origin"].max() == DEV_END and (fc["period"] >= pd.Timestamp("2024-01-01")).any()
    assert fr["period"].max() == LAST_DEV_PERIOD
    cal = online.calibrate(fc, fr)
    assert len(cal) == 3 * len(fc) and cal["value"].notna().all()


@pytest.mark.parametrize("case", ["resolved", "unresolved", "failed"])
def test_calibrate_raises_on_any_sealed_first_release_without_a_token(case):
    """A first release of a sealed period raises however ``valid`` would treat it: resolved,
    never resolved (NaT), or attached to a G1-failed forecast."""
    fc, _, fr = _dev_style()
    sealed = fr["period"] >= pd.Timestamp("2024-01-01")
    failed = None
    if case == "unresolved":
        fr.loc[sealed, "resolved"] = pd.NaT
    elif case == "failed":
        keys = ["origin", "target", "series", "horizon"]
        failed = fc.loc[fc["period"] >= pd.Timestamp("2024-01-01"), keys].drop_duplicates()
    with pytest.raises(splits.SealedOriginError):
        online.calibrate(fc, fr, methods=("pooled",), failed=failed)


def test_calibrate_checks_every_row_with_a_first_release_and_hands_on_the_token(spy):
    fc, _, fr = _dev_style()
    online.calibrate(fc, fr, methods=("pooled",), unseal_token=TOKEN)
    assert len(spy) == 1                                        # one target
    frame, token = spy[0]
    assert token == TOKEN and list(frame.columns) == ["origin", "period"]
    with_first = (fc[["origin", "series", "horizon", "period"]].drop_duplicates()
                  .merge(fr[["series", "period"]], on=["series", "period"]))
    assert len(frame) == len(with_first) and _n_sealed(frame) > 0


# ---- stage_f: median errors and MinT -----------------------------------------------------
ICB_OF = {"P1": "I1", "P2": "I1", "P3": "I2"}
REGION_OF = {"I1": "R1", "I2": "R1"}
BASE = {"P1": 100.0, "P2": 200.0, "P3": 300.0, "I1": 300.0, "I2": 300.0, "R1": 600.0,
        "ENGLAND": 600.0}
LEVEL = {"P1": "provider", "P2": "provider", "P3": "provider", "I1": "icb", "I2": "icb",
         "R1": "region", "ENGLAND": "england"}


def _tree(origins, last_period):
    """Calibrated forecasts at horizons 1 and 2 (period = origin + h − 1) for every series of a
    three-provider tree, and first releases published the month after, up to ``last_period``."""
    rng = np.random.default_rng(0)
    z = stats.norm.ppf(QUANTILES)
    cal, fr = [], []
    for o in origins:
        for s, b in BASE.items():
            for h in (1, 2):
                p = o + pd.DateOffset(months=h - 1)
                cal += [(o, "asof", "m+pooled", LEVEL[s], "att_all", s, h, p, q, v, 1.0)
                        for q, v in zip(QUANTILES, b * np.exp(0.05 * z))]
            if o <= pd.Timestamp(last_period):
                y = b * np.exp(rng.normal(0, 0.05))
                fr.append(("att_all", s, o, y, o + pd.DateOffset(months=1), LEVEL[s]))
    cal = pd.DataFrame(cal, columns=stage_f.COLS)
    fr = pd.DataFrame(fr, columns=["target", "series", "period", "y_first", "resolved", "level"])
    return ({lv: cal[cal["level"] == lv] for lv in stage_f.LEVELS},
            {lv: fr[fr["level"] == lv] for lv in stage_f.LEVELS})


DEV_ORIGINS = pd.date_range("2023-05-01", DEV_END, freq="MS")
RUN_ORIGINS = pd.date_range("2023-07-01", "2024-02-01", freq="MS")


def test_median_errors_pass_dev_and_raise_on_sealed_rows_without_a_token():
    cal, fr = _tree(DEV_ORIGINS, LAST_DEV_PERIOD)            # 2023-12's h=2 reaches 2024-01
    assert (cal["provider"]["period"] >= pd.Timestamp("2024-01-01")).any()
    e = stage_f._median_errors(cal["provider"], fr["provider"], "provider")
    assert len(e) and e["err"].notna().all()
    cal, fr = _tree(RUN_ORIGINS, "2024-02-01")
    with pytest.raises(splits.SealedOriginError):
        stage_f._median_errors(cal["provider"], fr["provider"], "provider")


def test_reconcile_frames_passes_dev_and_raises_on_sealed_rows_without_a_token(monkeypatch):
    monkeypatch.setattr(stage_f, "TARGETS", ["att_all"])
    cal, fr = _tree(DEV_ORIGINS, LAST_DEV_PERIOD)
    rec = stage_f.reconcile_frames(cal, fr, None, DEV_ORIGINS, ICB_OF, REGION_OF)
    assert rec["origin"].max() == DEV_END
    cal, fr = _tree(RUN_ORIGINS, "2024-02-01")
    with pytest.raises(splits.SealedOriginError):
        stage_f.reconcile_frames(cal, fr, None, RUN_ORIGINS, ICB_OF, REGION_OF)


def test_reconcile_frames_hands_the_token_to_every_median_error_check(monkeypatch, spy):
    monkeypatch.setattr(stage_f, "TARGETS", ["att_all"])
    cal, fr = _tree(RUN_ORIGINS, "2024-02-01")
    seen = []
    rec = stage_f.reconcile_frames(cal, fr, None, RUN_ORIGINS, ICB_OF, REGION_OF,
                                   errs_guard=lambda merged: seen.append(len(merged)),
                                   unseal_token=TOKEN)
    assert rec["origin"].max() == RUN_ORIGINS[-1]
    assert len(spy) == len(stage_f.LEVELS) == len(seen)      # one check per level, as the hook
    assert all(tok == TOKEN and list(f.columns) == ["origin", "period"] for f, tok in spy)
    assert [len(f) for f, _ in spy] == seen                  # the merged rows, all of them
    assert sum(_n_sealed(f) for f, _ in spy) > 0
