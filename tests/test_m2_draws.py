"""Draw storage for M2 fits: exact integer paths, the posterior subset, atomic npz writes."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from nhs_ae.models import m2_draws

xr = pytest.importorskip("xarray")


def test_integer_paths_are_exact_and_refuse_non_counts():
    sims = {"att_all": np.array([[[3.0, 4.0]], [[0.0, 12.0]]])}
    out = m2_draws.integer_paths(sims)
    assert out["att_all"].dtype == np.int32 and np.array_equal(out["att_all"], sims["att_all"])
    with pytest.raises(ValueError):
        m2_draws.integer_paths({"att_all": np.array([[[3.5]]])})


def test_posterior_subset_keeps_scalars_and_the_final_month():
    rng = np.random.default_rng(0)
    post = xr.Dataset({"kappa_all": (("chain", "draw"), rng.random((2, 5))),
                       "v_all": (("chain", "draw", "i", "t"), rng.random((2, 5, 3, 7)))})
    out = m2_draws.posterior_subset(SimpleNamespace(posterior=post), n_months=7)
    assert out["kappa_all"].shape == (2, 5)
    assert np.array_equal(out["v_all__last"], post["v_all"].values[..., -1])
    assert np.allclose(out["v_all__mean_path"], post["v_all"].values.mean(axis=(0, 1)))
    assert "v_all" not in out


def test_save_npz_roundtrip(tmp_path):
    path = tmp_path / "d" / "2023-04.npz"
    size = m2_draws.save_npz(path, {"a": np.arange(4, dtype=np.int32), "icbs": np.array(["E1", "E2"])})
    with np.load(path) as z:
        assert size == path.stat().st_size and z["a"].tolist() == [0, 1, 2, 3] and z["icbs"].tolist() == ["E1", "E2"]
    assert not list(path.parent.glob("*.tmp.npz"))
