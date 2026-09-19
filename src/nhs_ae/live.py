"""Live forecast entry point (WO-B), the 31 October deliverable::

    nhs-ae-forecast live --origin YYYY-MM --snapshot YYYY-MM-DD --model {m2f_r4|ets}

Uncalibrated by design: M2f-r4's posterior intervals or ETS's native intervals, with no
conformal step and no calibration pool, so nothing here reads a sealed score. Both models sit
behind one interface: fit → quantiles → aggregates → ship-blocking checks → write.

* **As-of data.** The origin month M is fetched on its second Thursday and trains to M−1. The
  command aborts unless ``--snapshot`` is the latest vintage available on that day and M−1 is
  present for every target: a missing month would silently move every horizon by one
  (``asof.load_asof`` only warns), putting March 2027 at h = 7 from a 2026-10 origin.
* **Output.** ``forecasts/<origin>/<model>/``: ``quantiles.parquet`` (nine levels, h1–6, three
  targets; ICB, region and England), ``manifest.json``, ``breach_illustrative.csv``, and for
  M2f-r4 the posterior predictive paths and posterior draws (``draws/``). An existing directory
  is never overwritten. A run that fails a check writes to ``<model>__REJECTED/`` with the
  reasons and exits 2.
* **Checks** (each aborts): no all-zero forecast (G1); quantiles present, monotone and ≥ 0;
  mean coherence gap under 1% at region and at England; every level-series-target-horizon
  present with the expected period.
* **Breach table.** Trust-level P(G&A occupancy > 92%), labelled illustrative in every row with
  its failed validation. The live models forecast ICBs, so its admissions input is raw ETS at
  provider level, the Stage G code path unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import subprocess
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from nhs_ae.config import PROCESSED_DIR, PROJECT_ROOT
from nhs_ae.evaluate.asof import TARGETS as _TARGETS
from nhs_ae.evaluate.asof import (
    VINTAGES_PATH,
    as_of_date,
    last_period,
    load_asof,
    load_vintages,
    month_start,
)
from nhs_ae.evaluate.harness import BacktestConfig, forecast_origin
from nhs_ae.evaluate.splits import SEALED_ORIGINS
from nhs_ae.features.hierarchy import icb_region_map
from nhs_ae.models import MODELS, m2
from nhs_ae.models.base import HORIZONS, QUANTILES

log = logging.getLogger(__name__)

OUT = PROJECT_ROOT / "forecasts"
LIVE_MODELS = ("m2f_r4", "ets")
TARGETS = tuple(_TARGETS)
EXCLUDE = ("UNMAPPED", "LEGACY")
GAP_LIMIT = 0.01
BREACH_STATUS = ("ILLUSTRATIVE ONLY, NOT FOR OPERATIONAL USE: the occupancy model failed its registered "
                 "validation (median absolute error 8.7 pp against a 5 pp tolerance; P(breach) Brier "
                 "0.26-0.31 against 0.249 for always forecasting the base rate). Admissions input: raw "
                 "ETS at provider level, not the live ICB model.")


class ShipBlock(RuntimeError):
    """A ship-blocking check failed; the command exits 2."""


def parse_month(s: str) -> date:
    y, m = (int(x) for x in s.split("-"))
    return date(y, m, 1)


def expected_periods(origin: date) -> dict[int, pd.Timestamp]:
    """Horizon h targets M−1+h (prereg §10, origin convention)."""
    return {h: last_period(origin) + pd.DateOffset(months=h) for h in HORIZONS}


def check_horizons(origin: date, periods: dict[int, pd.Timestamp]) -> None:
    want = expected_periods(origin)
    if periods != want:
        raise ShipBlock(f"horizon map {periods} differs from the registered {want}")
    if origin == date(2026, 10, 1):   # the winter the deliverable is for
        winter = [f"{periods[h]:%Y-%m}" for h in (3, 4, 5, 6)]
        if winter != ["2026-12", "2027-01", "2027-02", "2027-03"]:
            raise ShipBlock(f"December 2026 to March 2027 are not at h3-h6 from 2026-10: {winter}")


def load_live(origin: date, snapshot: pd.Timestamp, vintages: pd.DataFrame):
    """As-of data for the origin, refusing any silent truncation or unstated vintage."""
    if pd.Period(origin, "M") in SEALED_ORIGINS:
        raise ShipBlock(f"{origin:%Y-%m} is a sealed CONF origin")
    as_of = as_of_date(origin)
    if snapshot > as_of:
        raise ShipBlock(f"snapshot {snapshot:%Y-%m-%d} is after the as-of date {as_of:%Y-%m-%d}")
    usable = vintages.loc[vintages["snapshot"] <= as_of, "snapshot"]
    if usable.empty or usable.max() != snapshot:
        latest = "none" if usable.empty else f"{usable.max():%Y-%m-%d}"
        raise ShipBlock(f"snapshot {snapshot:%Y-%m-%d} is not the latest vintage available on {as_of:%Y-%m-%d} "
                        f"(latest: {latest}); ingest it with --snapshot, or state the right date")
    data = load_asof(origin, "asof", vintages)
    upto = last_period(origin)
    for t in TARGETS:
        p = data.panel(t, "icb")
        p = p[[c for c in p.columns if c not in EXCLUDE]]
        last = p.dropna(how="all").index.max()
        if data.last_period != upto or last != upto:
            raise ShipBlock(f"latest expected month {upto:%Y-%m} absent for {t} (training would end at "
                            f"{min(data.last_period, last):%Y-%m} and every horizon would shift by one)")
    return data, as_of


def fit_m2f(origin: date, data, regions: pd.Series, cores: int = 4) -> dict:
    from nhs_ae.evaluate.seed_stability import family_diagnostics
    from nhs_ae.models.m2_draws import fit_with_draws
    panels = {t: data.panel(t, "icb") for t in TARGETS}
    fc, diag, trace, paths, post, meta = fit_with_draws(origin, m2.M2F_R4, panels, regions, cores=cores)
    fam = family_diagnostics(trace)
    return {"fc": fc, "diagnostics": [{k: (str(v) if isinstance(v, pd.Timestamp) else v) for k, v in diag.items()}],
            "families": fam, "draws": {"predictive": {**paths, **meta}, "posterior": {**post, "months": meta["months"]}}}


def fit_ets(origin: date, data, regions: pd.Series) -> dict:
    from nhs_ae.evaluate.stage_f import SummedView
    model = MODELS["b1"]()
    icb = forecast_origin(data, [model], BacktestConfig(origins=[], modes=("asof",), levels=("icb",)))
    agg = forecast_origin(SummedView(data, regions), [model],
                          BacktestConfig(origins=[], modes=("asof",), levels=("region", "england")))
    fc = pd.concat([icb[~icb["series"].isin(EXCLUDE)], agg], ignore_index=True)
    return {"fc": fc[["level", "target", "series", "horizon", "period", "quantile", "value"]].assign(
        origin=month_start(origin)), "diagnostics": [], "families": None, "draws": None}


def ship_checks(fc: pd.DataFrame, origin: date, regions: pd.Series) -> list[str]:
    fails = []
    want = {"icb": sorted(regions.index), "region": sorted(regions.unique()), "england": ["ENGLAND"]}
    w = fc.pivot_table(index=["level", "target", "series", "horizon", "period"], columns="quantile",
                       values="value", aggfunc="first")
    missing_q = [q for q in QUANTILES if q not in w.columns]
    if missing_q:
        return [f"quantile levels missing: {missing_q}"]
    w = w[list(QUANTILES)]
    expected = pd.MultiIndex.from_tuples(
        [(lv, t, s, h, per) for lv, ss in want.items() for t in TARGETS for s in ss
         for h, per in expected_periods(origin).items()], names=w.index.names)
    absent, extra = expected.difference(w.index), w.index.difference(expected)
    if len(absent):
        fails.append(f"{len(absent)} expected forecasts absent, e.g. {list(absent[:3])}")
    if len(extra):
        fails.append(f"{len(extra)} unexpected forecasts, e.g. {list(extra[:3])}")
    v = w.to_numpy(float)
    if np.isnan(v).any():
        fails.append(f"{int(np.isnan(v).any(axis=1).sum())} forecasts have a missing quantile")
    if (v < 0).any():
        fails.append(f"{int((v < 0).any(axis=1).sum())} forecasts have a negative quantile")
    if (np.diff(v, axis=1) < 0).any():
        fails.append(f"{int((np.diff(v, axis=1) < 0).any(axis=1).sum())} forecasts have crossed quantiles")
    zero = (v == 0).all(axis=1)
    if zero.any():
        fails.append(f"G1: {int(zero.sum())} all-zero forecasts, e.g. {list(w.index[zero][:3])}")
    for level, gap in coherence(fc, regions).items():
        if not gap < GAP_LIMIT:
            fails.append(f"coherence gap at {level} is {gap:.4%} (limit {GAP_LIMIT:.0%})")
    return fails


def coherence(fc: pd.DataFrame, regions: pd.Series) -> dict[str, float]:
    """Mean |aggregate median − Σ children's medians| / aggregate median (the Stage F definition)."""
    med = fc[np.isclose(fc["quantile"].astype(float), 0.5)]
    out = {}
    for level, child, parent in (("region", "icb", regions), ("england", "region", None)):
        ch = med[med["level"] == child]
        ch = ch.assign(parent=ch["series"].map(parent) if parent is not None else "ENGLAND")
        sums = ch.groupby(["target", "horizon", "parent"])["value"].sum()
        agg = med[med["level"] == level].set_index(["target", "horizon", "series"])["value"]
        agg.index = agg.index.set_names("parent", level="series")
        j = pd.concat([agg.rename("agg"), sums.rename("children")], axis=1, join="inner")
        out[level] = float(((j["agg"] - j["children"]).abs() / j["agg"]).mean()) if len(j) else float("nan")
    return out


