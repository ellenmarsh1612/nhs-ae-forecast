"""Forecasting models (phase 1, weeks 2–4).

Order of implementation, cheapest first:
1. baselines.py   – B0 seasonal naive with trailing growth. The MASE reference.
2. statistical.py – B1 ETS and B2 STL+ARIMA, per series (statsmodels).
3. gbm.py         – global LightGBM, quantile and Tweedie objectives, direct multi-horizon,
                    conformalised intervals.
4. bayes.py       – hierarchical model in PyMC: provider random effects, shared seasonal
                    structure, admission rate linked to attendances. Coherent by
                    construction (aggregate posterior samples up the tree); partial pooling
                    handles post-merger cold starts.
5. foundation.py  – optional zero-shot Chronos / TimesFM comparison.

Every model implements ``fit_predict(panel, horizons, quantiles) -> quantile table`` with
the schema in base.py so evaluate/ can treat them identically. ``MODELS`` maps the CLI
names to classes.
"""

from functools import partial

from nhs_ae.models.baselines import SeasonalNaive
from nhs_ae.models.enbpi import EnbPI
from nhs_ae.models.gbm import LightGBMQuantile
from nhs_ae.models.statistical import ETS, STLArima

MODELS = {"b0": SeasonalNaive, "b1": ETS, "b2": STLArima, "m1": LightGBMQuantile,
          "m1_tuned": partial(LightGBMQuantile, tuned=True),
          "m1_v2": partial(LightGBMQuantile, tuned=True, per_horizon=True, level_window=3),
          "m1_v3": partial(LightGBMQuantile, tuned=True, per_horizon=True),
          # Stage D: v3 without its in-model conformal step, for downstream calibration
          "m1_v3_raw": partial(LightGBMQuantile, tuned=True, per_horizon=True, conformal=False),
          "m1_enbpi": EnbPI}
