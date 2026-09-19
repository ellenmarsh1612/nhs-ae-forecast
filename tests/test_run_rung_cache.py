"""run_rung never hands back a cached table that holds a different set of origins."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from nhs_ae.evaluate import stage_e
from nhs_ae.models import m2


def test_cached_table_with_other_origins_raises(tmp_path):
    rung = m2.M2D_CORR
    pd.DataFrame({"origin": [pd.Timestamp("2018-04-01")], "value": [1.0]}).to_parquet(
        tmp_path / f"forecasts_{rung.name}.parquet")
    pd.DataFrame({"origin": ["2018-04-01"], "rhat_max": [1.0]}).to_csv(
        tmp_path / f"diagnostics_{rung.name}.csv", index=False)
    with pytest.raises(RuntimeError, match="origins"):
        stage_e.run_rung(rung, origins=[date(2018, 4, 1), date(2018, 5, 1)], work=tmp_path)
    fc, _ = stage_e.run_rung(rung, origins=[date(2018, 4, 1)], work=tmp_path)   # exact match: returned
    assert len(fc) == 1