def breach_live(origin: date, as_of: pd.Timestamp, data, vintages: pd.DataFrame, seed: int = 0) -> pd.DataFrame:
    from nhs_ae.decide.occupancy import (
        breach_table,
        fit_coefficients,
        occupancy_draws,
        quarterly_admissions,
        sample_quantiles,
    )
    from nhs_ae.evaluate.stage_g import N_DRAWS, load_kh03, monthly_admissions
    adm = forecast_origin(data, [MODELS["b1"]()], BacktestConfig(origins=[], modes=("asof",), levels=("provider",),
                                                                  targets=("adm_via_ae",)))
    kh03 = load_kh03()
    adm_q = quarterly_admissions(monthly_admissions(vintages[vintages["snapshot"] <= as_of]))
    coefs = fit_coefficients(kh03, adm_q, as_of)
    s = adm.pivot_table(index=["series", "horizon", "period"], columns="quantile", values="value").reset_index()
    s = s[s["series"].isin(set(coefs.dropna(subset=["beds"])["org_code"]))].reset_index(drop=True)
    rng = np.random.default_rng(seed)
    draws = sample_quantiles(s[list(QUANTILES)].to_numpy(float), QUANTILES, N_DRAWS, rng)
    c = coefs.set_index("org_code").loc[s["series"]].reset_index()
    occ = occupancy_draws(draws, s["period"].dt.days_in_month.to_numpy(float), c, rng)
    out = pd.concat([s[["series", "horizon", "period", 0.5]].rename(columns={0.5: "adm_median_ets"}),
                     breach_table(occ, c["beds"].to_numpy())], axis=1)
    out.insert(0, "status", BREACH_STATUS)
    out["origin"], out["beds"] = month_start(origin), c["beds"].to_numpy()
    return out


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False, cwd=PROJECT_ROOT).stdout.strip()


