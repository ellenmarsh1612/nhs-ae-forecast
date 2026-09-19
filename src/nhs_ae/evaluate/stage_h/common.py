"""Constants, hashing helpers and the run context shared by the Stage H modules.

Every date the runner uses lives here (design §2.4: no literal 2025-09 anywhere else).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from nhs_ae.config import PROCESSED_DIR, PROJECT_ROOT
from nhs_ae.evaluate.splits import split_origins
from nhs_ae.ingest.recover import month_range

# ---- origins -----------------------------------------------------------------------------
CONF21: tuple[date, ...] = tuple(split_origins("conf"))                 # 2024-01 .. 2025-09
CONF19: tuple[date, ...] = tuple(month_range(date(2024, 1, 1), date(2025, 7, 1)))   # D7
D7_FOLD: dict[date, date] = {date(2025, 8, 1): date(2025, 7, 1), date(2025, 9, 1): date(2025, 7, 1)}
W5: tuple[date, ...] = (date(2024, 1, 1), date(2024, 10, 1), date(2024, 11, 1), date(2024, 12, 1),
                        date(2025, 1, 1))                               # winter-h3 origins in CONF19
DEV: tuple[date, ...] = tuple(split_origins("dev"))                     # 2018-04 .. 2023-12
DEV_WINTER_H3: tuple[date, ...] = tuple(o for o in DEV if o.month in (10, 11, 12, 1))  # h3 in Dec-Mar
DRY: tuple[date, ...] = tuple(month_range(date(2023, 7, 1), date(2023, 12, 1)))
INPUT_START = date(2017, 7, 1)          # first origin of the pool inputs (Stage D burn-in)
FR_START = date(2017, 8, 1)             # first origin of the first-release tables
RUN_END = date(2025, 9, 1)              # E in run mode
DRY_END = date(2023, 12, 1)             # E in the dry run

# ---- statistics --------------------------------------------------------------------------
K5 = ("series", "target", "origin", "horizon", "period")
BAND = (0.85, 0.95)                     # registered coverage band, inclusive (plan §3)
CELL_BAND = (0.87, 0.93)                # the 0.87-0.93 origin-year x horizon criterion
N_BOOT, SEED, BLOCK = 1000, 0, 3
H1_BAR = -0.15
H3_PROVIDER_TOL = 0.02
H4_TOL = 0.02
H4_ORIGINAL_PP = 5.0
H4B_MIN_COUNT = {19: 10, 21: 11}        # "more than half of the origins"
M2_FAIL_LIMIT = 4                        # failed counted units (of 19) that make H2's M2 clause not evaluable

# ---- models ------------------------------------------------------------------------------
NAMES = {"b0": "b0_seasonal_naive", "b1": "b1_ets", "b2": "b2_stl_arima", "m1": "m1_lightgbm",
         "m1_v3_raw": "m1_lightgbm_v3_raw", "m2": "m2d_corr"}
G1_BASES = ("b1", "b2", "m1_v3_raw")    # G1's scope (amendment "Guard G1 registered")
LEVELS = ("provider", "icb", "region", "england")
PROVIDER_MODELS = ("b0", "b1", "b2", "m1", "m1_v3_raw")
H4_MODELS = ("b0", "b1", "b2", "m1")    # m1_v3_raw alongside

# ---- permitted inputs (P5, design §8) ----------------------------------------------------
# Each input's name under INPUTS and the origin set it must hold. prepare --dev-side writes
# DEV_SIDE_KEYS as dev_side/forecasts/{key}_{level}_{mode}.parquet (generate.forecast_path).
POOL_ORIGINS: tuple[date, ...] = tuple(month_range(INPUT_START, max(DEV)))   # 2017-07 .. 2023-12
DEV_SIDE_ORIGINS: dict[tuple[str, str, str], tuple[date, ...]] = {
    ("b0", "provider", "asof"): DEV, ("m1", "provider", "asof"): DEV,
    **{(k, "provider", "final"): DEV_WINTER_H3 for k in PROVIDER_MODELS},
    ("b1", "provider", "asof"): DEV_WINTER_H3,                              # seeded
}
DEV_SIDE_KEYS: tuple[tuple[str, str, str], ...] = tuple(DEV_SIDE_ORIGINS)
M2_INPUT = "m2/forecasts_m2d_corr.parquet"
M2_DEV_SHA = "58b43b3dcdfab40e18860fa2ffb6898130265c89247e7def0d91071999a35356"  # E-m2-rerun69 README
P5_ORIGINS: dict[str, tuple[date, ...]] = {
    **{f"pool/base_{k}_{lv}.parquet": POOL_ORIGINS for k in G1_BASES for lv in LEVELS},
    M2_INPUT: DEV,
    **{f"dev_side/forecasts/{k}_{lv}_{m}.parquet": o for (k, lv, m), o in DEV_SIDE_ORIGINS.items()},
}
P5_INPUTS: frozenset[str] = frozenset(P5_ORIGINS)                            # 21 names

# ---- paths -------------------------------------------------------------------------------
TAG = "conf-plan-v1"
RUN_ROOT = PROCESSED_DIR / "stage_h"
INPUTS = RUN_ROOT / "inputs"
DRY_ROOT = PROCESSED_DIR / "stage_h_dry"
RESULTS = PROJECT_ROOT / "results" / "H-confirmatory"
DRY_RESULTS = PROJECT_ROOT / "results" / "H-dryrun"
PINS = PROJECT_ROOT / "docs" / "stage_h_pins.json"
QUARANTINE = PROCESSED_DIR / "quarantine" / "pre-seal"
HASH_FILES = ("forecast_hashes.csv", "m2_fits.csv", "timings.csv", "qa_counts.csv")


def ts(d) -> pd.Timestamp:
    return pd.Timestamp(d)


# ---- hashing -----------------------------------------------------------------------------
def file_sha(path: Path | str, chunk: int = 1 << 20) -> str:
    """SHA-256 of a file's bytes."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def row_hash(frame: pd.DataFrame, sort_by: list[str] | None = None) -> str:
    """Canonical row hash (design §3.1): the SHA-256 of ``pd.util.hash_pandas_object`` over
    every column, in sorted column order, after sorting the rows by ``sort_by`` (default: every
    column). Independent of the parquet encoding, so it survives a rewrite of the same rows."""
    cols = sorted(map(str, frame.columns))
    f = frame.rename(columns=str)[cols]
    f = f.sort_values(sort_by or cols, kind="stable").reset_index(drop=True)
    h = pd.util.hash_pandas_object(f, index=False).to_numpy()
    return hashlib.sha256(np.ascontiguousarray(h).tobytes()).hexdigest()


