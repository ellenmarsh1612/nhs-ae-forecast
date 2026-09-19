"""PIT bin assignment from the nine registered quantile levels."""

from __future__ import annotations

import numpy as np

from nhs_ae.evaluate.stage_e_pit import EXPECTED, pit_bin

Q = np.array([[10, 20, 30, 40, 50, 60, 70, 80, 90]], dtype=float)


def test_expected_masses_are_the_level_gaps():
    assert np.allclose(EXPECTED, [0.025, 0.025, 0.05, 0.15, 0.25, 0.25, 0.15, 0.05, 0.025, 0.025])


def test_untied_outturns_land_in_the_bracketing_bin():
    rng = np.random.default_rng(0)
    q = np.repeat(Q, 3, axis=0)
    b, tied = pit_bin(q, np.array([5.0, 45.0, 95.0]), rng)
    assert b.tolist() == [0, 4, 9] and not tied.any()


def test_single_tie_goes_to_either_neighbouring_bin():
    rng = np.random.default_rng(0)
    q = np.repeat(Q, 400, axis=0)
    b, tied = pit_bin(q, np.full(400, 50.0), rng)                 # y equals the median exactly
    assert tied.all() and set(b.tolist()) == {4, 5}


def test_multiple_ties_spread_over_the_tied_levels():
    rng = np.random.default_rng(0)
    q = np.repeat(np.array([[10, 20, 20, 20, 50, 60, 70, 80, 90]], dtype=float), 2000, axis=0)
    b, _ = pit_bin(q, np.full(2000, 20.0), rng)                    # ties at levels 0.05, 0.10, 0.25
    assert set(b.tolist()) == {2, 3}
    assert abs(np.mean(b == 3) - 0.15 / 0.20) < 0.05               # in proportion to bin mass