def environment() -> dict:
    """Output is bit-identical only within one environment: the same seed gave ETS quantiles up to
    3.9% apart, and a different M2f-r4 chain, on a Linux CI runner against macOS (2026-09-12)."""
    import importlib.metadata as md
    import platform
    out = {"python": platform.python_version(), "platform": platform.platform(), "machine": platform.machine()}
    for pkg in ("numpy", "pandas", "scipy", "statsmodels", "pymc", "pytensor", "nutpie", "arviz"):
        try:
            out[pkg] = md.version(pkg)
        except md.PackageNotFoundError:
            out[pkg] = None
    return out


def manifest(origin: date, snapshot: pd.Timestamp, as_of: pd.Timestamp, model: str, res: dict, fc: pd.DataFrame,
             data, gaps: dict, fails: list[str]) -> dict:
    tag = "m2f-r4-frozen" if model == "m2f_r4" else "prereg-v1 (B1 ETS)"
    tag_ok = subprocess.run(["git", "merge-base", "--is-ancestor", tag.split()[0], "HEAD"], cwd=PROJECT_ROOT,
                            capture_output=True, check=False).returncode == 0
    dirty = [ln for ln in _git("status", "--porcelain").splitlines() if not ln[3:].startswith("forecasts/")]
    return {"origin": f"{origin:%Y-%m}", "model": model, "model_tag": tag, "tag_is_ancestor_of_head": tag_ok,
            "code_commit": _git("rev-parse", "HEAD"), "tree_dirty_outside_forecasts": bool(dirty),
            "as_of": f"{as_of:%Y-%m-%d}", "snapshot": f"{snapshot:%Y-%m-%d}",
            "training_ends": f"{data.last_period:%Y-%m}",
            "periods": {f"h{h}": f"{p:%Y-%m}" for h, p in expected_periods(origin).items()},
            "inputs": {"vintages": {"path": str(VINTAGES_PATH.relative_to(PROJECT_ROOT)), "sha256": _sha(VINTAGES_PATH)},
                       "manifest": {"path": "data/raw/manifest.jsonl",
                                    "sha256": _sha(PROJECT_ROOT / "data" / "raw" / "manifest.jsonl")},
                       "provider_icb_map": {"path": "data/reference/provider_icb_map.csv",
                                            "sha256": _sha(PROJECT_ROOT / "data" / "reference" / "provider_icb_map.csv")},
                       "kh03": {"path": "data/processed/kh03.parquet", "sha256": _sha(PROCESSED_DIR / "kh03.parquet")}},
            "sampling": res["diagnostics"], "rows": {lv: int((fc["level"] == lv).sum()) for lv in ("icb", "region", "england")},
            "coherence_gap": gaps, "checks_failed": fails, "environment": environment(),
            "calibration": "none: posterior (M2f-r4) or native (ETS) intervals; no conformal step, no calibration pool"}


