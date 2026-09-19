"""Build site/figures/: every figure the portfolio site may use, as SVG and PNG.

Figures are drawn from site/site_numbers.json wherever the number is in it, so a figure
and the text beside it cannot disagree. Each figure is written three times: `<name>.svg`,
`<name>.png` and `<name>.caption.txt`, the last holding the one-line caption to print
beneath it.

Usage: python site/build_figures.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FIGS = ROOT / "site" / "figures"
NUMBERS = {e["id"]: e for e in json.loads((ROOT / "site" / "site_numbers.json").read_text())}

INK, GRID, CAL, RAW, WARN = "#161d22", "#d8dedf", "#1c6b72", "#8f2f26", "#8a6d1f"
plt.rcParams.update({"font.size": 9, "figure.dpi": 200, "savefig.bbox": "tight",
                     "axes.edgecolor": INK, "text.color": INK, "axes.labelcolor": INK,
                     "xtick.color": INK, "ytick.color": INK, "svg.fonttype": "none"})


def v(id):
    return NUMBERS[id]["value"]


def save(fig, name, caption):
    FIGS.mkdir(parents=True, exist_ok=True)
    for ext in ("svg", "png"):
        fig.savefig(FIGS / f"{name}.{ext}")
    (FIGS / f"{name}.caption.txt").write_text(caption.strip() + "\n")
    plt.close(fig)
    print(f"  {name}.svg / .png / .caption.txt")


# ------------------------------------------------------------------ (a) coverage
def coverage_by_horizon():
    hs = range(1, 7)
    cal = [v(f"coverage_by_horizon_calibrated_h{h}") * 100 for h in hs]
    raw = [v(f"coverage_by_horizon_uncalibrated_h{h}") * 100 for h in hs]
    lo, hi = [x * 100 for x in v("coverage_tolerance")]

    fig, ax = plt.subplots(figsize=(6.2, 3.4))
    ax.axhspan(lo, hi, color=CAL, alpha=0.08, zorder=0)
    ax.axhline(v("coverage_target") * 100, color=CAL, ls="--", lw=1, zorder=1)
    ax.annotate("target 90%", (0.6, v("coverage_target") * 100 + 0.8), color=CAL, fontsize=8)
    ax.annotate(f"tolerance {lo:.0f}–{hi:.0f}%", (6.35, hi - 1.2), color=CAL, fontsize=8,
                ha="right", alpha=0.75)
    ax.plot(hs, cal, "-o", color=CAL, lw=2, ms=4.5, label="calibrated")
    ax.plot(hs, raw, "-o", color=RAW, lw=2, ms=4.5, label="uncalibrated")
    for x, y in ((1, cal[0]), (6, cal[-1])):
        ax.annotate(f"{y:.1f}", (x, y), textcoords="offset points", xytext=(0, 8),
                    ha="center", color=CAL, fontsize=8)
    for x, y in ((1, raw[0]), (6, raw[-1])):
        ax.annotate(f"{y:.1f}", (x, y), textcoords="offset points", xytext=(0, -14),
                    ha="center", color=RAW, fontsize=8)
    ax.set_xlabel("months ahead")
    ax.set_ylabel("outturns inside the 90% interval (%)")
    ax.set_xlim(0.6, 6.4)
    ax.set_ylim(60, 97)
    ax.grid(axis="y", color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(frameon=False, loc="center right", fontsize=8)
    save(fig, "coverage_by_horizon",
         "Coverage of the 90% interval on the sealed window, provider level, 19 origins: "
         "the calibrated forecast holds the registered 85–95% tolerance at every horizon; "
         "the same forecasts without the calibration layer cover 68–75%. "
         "Source: results/H-confirmatory/tables/primary.table.csv and headline.by_horizon.csv.")


# ------------------------------------------------------------------ (b) winter skill
def winter_skill():
    targets = [("att_all", "All-types\nattendances"), ("att_type1", "Type 1\nattendances"),
               ("adm_via_ae", "Admissions\nvia A&E")]
    fig, ax = plt.subplots(figsize=(6.2, 2.9))
    bar = v("h1_bar") * 100
    ax.axvline(bar, color=WARN, ls="--", lw=1)
    ax.annotate(f"pre-registered bar {bar:.0f}%", (bar + 1, 2.42), color=WARN, fontsize=8)
    ax.axvline(0, color=INK, lw=0.8)
    for i, (key, label) in enumerate(targets):
        point = v(f"h1_rel_{key}") * 100
        lo, hi = v(f"h1_rel_lo_{key}") * 100, v(f"h1_rel_hi_{key}") * 100
        ax.plot([lo, hi], [i, i], color=CAL, lw=2.5, solid_capstyle="round")
        ax.plot([point], [i], "o", color=CAL, ms=7)
        ax.annotate(f"{point:.1f}%", (point, i), textcoords="offset points", xytext=(0, 9),
                    ha="center", fontsize=8, color=CAL)
    ax.set_yticks(range(len(targets)), [t[1] for t in targets])
    ax.set_xlabel("error against the seasonal-naive baseline (%), winter, three months ahead")
    ax.set_xlim(-60, 5)
    ax.set_ylim(-0.6, 2.6)
    ax.grid(axis="x", color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    save(fig, "winter_skill_over_baseline",
         "H1 on the sealed window: MASE against the seasonal-naive baseline at horizon 3 in "
         "winter, with 95% paired-bootstrap intervals over providers. All three targets clear "
         "the pre-registered 15% bar, and do so with any one of the five winter origins left "
         "out. Source: results/H-confirmatory/tables/h1.table.csv.")


# ------------------------------------------------------------------ (c) revision effect
def revision_effect():
    cells = [(k, e) for k, e in NUMBERS.items() if k.startswith("h4_cell_")]
    models = {"b0_seasonal_naive": "Seasonal naive", "b1_ets": "ETS",
              "b2_stl_arima": "STL+ARIMA", "m1_lightgbm": "LightGBM (M1)"}
    targets = {"att_all": "all-types attendances", "att_type1": "Type 1 attendances",
               "adm_via_ae": "admissions via A&E"}
    marks = {"att_all": "o", "att_type1": "s", "adm_via_ae": "^"}

    fig, ax = plt.subplots(figsize=(6.2, 3.0))
    ax.axvspan(-2, 2, color=CAL, alpha=0.07)
    ax.axvline(0, color=INK, lw=0.8)
    for x in (-2, 2):
        ax.axvline(x, color=WARN, ls="--", lw=1)
    ax.annotate("pre-registered bar ±2%", (2 - 0.08, 3.45), color=WARN, fontsize=8, ha="right")
    for key, entry in cells:
        _, _, rest = key.partition("h4_cell_")
        model = next(m for m in models if rest.startswith(m))
        target = rest[len(model) + 1:]
        y = list(models).index(model)
        ax.plot([entry["value"] * 100], [y], marks[target], color=CAL, ms=6,
                markerfacecolor="none", markeredgewidth=1.4)
    ax.set_yticks(range(len(models)), list(models.values()))
    ax.set_xlim(-2.4, 2.4)
    ax.set_ylim(-0.6, 3.7)
    ax.set_xlabel("change in error from training on revised rather than as-published data (%)")
    ax.grid(axis="x", color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.legend(handles=[Line2D([], [], marker=marks[t], color=CAL, ls="", ms=6,
                              markerfacecolor="none", markeredgewidth=1.4, label=name)
                       for t, name in targets.items()],
              frameon=False, fontsize=8, loc="lower left", ncols=3,
              bbox_to_anchor=(0, -0.42))
    save(fig, "revision_effect",
         "H4 on the sealed window: every one of the twelve deciding model × target cells sits "
         "within 0.4% of zero, against a pre-registered bar of ±2%, so training on revised "
         "data rather than the figures published at the time changes winter accuracy "
         "negligibly. Source: results/H-confirmatory/tables/h4.table.csv.")


# ------------------------------------------------------------------ (d) verdict stability
def verdict_stability():
    bases = ["ets", "stl_arima", "m1"]
    names = {"ets": "ETS", "stl_arima": "STL+ARIMA", "m1": "LightGBM (M1) — headline"}
    dropped = sorted({k.split("_drop_")[1] for k in NUMBERS if k.startswith("reconciliation_loo_")})
    full = {b: v(f"reconciliation_verdict_{b}") for b in bases}

    fig, ax = plt.subplots(figsize=(6.2, 2.6))
    for i, b in enumerate(bases):
        for j, d in enumerate(dropped):
            verdict = v(f"reconciliation_loo_{b}_drop_{d}")
            same = verdict == full[b]
            ax.scatter(j, i, s=260, marker="s",
                       color=CAL if verdict == "holds" else RAW,
                       alpha=1.0 if not same else 0.35,
                       edgecolors=INK if not same else "none", linewidths=1.2, zorder=3)
        ax.scatter(-1.2, i, s=260, marker="s", color=CAL if full[b] == "holds" else RAW,
                   alpha=0.35, zorder=3)
    ax.set_yticks(range(len(bases)), [names[b] for b in bases])
    ax.set_xticks([-1.2] + list(range(len(dropped))),
                  ["all five"] + [d for d in dropped], rotation=45, ha="right")
    ax.set_xlabel("origin left out")
    ax.set_xlim(-2, len(dropped) - 0.4)
    ax.set_ylim(-0.7, len(bases) - 0.3)
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(False)
    ax.tick_params(length=0)
    ax.legend(handles=[Line2D([], [], marker="s", ls="", ms=9, color=CAL, alpha=.35,
                              label="reconciliation helps"),
                       Line2D([], [], marker="s", ls="", ms=9, color=RAW, alpha=.35,
                              label="it does not"),
                       Line2D([], [], marker="s", ls="", ms=9, color="none",
                              markeredgecolor=INK, label="verdict flips")],
              frameon=False, fontsize=8, loc="lower left", ncols=3, bbox_to_anchor=(0, -0.62))
    save(fig, "verdict_stability",
         "H3 with one winter origin left out at a time. Two of the three verdicts flip on a "
         "single origin: reconciliation stops helping ETS without October 2024, and stops "
         "hurting the headline model without December 2024. One winter cannot settle it. "
         "Source: results/H-confirmatory/tables/h3.loo.csv and h3.verdicts.csv.")


# ------------------------------------------------------------------ (e) amendment timeline
def amendment_timeline():
    import datetime as dt
    log = (ROOT / "docs" / "amendment_log.md").read_text()
    dates = [dt.date.fromisoformat(d) for d in
             re.findall(r"^### \d+\. \**(\d{4}-\d{2}-\d{2})", log, re.M)]
    freeze = dt.date.fromisoformat(v("freeze_date"))
    unseal = dt.date.fromisoformat(v("confirmatory_unseal_date")[:10])
    counts = {d: dates.count(d) for d in sorted(set(dates))}

    fig, ax = plt.subplots(figsize=(6.2, 2.4))
    ax.bar(list(counts), list(counts.values()), color=CAL, width=0.62)
    for d, n in counts.items():
        ax.annotate(str(n), (d, n), textcoords="offset points", xytext=(0, 3), ha="center",
                    fontsize=7.5, color=INK)
    for day, label, colour in ((freeze, "pre-registration frozen", WARN),
                               (unseal, "sealed window opened", RAW)):
        ax.axvline(day, color=colour, lw=1.2, ls="--")
        ax.annotate(label, (day, max(counts.values()) * 1.02), color=colour, fontsize=8,
                    rotation=90, va="top", ha="right")
    ax.set_ylabel("amendments recorded")
    ax.set_ylim(0, max(counts.values()) * 1.35)
    ax.grid(axis="y", color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.autofmt_xdate(rotation=45)
    save(fig, "amendment_timeline",
         f"All {len(dates)} amendments to the pre-registration, by the day they were recorded, "
         f"with the freeze ({freeze}) and the single opening of the sealed window ({unseal}) "
         "marked. Every change to the plan is dated and reasoned, and all of them precede the "
         "unsealing. Source: docs/amendment_log.md.")


# ------------------------------------------------------------------ (f) fan chart placeholder
def fan_chart_placeholder():
    fig, ax = plt.subplots(figsize=(6.2, 3.0))
    ax.text(0.5, 0.56, "December 2026 – March 2027 forecast", ha="center", va="center",
            fontsize=12, color=INK, transform=ax.transAxes)
    ax.text(0.5, 0.40,
            "Published on 31 October 2026. Run site/fan_chart.py once\n"
            "forecasts/2026-10/ets/quantiles.parquet exists to replace this placeholder.",
            ha="center", va="center", fontsize=8.5, color="#6c7a82", transform=ax.transAxes)
    ax.set_xticks([])
    ax.set_yticks([])
    for side in ("top", "right", "bottom", "left"):
        ax.spines[side].set_color(GRID)
    save(fig, "live_forecast_fan_placeholder",
         "Placeholder. The live forecast for December 2026 to March 2027 is published on 31 "
         "October 2026; site/fan_chart.py draws the real fan chart from "
         "forecasts/2026-10/ets/quantiles.parquet once that file exists.")


if __name__ == "__main__":
    print("building site/figures/")
    coverage_by_horizon()
    winter_skill()
    revision_effect()
    verdict_stability()
    amendment_timeline()
    fan_chart_placeholder()
    print("done")