# ---- the run context ---------------------------------------------------------------------
@dataclass(frozen=True)
class Context:
    """What a Stage H command runs on. ``mode`` is "run" (CONF) or "dry" (DEV, no token)."""
    mode: str
    new_origins: tuple[date, ...]        # origins generated in step 3
    counted: tuple[date, ...]            # origins every pooled statistic counts (D7 in run mode)
    fold: dict                           # origin -> origin unit for the 21-origin bootstrap
    end: date                            # E: the last origin any build may reach (design §2.4)
    work: Path                           # data/processed/stage_h/<tag> or stage_h_dry/<head>
    results: Path
    vintages_path: Path
    jobs: int = 8

    @property
    def split(self) -> str:
        """The split the new origins' scores belong to: "conf" in run mode, "dev" in the dry run."""
        return "conf" if self.mode == "run" else "dev"

    @property
    def token_allowed(self) -> bool:
        return self.mode == "run"


def run_context(tag_commit: str, jobs: int = 8) -> Context:
    work = RUN_ROOT / tag_commit
    return Context("run", CONF21, CONF19, dict(D7_FOLD), RUN_END, work, RESULTS,
                   work / "vintages" / "ae_monthly_all_vintages.parquet", jobs)


def dry_context(head: str, jobs: int = 8) -> Context:
    work = DRY_ROOT / head
    return Context("dry", DRY, DRY, {}, DRY_END, work, DRY_RESULTS,
                   work / "vintages" / "ae_monthly_all_vintages.parquet", jobs)
