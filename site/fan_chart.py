"""Draw the live forecast's fan chart, once the live run has written its quantiles.

The published forecast is made on 8 October 2026 and written to
``forecasts/2026-10/ets/quantiles.parquet``. Until that file exists this script exits 1
with a message, and site/figures/live_forecast_fan_placeholder.* stands in its place.

Usage: python site/fan_chart.py [--forecast PATH] [--level england] [--target att_all]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = ROOT / "forecasts" / "2026-10" / "ets" / "quantiles.parquet"
OUT = ROOT / "site" / "figures" / "live_forecast_fan"
HISTORY = ROOT / "data" / "processed" / "ae_monthly_all_vintages.parquet"

INK, GRID, CAL = "#161d22", "#d8dedf", "#1c6b72"
WINTER = ("2026-12", "2027-03")
LABELS = {"att_all": "A&E attendances, all types", "att_type1": "Type 1 A&E attendances",
          "adm_via_ae": "emergency admissions via A&E"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--forecast", type=Path, default=DEFAULT)
    ap.add_argument("--level", default="england")
    ap.add_argument("--target", default="att_all", choices=list(LABELS))
    ap.add_argument("--history-months", type=int, default=24)
    args = ap.parse_args(argv)

    if not args.forecast.exists():
        print(f"{args.forecast} does not exist yet — the live run writes it on 8 October "
              f"2026. Keeping the placeholder.", file=sys.stderr)
        return 1

    fc = pd.read_parquet(args.forecast)
    fc = fc[(fc["level"] == args.level) & (fc["target"] == args.target)]
    if fc.empty:
        print(f"no rows for level={args.level!r} target={args.target!r} in "
              f"{args.forecast}", file=sys.stderr)
        return 1
    wide = fc.pivot_table(index="period", columns="quantile", values="value").sort_index()
    q = {c: wide[c] for c in wide.columns}
    period = pd.to_datetime(wide.index)

    fig, ax = plt.subplots(figsize=(6.6, 3.4))
    bands = [(0.05, 0.95, 0.16), (0.25, 0.75, 0.28)]
    for lo, hi, alpha in bands:
        if lo in q and hi in q:
            ax.fill_between(period, q[lo], q[hi], color=CAL, alpha=alpha, lw=0,
                            label=f"{int((hi - lo) * 100)}% interval")
    if 0.5 in q:
        ax.plot(period, q[0.5], "-o", color=CAL, lw=2, ms=4, label="median forecast")

    if HISTORY.exists():
        hist = pd.read_parquet(HISTORY)
        if {"period", "snapshot"} <= set(hist.columns):
            latest = (hist.sort_values("snapshot").groupby(["period", "org_code"]).tail(1))
            if args.target in latest.columns:
                series = latest.groupby("period")[args.target].sum().sort_index()
                series = series.tail(args.history_months)
                ax.plot(pd.to_datetime(series.index), series.values, color=INK, lw=1.4,
                        label="published outturn")

    winter = pd.to_datetime(list(WINTER))
    ax.axvspan(winter[0], winter[1], color=CAL, alpha=0.05, zorder=0)
    ax.annotate("winter 2026/27", (winter[0], ax.get_ylim()[1]), fontsize=8, color=CAL,
                va="top", ha="left")
    ax.set_ylabel(LABELS[args.target].capitalize())
    ax.set_xlabel("month")
    ax.grid(axis="y", color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    fig.autofmt_xdate(rotation=45)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    for ext in ("svg", "png"):
        fig.savefig(f"{OUT}.{ext}", dpi=200, bbox_inches="tight")
    (OUT.with_suffix(".caption.txt")).write_text(
        f"The published forecast for {LABELS[args.target]} at {args.level} level, made on 8 "
        "October 2026 from data to September 2026. Intervals are the model's own, "
        "uncalibrated: on the sealed window they covered 97-98% where 90% is intended, so "
        "they are wider than nominal. Source: "
        f"{args.forecast.relative_to(ROOT)}.\n")
    print(f"wrote {OUT}.svg / .png / .caption.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
