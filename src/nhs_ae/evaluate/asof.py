"""As-of data loading: what was known at a forecast origin.

Definitions
-----------
* An **origin** is a month ``M``. The forecaster is assumed to run on the second
  Thursday of ``M``, just after NHS England publishes the file for ``M-1``. So the
  training data ends at period ``M-1`` and horizon ``h`` targets period ``M-1+h``:
  an October origin sees September and forecasts December–March at horizons 3–6.
* **as-of mode** uses, for every (period, provider, metric), the value from the most
  recent archived version whose ``available_from`` is on or before the origin's
  as-of date. The ``snapshot`` column of the vintage parquet *is* ``available_from``
  (the ingest and recovery stages set them equal), which is why this module keys on it.
  A version that exists but could not be parsed is simply absent from the parquet, so
  the loader falls back to the previous parseable version of that period.
* If no version of the latest period is available at the origin, that period is treated
  as **not yet published**: the training data end at the last period with a version and
  the horizons shift with them. It is never back-filled from a later revision. Four
  origins are affected (Appendix A, corrected by the pre-registration's §10 row "Appendix
  A corrected (P10)"): 2018-11 and 2021-10 on DEV, one month short; 2025-08 and 2025-09 on
  CONF, one and two months short.
* **final mode** uses the latest archived version of every period published by the
  origin. The difference between the modes is revisions and late submissions, exactly the
  leakage H4 measures, except at those four origins: there the missing month exists in
  final mode (it was published later), so final-mode training ends at *M*−1 and its
  horizons do not shift.
* **Truth** for scoring is always final mode over all periods.

Targets (pre-registration §1) are sums of canonical metrics. Because a non-submitting
provider is an absent row rather than a blank one, a panel is built by reindexing to
the full month range and every gap becomes NaN. No zeros are ever imputed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import pandas as pd

from nhs_ae.config import PROCESSED_DIR
from nhs_ae.features.hierarchy import ENGLAND, UNMAPPED, current_icb_map, current_region_map
from nhs_ae.ingest.recover import second_thursday

log = logging.getLogger(__name__)

TARGETS: dict[str, tuple[str, ...]] = {
    "att_all": ("att_type1", "att_type2", "att_other"),
    "att_type1": ("att_type1",),
    "adm_via_ae": ("adm_via_ae_type1", "adm_via_ae_type2", "adm_via_ae_other"),
}
METRICS_NEEDED = tuple(sorted({m for ms in TARGETS.values() for m in ms}))
LEVELS = ("provider", "region", "england")   # the default backtest levels
OPTIONAL_LEVELS = ("icb",)                   # opt-in: pass e.g. levels=(*LEVELS, "icb")
VINTAGES_PATH = PROCESSED_DIR / "ae_monthly_all_vintages.parquet"


def load_vintages(path=VINTAGES_PATH) -> pd.DataFrame:
    """The all-vintages long table, restricted to target metrics, with normalised keys."""
    v = pd.read_parquet(path, columns=["period", "org_code", "parent_org", "org_name", "metric",
                                       "value", "is_total", "snapshot"])
    v = v[v["metric"].isin(METRICS_NEEDED)].copy()
    v["period"] = pd.to_datetime(v["period"]).dt.to_period("M").dt.to_timestamp()
    v["snapshot"] = pd.to_datetime(v["snapshot"])
    v.loc[v["is_total"], "org_code"] = ENGLAND  # files use '-', 'England', 'ENGLAND', ...
    return v.reset_index(drop=True)


def month_start(d: date) -> pd.Timestamp:
    return pd.Timestamp(d.year, d.month, 1)


def as_of_date(origin: date) -> pd.Timestamp:
    """Publication day of the origin month: the second Thursday."""
    return pd.Timestamp(second_thursday(origin.year, origin.month))


def last_period(origin: date) -> pd.Timestamp:
    return month_start(origin) - pd.DateOffset(months=1)


def slice_vintages(v: pd.DataFrame, as_of: pd.Timestamp | None, upto: pd.Timestamp | None) -> pd.DataFrame:
    """Most recent version of each (period, org, metric) available at ``as_of``, periods ≤ ``upto``."""
    if as_of is not None:
        v = v[v["snapshot"] <= as_of]
    if upto is not None:
        v = v[v["period"] <= upto]
    v = v.sort_values("snapshot", kind="stable")
    return v.drop_duplicates(["period", "org_code", "metric"], keep="last")


def targets_long(sliced: pd.DataFrame) -> pd.DataFrame:
    """period, org_code, parent_org, org_name, is_total, target, value (NaN if any part missing)."""
    wide = sliced.pivot_table(index=["period", "org_code", "is_total"], columns="metric",
                              values="value", aggfunc="first")
    out = {}
    for t, parts in TARGETS.items():
        cols = [c for c in parts if c in wide.columns]
        out[t] = wide[cols].sum(axis=1, min_count=len(parts)) if len(cols) == len(parts) else float("nan")
    long = pd.DataFrame(out).stack(future_stack=True).rename("value").reset_index()
    long = long.rename(columns={"level_3": "target"})
    meta = (sliced.sort_values("snapshot").drop_duplicates(["period", "org_code"], keep="last")
                  [["period", "org_code", "parent_org", "org_name"]])
    return long.merge(meta, on=["period", "org_code"], how="left")


@dataclass
class AsOfData:
    origin: pd.Timestamp        # month start
    as_of: pd.Timestamp         # date the data were fetched "on"
    last_period: pd.Timestamp   # last month in the training data
    mode: str
    targets: pd.DataFrame       # targets_long output
    region_map: pd.Series       # org_code -> region
    # org_code -> ICB code. None means "load data/reference/provider_icb_map.csv (+ backfill)
    # the first time the icb level is asked for", so runs without that level never read it.
    icb_map: pd.Series | None = None

    def panel(self, target: str, level: str) -> pd.DataFrame:
        """Wide monthly panel for one target at one hierarchy level (see models.base)."""
        t = self.targets[self.targets["target"] == target]
        months = pd.date_range(t["period"].min(), self.last_period, freq="MS")
        if level == "england":
            s = t[t["is_total"]].set_index("period")["value"]
            return s.reindex(months).to_frame(ENGLAND)
        prov = t[~t["is_total"]]
        wide = prov.pivot_table(index="period", columns="org_code", values="value", aggfunc="first")
        wide = wide.reindex(months)
        if level == "provider":
            return wide
        if level == "region":
            regions = wide.columns.map(self.region_map.reindex(wide.columns).fillna("LEGACY"))
            return wide.T.groupby(regions).sum(min_count=1).T
        if level == "icb":
            if self.icb_map is None:
                self.icb_map = current_icb_map(self.targets)
            icbs = wide.columns.map(self.icb_map.reindex(wide.columns).fillna(UNMAPPED))
            return wide.T.groupby(icbs).sum(min_count=1).T
        raise ValueError(f"unknown level {level!r}; expected one of {LEVELS + OPTIONAL_LEVELS}")

    def missing_providers(self, target: str) -> pd.Series:
        """Per month, how many providers seen in the last 12 months are absent (informational)."""
        wide = self.panel(target, "provider")
        seen = wide.notna().rolling(12, min_periods=1).max().astype(bool)
        return (seen & wide.isna()).sum(axis=1)


def load_asof(origin: date, mode: str, vintages: pd.DataFrame,
              region_map: pd.Series | None = None,
              icb_map: pd.Series | None = None) -> AsOfData:
    """``icb_map`` (org_code -> ICB, e.g. ``current_icb_map(vintages, mapping)``) defaults
    to the reference table, loaded only if the icb level is requested."""
    if mode not in ("asof", "final"):
        raise ValueError("mode must be 'asof' or 'final'")
    as_of = as_of_date(origin)
    upto = last_period(origin)
    sliced = slice_vintages(vintages, as_of if mode == "asof" else None, upto)
    available = sliced.loc[~sliced["is_total"], "period"].max()
    if pd.notna(available) and available < upto:
        log.warning("origin %s %s: no version of %s available; training ends at %s",
                    origin.strftime("%Y-%m"), mode, upto.strftime("%Y-%m"), available.strftime("%Y-%m"))
        upto = available
    if region_map is None:
        region_map = current_region_map(vintages)
    return AsOfData(origin=month_start(origin), as_of=as_of, last_period=upto, mode=mode,
                    targets=targets_long(sliced), region_map=region_map, icb_map=icb_map)


def load_truth(vintages: pd.DataFrame, region_map: pd.Series | None = None,
               icb_map: pd.Series | None = None) -> AsOfData:
    """Latest revised values for every period: the outturn every forecast is scored against."""
    sliced = slice_vintages(vintages, None, None)
    if region_map is None:
        region_map = current_region_map(vintages)
    last = sliced["period"].max()
    return AsOfData(origin=last, as_of=pd.Timestamp.max, last_period=last, mode="final",
                    targets=targets_long(sliced), region_map=region_map, icb_map=icb_map)
