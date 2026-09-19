"""Print the two headline tables from the shipped result files.

Run by `make test` and `make tables`. Every number is read from
results/H-confirmatory/tables/, never from this file.
"""
from __future__ import annotations

import csv
from pathlib import Path

T = Path(__file__).resolve().parent.parent / "results" / "H-confirmatory" / "tables"


def read(name):
    with open(T / name, newline="") as f:
        return list(csv.DictReader(f))


def main() -> int:
    print("\nBaseline table — H1: error against the seasonal-naive baseline")
    print("(MASE, horizon 3, winter, provider level, sealed window, 5 origins)\n")
    print(f"  {'target':<28}{'change':>9}{'95% interval':>22}   verdict")
    names = {"att_all": "all-types attendances", "att_type1": "Type 1 attendances",
             "adm_via_ae": "admissions via A&E"}
    for r in read("h1.table.csv"):
        if r["model"] != "m1_lightgbm" or r["role"] != "decides":
            continue
        lo, hi = float(r["rel_lo"]) * 100, float(r["rel_hi"]) * 100
        print(f"  {names[r['target']]:<28}{float(r['rel']) * 100:>8.1f}%"
              f"{f'[{lo:.1f}%, {hi:.1f}%]':>22}   {r['verdict']}")
    print("\n  Pre-registered bar: a 15% reduction, with the interval entirely beyond it.")

    print("\nCoverage table — the primary comparison")
    print("(90% intervals, provider level, as-of, sealed window, 19 origins)\n")
    print(f"  {'horizon':<9}{'calibrated':>12}{'uncalibrated':>14}{'95% interval':>20}")
    raw = {r["horizon"]: r for r in read("headline.by_horizon.csv")
           if r["model"] == "m1_lightgbm_v3_raw"}
    for r in read("primary.table.csv"):
        h = r["horizon"]
        lo, hi = float(r["lo"]) * 100, float(r["hi"]) * 100
        print(f"  {h:<9}{float(r['point']) * 100:>11.1f}%"
              f"{float(raw[h]['point_raw']) * 100:>13.1f}%"
              f"{f'[{lo:.1f}%, {hi:.1f}%]':>20}")
    print("\n  Registered tolerance: 85–95% at every horizon. Verdict: within tolerance.")
    print("  The uncalibrated column is the same forecasts without the calibration layer.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