def run(origin: date, snapshot: pd.Timestamp, model: str, out: Path = OUT, cores: int = 4, force: bool = False) -> Path:
    if model not in LIVE_MODELS:
        raise ValueError(f"model must be one of {LIVE_MODELS}")
    target = out / f"{origin:%Y-%m}" / model
    if target.exists() and not force:
        raise FileExistsError(f"{target} exists; a forecast is never overwritten (pass --force for a dry run)")
    vintages = load_vintages(VINTAGES_PATH)
    data, as_of = load_live(origin, snapshot, vintages)
    regions = icb_region_map()
    res = fit_m2f(origin, data, regions, cores) if model == "m2f_r4" else fit_ets(origin, data, regions)
    fc = res["fc"]
    check_horizons(origin, {int(h): pd.Timestamp(p) for h, p in fc[["horizon", "period"]].drop_duplicates().to_numpy()})
    fails = ship_checks(fc, origin, regions)
    gaps = coherence(fc, regions)
    dest = target if not fails else target.with_name(f"{model}__REJECTED")
    dest.mkdir(parents=True, exist_ok=True)
    fc.to_parquet(dest / "quantiles.parquet", index=False)
    if res["draws"]:
        from nhs_ae.models.m2_draws import save_npz
        for k, arrays in res["draws"].items():
            save_npz(dest / "draws" / f"{k}.npz", arrays)
        res["families"].to_csv(dest / "diagnostics_by_family.csv", index=False)
    breach_live(origin, as_of, data, vintages).to_csv(dest / "breach_illustrative.csv", index=False)
    (dest / "manifest.json").write_text(json.dumps(manifest(origin, snapshot, as_of, model, res, fc, data, gaps, fails),
                                                   indent=1, default=str))
    if fails:
        raise ShipBlock("; ".join(fails))
    return dest


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="nhs-ae-forecast")
    sub = p.add_subparsers(dest="cmd", required=True)
    lv = sub.add_parser("live", help="forecast from one origin")
    lv.add_argument("--origin", required=True, help="YYYY-MM")
    lv.add_argument("--snapshot", required=True, help="YYYY-MM-DD: the vintage the forecast is made from")
    lv.add_argument("--model", required=True, choices=LIVE_MODELS)
    lv.add_argument("--out", type=Path, default=OUT)
    lv.add_argument("--cores", type=int, default=4)
    lv.add_argument("--force", action="store_true", help="overwrite an existing directory (dry runs only)")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        dest = run(parse_month(args.origin), pd.Timestamp(args.snapshot), args.model, args.out, args.cores, args.force)
    except ShipBlock as e:
        print(f"SHIP-BLOCKED: {e}", file=sys.stderr)
        return 2
    except FileExistsError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 3
    print(f"FORECAST WRITTEN: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
