"""Build site/site_numbers.json: every number the portfolio site may show, with its source.

Rules this script exists to enforce:

* no number is typed into the site by hand. Each value is read from a tracked file, and
  that file's path (with a line number, where the value comes from prose) is recorded
  beside it;
* a value that cannot be found is written as "NOT FOUND", with the paths searched;
* every entry carries a label saying how much weight it can take:
  ``confirmatory`` (fixed before the sealed window was opened and scored once),
  ``development`` (measured on the development window), ``exploratory`` (registered but
  not confirmatory, or reported alongside), ``post_hoc`` (measured after the fact).

Usage: python site/build_numbers.py
"""
from __future__ import annotations

import csv
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "site_numbers.json"
H = ROOT / "results" / "H-confirmatory"
T = H / "tables"

ENTRIES: list[dict] = []


# ---------------------------------------------------------------- helpers

def rel(path: Path) -> str:
    """Repository-relative path. data/processed is a symlink out of the worktree, so fall
    back to the unresolved path rather than following it out of the tree."""
    p = Path(path)
    try:
        return str(p.resolve().relative_to(ROOT))
    except ValueError:
        return str(p).replace(str(ROOT) + "/", "")


def add(id, value, unit, description, source_path, label, caveat=""):
    ENTRIES.append({"id": id, "value": value, "unit": unit, "description": description,
                    "source_path": source_path, "label": label, "caveat": caveat})


def not_found(id, description, searched, caveat=""):
    ENTRIES.append({"id": id, "value": "NOT FOUND", "unit": "", "description": description,
                    "source_path": "", "label": "", "caveat": caveat,
                    "searched_paths": [str(s) for s in searched]})


def rows(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def one(path: Path, **where) -> dict:
    got = [r for r in rows(path) if all(r[k] == v for k, v in where.items())]
    if len(got) != 1:
        raise SystemExit(f"{rel(path)}: {len(got)} rows match {where}, expected 1")
    return got[0]


def num(x: str) -> float:
    return round(float(x), 6)


def grep(path: Path, pattern: str, group: int = 1) -> tuple[str, str]:
    """The first capture of ``pattern`` in ``path``, with 'path:line' beside it.

    Raises if the pattern matches no line or more than one, so a silent mis-read
    cannot reach the site.
    """
    text = path.read_text()
    hits = list(re.finditer(pattern, text, re.S))
    if len(hits) != 1:
        raise SystemExit(f"{rel(path)}: {len(hits)} matches for {pattern!r}, expected 1")
    m = hits[0]
    line = text.count("\n", 0, m.start()) + 1
    return re.sub(r"\s+", " ", m.group(group)).strip(), f"{rel(path)}:{line}"


def grep_agreed(path: Path, pattern: str, group: int = 1) -> tuple[str, str]:
    """Like ``grep``, but allows several matches provided every capture agrees."""
    text = path.read_text()
    hits = list(re.finditer(pattern, text, re.S))
    caps = {re.sub(r"\s+", " ", m.group(group)).strip() for m in hits}
    if len(caps) != 1:
        raise SystemExit(f"{rel(path)}: captures {caps} for {pattern!r}, expected one value")
    line = text.count("\n", 0, hits[0].start()) + 1
    return caps.pop(), f"{rel(path)}:{line}"


VERDICTS = json.loads((H / "verdicts.json").read_text())
PREREG = ROOT / "docs" / "preregistration.md"
DESIGN = ROOT / "docs" / "stage_h_design.md"
PLAN = ROOT / "docs" / "confirmatory_plan.md"
LOG = ROOT / "docs" / "amendment_log.md"

TARGETS = {"att_all": "all-types attendances", "att_type1": "Type 1 attendances",
           "adm_via_ae": "emergency admissions via A&E"}


# ---------------------------------------------------------------- 1. coverage

value, src = grep(PREREG, r"empirical coverage within\s+\*\*±5 percentage points\*\* of (90)%")
add("coverage_target", 0.90, "proportion",
    "Nominal coverage of the 90% central prediction interval: the share of outturns that "
    "should fall inside it.", src, "confirmatory")

lo, src_tol = grep(DESIGN, r"\*within tolerance\* if (0\.85) ≤ lo_h and hi_h ≤ 0\.95")
add("coverage_tolerance", [0.85, 0.95], "proportion",
    "Registered tolerance band for 90% coverage. A clause is confirmed if coverage is "
    "inside this band at every horizon and refuted if it is outside at any.",
    src_tol, "confirmatory")

CAL_MODEL = one(T / "primary.table.csv", horizon="1")["model"]
cal_def, cal_src = grep(PREREG, r"direct multi-horizon; (conformalised on a [^|]+?) \|")
per_h, per_h_src = grep(PREREG, r"registered as `m1_v3`: (per-horizon models[^.]+\.)")
add("calibrated_model", CAL_MODEL, "model key",
    "The model behind every 'calibrated' coverage figure: LightGBM trained per horizon "
    "(M1 v3 raw), with pooled conformal calibration and the G1 all-zero-forecast marking, "
    "scored at provider level in as-of mode.",
    rel(T / "primary.table.csv"), "confirmatory")
add("calibration_layer", cal_def, "definition",
    "The calibration layer, quoted from the pre-registration's model table: split conformal "
    "on a rolling window of recent errors.", cal_src, "confirmatory",
    "'Pooled' means the conformal scores are pooled across providers rather than taken "
    "per series (docs/results.md, Stage D: 'per-series rather than pooled conformal "
    "scores'). The layer is applied to the quantile forecasts, not refitted per horizon.")
add("calibrated_model_structure", per_h, "definition",
    "The learner under the calibration layer, quoted from its registration.",
    per_h_src, "confirmatory",
    "M1 v3: one LightGBM per horizon, with the original 12-month level feature.")

for r in rows(T / "primary.table.csv"):
    h = r["horizon"]
    add(f"coverage_by_horizon_calibrated_h{h}", num(r["point"]), "proportion",
        f"Sealed-window 90% interval coverage of the calibrated forecast at horizon {h}, "
        f"provider level, {r['n_origins']} origins.",
        rel(T / "primary.table.csv"), "confirmatory",
        f"95% interval {num(r['lo'])}–{num(r['hi'])}.")

for r in rows(T / "headline.by_horizon.csv"):
    if r["model"] != "m1_lightgbm_v3_raw":
        continue
    h = r["horizon"]
    add(f"coverage_by_horizon_uncalibrated_h{h}", num(r["point_raw"]), "proportion",
        f"The same forecasts without the calibration layer, at horizon {h}.",
        rel(T / "headline.by_horizon.csv"), "confirmatory",
        f"95% interval {num(r['lo_raw'])}–{num(r['hi_raw'])}. Column point_raw.")

dev_cov = [r for r in rows(T / "dev.coverage.primary.csv") if r["region"] == "assessable"]
for r in dev_cov:
    add(f"coverage_by_year_dev_{r['oyear']}_h{r['horizon']}", num(r["value"]), "proportion",
        f"Development-window coverage of the calibrated model, origin year {r['oyear']}, "
        f"horizon {r['horizon']} ({r['origins']} origins, {r['n']} scored rows).",
        rel(T / "dev.coverage.primary.csv"), "development",
        "Development window, 69 origins from 2018-04 to 2023-12. 2020 and 2021 cover the "
        "COVID collapse and are the widest cells.")


# 2020 is absent from the confirmatory run's DEV coverage table by design: the registered
# assessable origin-years are 2018, 2019, 2021, 2022 and 2023, each needing at least six
# origins. It is supplied here from Stage D's table, which keeps the COVID cells, because
# the site was asked for every year including 2020.
assessable, assessable_src = grep(
    DESIGN, r"one value per assessable DEV origin-year \(([^)]+)\)")
add("coverage_by_year_dev_2020_omitted_from_confirmatory", assessable, "registered years",
    "Why no 2020 cell appears in the confirmatory run's development coverage table: these "
    "are the origin-years the design registered as assessable.", assessable_src,
    "confirmatory",
    "2020 is not among them. The 2020 figures below come from the Stage D calibration "
    "table, which keeps the COVID cells and marks them unassessed.")

stage_d = ROOT / "results" / "D-calibration" / "coverage_by_horizon_year.csv"
for r in rows(stage_d):
    if (r["model"], r["oyear"], r["target"], r["region"]) != (
            "m1_lightgbm_v3_raw+pooled", "2020", "all", "covid_window"):
        continue
    add(f"coverage_by_year_dev_2020_h{r['horizon']}", num(r["cov90"]), "proportion",
        f"Development-window coverage of the calibrated model in 2020, horizon "
        f"{r['horizon']} ({r['origins']} origins, {r['n']} scored rows), COVID window.",
        rel(stage_d), "development",
        "Marked assessed=False: 2020 is not a registered assessable origin-year, and these "
        "cells span the COVID collapse. Shown because the year was asked for; it decides "
        "nothing, and the site should not quote it beside the confirmatory cells without "
        "saying which window it belongs to.")


# ---------------------------------------------------------------- 2. H1, skill over baseline

bar, bar_src = grep(PREREG, r"is at least \*\*(\d+)% lower\*\*")
add("h1_bar", -round(int(bar) / 100, 2), "relative change",
    "Pre-registered bar for H1: the error reduction the model must beat, with the 95% "
    "interval entirely beyond it.", bar_src, "confirmatory")

w5, w5_src = grep(DESIGN, r"\*\*W5\*\*, the winter-h3 origins, are ([^.]+)\.")
add("h1_winter_origins", len(re.findall(r"\d{4}-\d{2}", w5)), "count",
    f"Number of winter forecast origins behind every winter statistic: {w5}. At horizon 3 "
    "their targets are March 2024 and December 2024 to March 2025.",
    w5_src, "confirmatory",
    "One complete winter plus one March. Bootstraps resample providers within that winter, "
    "so they do not capture between-winter variation.")

for target, name in TARGETS.items():
    r = one(T / "h1.table.csv", model="m1_lightgbm", target=target, role="decides")
    for field, key in (("rel", "h1_rel"), ("rel_lo", "h1_rel_lo"), ("rel_hi", "h1_rel_hi")):
        add(f"{key}_{target}", num(r[field]), "relative change",
            f"H1, {name}: {'point estimate' if field == 'rel' else field} of the relative "
            "change in MASE against the seasonal-naive baseline, horizon 3, winter, "
            "provider level.", rel(T / "h1.table.csv"), "confirmatory",
            f"Verdict {r['verdict']}; fragile={r['fragile']}.")

add("h1_verdict", VERDICTS["h1.overall.verdict"], "verdict",
    "H1 overall verdict: confirmed only if all three targets clear the bar.",
    rel(H / "verdicts.json"), "confirmatory",
    f"fragile={VERDICTS['h1.overall.fragile']}; flips={VERDICTS['h1.overall.flips']}.")

for r in rows(T / "h1.loo.csv"):
    if r["model"] != "m1_lightgbm" or r["role"] != "decides":
        continue
    add(f"h1_loo_{r['target']}_drop_{r['dropped'][:7]}", r["verdict"], "verdict",
        f"H1 for {TARGETS[r['target']]} with origin {r['dropped'][:7]} left out "
        f"(rel {num(r['rel'])}, upper end {num(r['rel_hi'])}).",
        rel(T / "h1.loo.csv"), "confirmatory",
        "Leave-one-origin-out over the five winter origins; the verdict holds in all five.")


# ---------------------------------------------------------------- 3. the published model

not_found(
    "sealed_wis_by_model_by_target",
    "A sealed-window WIS table by model and target, as the criterion that selected the "
    "published model.",
    [rel(T), rel(H / "verdicts.json"), rel(ROOT / "docs" / "confirmatory_plan.md"),
     rel(ROOT / "docs" / "stage_h_design.md")],
    "No such table exists, and no sealed-window statistic selected the published model. "
    "The sealed run reports WIS only as ratios against M1 + pooled at aggregate levels "
    "(results/H-confirmatory/tables/f2.wis__level=*.csv) and as the H3 reconciliation "
    "comparison; the choice of published model was made on the development window before "
    "the seal was opened, by the rule quoted in live_model_selection_rule.")

rule, rule_src = grep(PREREG, r"(\*\*D5 = \(b\): the live forecast is uncalibrated raw ETS[^|]*?)(?:\|)")
add("live_model_selection_rule", rule, "rule text",
    "The registered rule that made raw ETS the published model, quoted verbatim. It was "
    "applied to a development-window re-run (D1), and no sealed row informed it.",
    rule_src, "confirmatory",
    "The pre-commitment it applies is docs/d1_precommitments.md, committed before the "
    "re-run it decides.")

for r in rows(T / "headline.icb_raw_ets.as_issued.by_horizon.csv"):
    add(f"ets_sealed_coverage_icb_h{r['horizon']}", num(r["point"]), "proportion",
        f"Sealed-window 90% interval coverage of the published model (raw ETS) at ICB "
        f"level, horizon {r['horizon']} — the level the live forecast issues.",
        rel(T / "headline.icb_raw_ets.as_issued.by_horizon.csv"), "confirmatory",
        f"95% interval {num(r['lo'])}–{num(r['hi'])}. Over-covers: the intervals are wider "
        "than nominal. Under P12 any change to the live model made because of this is "
        "recorded as CONF-informed.")

for r in rows(T / "headline.by_horizon.csv"):
    if r["model"] != "b1_ets":
        continue
    add(f"ets_sealed_coverage_provider_h{r['horizon']}", num(r["point_raw"]), "proportion",
        f"The same model at provider level, horizon {r['horizon']}.",
        rel(T / "headline.by_horizon.csv"), "confirmatory", "Column point_raw.")

for r in rows(T / "h2_m2.table.csv"):
    add(f"hierarchical_bayes_sealed_coverage_h{r['horizon']}", num(r["point"]), "proportion",
        f"Sealed-window 90% interval coverage of the frozen hierarchical Bayesian model "
        f"(m2d_corr), its own posterior intervals, ICB level, horizon {r['horizon']}.",
        rel(T / "h2_m2.table.csv"), "confirmatory",
        f"95% interval {num(r['lo'])}–{num(r['hi'])}.")

add("hierarchical_bayes_verdict", VERDICTS["h2_m2.verdict.verdict"], "verdict",
    "H2's M2 clause: refuted. The registered prediction was that these intervals would "
    "hold the tolerance band; they miss it at every horizon by being too wide.",
    rel(H / "verdicts.json"), "confirmatory",
    f"All {VERDICTS['h2_m2.n_full']} fits completed and {VERDICTS['h2_m2.n_failed_full']} "
    "failed, so the clause was evaluable.")

add("conformal_m1_verdict", VERDICTS["h2_m1.verdict.verdict"], "verdict",
    "H2's M1 clause: confirmed. Default M1's own conformal intervals under-cover.",
    rel(H / "verdicts.json"), "confirmatory",
    "Direction is named, not decisive; the clause turns on being outside the band at some "
    "horizon in 4-6.")


# ---------------------------------------------------------------- 4. revisions (H4, H4b)

mode_def, mode_src = grep(ROOT / "src" / "nhs_ae" / "evaluate" / "asof.py",
                          r"(\*\*Truth\*\* for scoring is always final mode over all periods\.)")
add("h4_what_was_varied",
    "training data vintage only; the outturn scored against is the same in both modes",
    "definition",
    "What the as-of/final comparison varies. As-of mode trains on the figures published at "
    "the origin; final mode trains on today's revised figures. Both are scored against the "
    "same outturn, so the comparison isolates the training vintage.",
    rel(ROOT / "src" / "nhs_ae" / "evaluate" / "asof.py"), "confirmatory",
    f"Loader docstring: {mode_def.strip()!r}. Check this against docs/preregistration.md §4 "
    "before the site states it in other words.")

h4_bar, h4_bar_src = grep(PREREG, r"in \*\*final\*\* mode is within \*\*(\d+)%\*\* of\s+its \*\*as-of\*\* value")
add("h4_bar", round(int(h4_bar) / 100, 2), "relative change",
    "Pre-registered bar for H4: the largest difference between final-mode and as-of-mode "
    "error that still counts as 'revisions do not matter'.", h4_bar_src, "confirmatory")

h4_cells = [r for r in rows(T / "h4.table.csv") if r["role"] == "decides"]
for r in h4_cells:
    add(f"h4_cell_{r['model']}_{r['target']}", num(r["rel"]), "relative change",
        f"H4: relative change in winter horizon-3 WIS from training on revised data rather "
        f"than as-published data, {r['model']} on {TARGETS[r['target']]}.",
        rel(T / "h4.table.csv"), "confirmatory",
        f"95% interval {num(r['rel_lo'])}–{num(r['rel_hi'])}; differs={r['differs']}.")

worst = max(h4_cells, key=lambda r: abs(float(r["rel"])))
add("h4_max_revision_effect", num(worst["rel"]), "relative change",
    f"The largest revision effect over the twelve deciding cells: {worst['model']} on "
    f"{TARGETS[worst['target']]}.", rel(T / "h4.table.csv"), "confirmatory",
    "Twelve cells = four deciding models (B0, B1 ETS, B2 STL+ARIMA, default M1) × three "
    "targets. M1 v3 raw is reported alongside, not among the twelve, and moves further: "
    "see h4_alongside_*.")

for r in rows(T / "h4.table.csv"):
    if r["role"] == "decides":
        continue
    add(f"h4_alongside_{r['model']}_{r['target']}", num(r["rel"]), "relative change",
        f"H4 for the model reported alongside ({r['model']}) on {TARGETS[r['target']]}: the "
        "base learner of the calibrated primary.", rel(T / "h4.table.csv"), "exploratory",
        f"95% interval {num(r['rel_lo'])}–{num(r['rel_hi'])}. Outside the twelve deciding "
        "cells; the widest single cell in the table.")

add("h4_verdict", VERDICTS["h4.verdict.verdict"], "verdict",
    "H4 verdict on the sealed window.", rel(H / "verdicts.json"), "exploratory",
    "Labelled exploratory on the sealed window by the amendment '§9 applied to CONF', "
    "because the winter slice holds one winter rather than the four §9 requires. H4's "
    "confirmatory statement was made earlier, at tag backtest-v1, on the pre-split window.")

add("h4_original_verdict", VERDICTS["h4_original.verdict.verdict"], "verdict",
    "H4-original (a ranking change, or a gain over the baseline differing between modes by "
    "more than 5 percentage points), which the pre-registration predicted would be refuted.",
    rel(H / "verdicts.json"), "exploratory")

for r in rows(T / "h4b.table.csv"):
    add(f"h4b_late_submissions_{r['target']}", r["verdict"], "verdict",
        f"H4b for {TARGETS[r['target']]}: the late-submission component is the larger one "
        f"at {r['late_larger']} of 19 origins (needed: more than half, {r['need']}).",
        rel(T / "h4b.table.csv"), "exploratory",
        "Labelled *seen*: the decomposition was computed and read before the freeze.")

add("h4b_verdict", VERDICTS["h4b.overall.verdict"], "verdict",
    "H4b overall: not confirmed. It holds for all-types attendances only.",
    rel(H / "verdicts.json"), "exploratory")


# ---------------------------------------------------------------- 5. reconciliation (H3)

for r in rows(T / "h3.verdicts.csv"):
    add(f"reconciliation_verdict_{r['base'].lower().replace('+', '_').replace(' ', '')}",
        r["H3"], "verdict",
        f"H3 on the sealed window for base model {r['base']}: does MinT reconciliation "
        "improve ICB-level WIS without costing providers more than 2%?",
        rel(T / "h3.verdicts.csv"), "confirmatory",
        f"fragile={r.get('fragile', '')}. The headline is M1's verdict (decision D3).")

for r in rows(T / "h3.loo.csv"):
    add(f"reconciliation_loo_{r['base'].lower().replace('+', '_').replace(' ', '')}"
        f"_drop_{r['dropped'][:7]}", r["H3"], "verdict",
        f"H3 for {r['base']} with origin {r['dropped'][:7]} left out "
        f"(ICB upper end {num(r['icb_rel_hi'])}, provider point {num(r['provider_rel'])}).",
        rel(T / "h3.loo.csv"), "confirmatory",
        "Two of the three verdicts flip on a single origin: ETS fails without 2024-10, M1 "
        "holds without 2024-12.")

dev_h3 = ROOT / "results" / "F-reconciliation" / "h3_results.csv"
for r in rows(dev_h3):
    base = r["base"].lower().replace("+", "_").replace(" ", "")
    add(f"reconciliation_dev_{base}_{r['level']}", r["H3"], "verdict",
        f"H3 on the development window, base {r['base']} at {r['level']} level: relative "
        f"WIS change {num(r['rel'])} (95% interval {num(r['rel_lo'])}-{num(r['rel_hi'])}), "
        f"over {r['n_series']} series.", rel(dev_h3), "development",
        "Development-window reconciliation, scored before the seal was opened. The "
        "development verdicts fail for every base; the sealed window agrees except for ETS.")


# ---------------------------------------------------------------- 6. decision layer

med, med_src = grep(LOG, r"the median error is (\d+\.\d+) pp and (\d+)% fall within 10 pp")
add("decision_layer_median_error", float(med), "percentage points",
    "Median absolute error of the registered occupancy reconstruction against published "
    "KH03 occupancy, outside the COVID window, over 2,274 trust-quarters.",
    med_src, "development")

tol, tol_src = grep(LOG, r"median absolute error ≤ (\d+) percentage points and at least 80%")
add("decision_layer_tolerance", float(tol), "percentage points",
    "Registered tolerance the reconstruction had to meet: median absolute error at most "
    "this, and at least 80% of trust-quarters within 10 points.", tol_src, "development")

add("decision_layer_verdict", "illustrative only", "verdict",
    "The decision layer failed both limbs of its registered validation, so every bed number "
    "it produces ships labelled illustrative, and P(breach) is labelled a lower bound.",
    rel(ROOT / "results" / "G-decision" / "occupancy_validation.md"), "development",
    "This label must travel with every figure and table derived from the decision layer, on "
    "the site as in the repository.")

thr, thr_src = grep(PLAN, r"England (2023/24) planning guidance for the 92% line")
add("decision_layer_occupancy_threshold", 0.92, "proportion",
    "The bed-occupancy planning threshold the decision layer reports breaches of.",
    thr_src, "development",
    f"Source recorded as NHS England {thr} planning guidance, but the project's own record "
    "still marks it '[needs citation]' and says the line must be sourced before use "
    "(docs/amendment_log.md, STOP 8 entry). Do not publish the threshold with a citation "
    "until that is resolved.")


# ---------------------------------------------------------------- 7. tuning null

search = rows(ROOT / "results" / "m1-tuning" / "m1_search.csv")
add("tuning_configurations", len(search), "count",
    "Hyperparameter configurations evaluated in the registered search over the "
    "pre-registered space.", rel(ROOT / "results" / "m1-tuning" / "m1_search.csv"),
    "development")

wis = [float(r["wis_mean"]) for r in search]
spread = (max(wis) - min(wis)) / min(wis)
add("tuning_spread", round(spread, 4), "relative change",
    "Spread of mean WIS across those configurations, best to worst, computed from the "
    "search table.", rel(ROOT / "results" / "m1-tuning" / "m1_search.csv"), "development",
    "Computed by site/build_numbers.py from the wis_mean column: (max - min) / min.")


mmd = [float(r["mmd_wis_pct"]) for r in rows(ROOT / "results" / "A-noise-floor" / "noise_table.csv")
       if r["run"] == "comparison" and r["slice"] == "all"]
add("tuning_criterion_noise_floor", [round(min(mmd), 3), round(max(mmd), 3)], "per cent",
    "The seed-noise floor the tuning spread has to beat: the minimum meaningful difference "
    "in WIS from re-running the same configuration under different seeds, per target.",
    rel(ROOT / "results" / "A-noise-floor" / "noise_table.csv"), "development",
    "Column mmd_wis_pct over the three targets. The tuning spread is a range over "
    "configurations, not a standard deviation; compare like with like before saying the "
    "search 'moved nothing'.")


# ---------------------------------------------------------------- 8. what could not be tested

add("cold_start_untestable", VERDICTS["h5"], "reason",
    "H5 (cold start) was registered but could not be evaluated, and never can be on a "
    "sealed split. The recorded reason, verbatim.", rel(H / "verdicts.json"), "confirmatory")


# ---------------------------------------------------------------- 9. the audit trail

entries = re.findall(r"^### (\d+)\. \**(\d{4}-\d{2}-\d{2})\**([^\n]*)", LOG.read_text(), re.M)
bodies = re.split(r"^### \d+\. ", LOG.read_text(), flags=re.M)[1:]
add("amendments_total", len(entries), "count",
    "Amendments recorded in the pre-registration's amendment table.", rel(LOG), "confirmatory")

freeze_date, freeze_src = grep_agreed(PREREG, r"\| (2026-09-09) \(freeze\) \|")
after = [e for e in entries if e[1] > freeze_date]
add("amendments_after_freeze", len(after), "count",
    f"Amendments dated after the freeze of {freeze_date}. The remainder are dated on or "
    "before it and are marked pre-freeze in their own text.", rel(LOG), "confirmatory")

touching = [b for b in bodies if re.search(r"\bH[1-5]b?\b|\bprimary\b", b)]
add("amendments_touching_hypotheses", len(touching), "count",
    "Amendments whose text names a registered hypothesis (H1-H5, H4b) or the primary "
    "comparison.", rel(LOG), "confirmatory",
    "Counted mechanically by site/build_numbers.py: entries matching /\\bH[1-5]b?\\b|primary/.")

add("freeze_date", freeze_date, "date",
    "The date the pre-registration was frozen; nothing after it changes a hypothesis "
    "without an amendment row.", freeze_src, "confirmatory")

tag_src = ROOT / "docs" / "confirmatory_results.md"
tags = sorted(set(re.findall(r"`(prereg-v1|conf-plan-v1|conf-run-v1)`",
                             tag_src.read_text() + PREREG.read_text())))
add("tag_names", tags, "git tags",
    "The three tags that anchor the record: the frozen pre-registration, the confirmatory "
    "plan (the run's token), and the run's results.",
    f"{rel(tag_src)} and {rel(PREREG)}", "confirmatory",
    "prereg-v1 freezes the hypotheses; conf-plan-v1 is the commit the sealed run was "
    "allowed to start from; conf-run-v1 is the commit holding its results.")

unseal = json.loads((H / "unseal_entry.json").read_text())
add("confirmatory_unseal_date", unseal["timestamp"], "timestamp",
    "When the sealed window was opened, from the single line written to the unseal log.",
    rel(H / "unseal_entry.json"), "confirmatory",
    f"One line only; {unseal['sealed_rows']} sealed rows, origins "
    f"{unseal['origins'][0]} to {unseal['origins'][-1]}.")

disclosure, disc_src = grep(PREREG, r"(\*\*Disclosure: CONF is sealed going forward, "
                                    r"not unseen\.\*\*[^|]*?)(?:\|)")
add("disclosure_models_seen_sealed_months", disclosure, "quoted disclosure",
    "Which models had already been scored on the sealed months during development, and "
    "which met them first in the confirmatory run. Quoted verbatim from the project's own "
    "disclosure row.", disc_src, "confirmatory",
    "This is the sentence that forbids the site saying 'tested on data the models had "
    "never seen'. The calibration methods and the hierarchical model met the sealed months "
    "first in the confirmatory run; the baselines and the tree model did not.")


# ---------------------------------------------------------------- 10. vintage provenance

# sourced from the pre-registration, which is identical in the private repository and in
# the public snapshot, so this file rebuilds to the same bytes in both
recovered, rec_src = grep(PREREG, r"(\d+ recovered files have an Internet Archive capture)")
add("vintage_recovered_from", "the Internet Archive's captures of the NHS England year pages",
    "provenance",
    "Where file versions from before the vintage archive existed were recovered from.",
    rec_src, "development",
    f"The pre-registration's own check: {recovered.strip()!r}, each verified against the "
    "NHS England server. Files still on the server are fetched from it directly.")

manifest = (ROOT / "data" / "raw" / "manifest.jsonl")
lines = [json.loads(x) for x in manifest.read_text().splitlines() if x.strip()]
add("vintage_file_versions", len(lines), "count",
    "File versions recorded in the vintage manifest: one row per published file version.",
    rel(manifest), "development")
snapshots = sorted({l["available_from"][:10] for l in lines if l.get("available_from")})
add("vintage_snapshot_dates", len(snapshots), "count",
    "Distinct dates on which a file version became current (manifest available_from).",
    rel(manifest), "development",
    f"{snapshots[0]} to {snapshots[-1]}. Counted from the manifest, which travels with "
    "every copy of this repository; the private working repository also holds one "
    "directory per snapshot under data/raw, and site/REPORT.md records how the two counts "
    "differ.")

periods = sorted({l["period"][:7] for l in lines if l.get("period")})
add("vintage_period_range", [periods[0], periods[-1]] if periods else "NOT FOUND",
    "month range", "Range of data months covered by the archived file versions.",
    rel(manifest), "development")

_rule, _rule_src = grep(PREREG, r"\| (2018-12) \| 2018-10 \| DEV origin\. \|")
add("vintage_rule_for_months_without_a_snapshot",
    "the origin is excluded from as-of evaluation, or the month is dropped from that "
    "origin's training data; each case is listed in Appendix A with its treatment",
    "rule",
    "What happens at an origin where a data month has no surviving as-of version.",
    f"{rel(PREREG)}:258 (Appendix A)", "confirmatory",
    "Appendix A lists every such origin and period, and the amendment 'Appendix A "
    "correction' names the four truncated origins: 2018-11, 2021-10, 2025-08, 2025-09.")


# ---------------------------------------------------------------- 11. scale

import pandas as pd  # noqa: E402  (only needed for the panel)

panel = ROOT / "data" / "processed" / "ae_monthly_all_vintages.parquet"
df = pd.read_parquet(panel, columns=["org_code", "period"])
add("scale_panel_rows", int(len(df)), "count",
    "Rows in the vintage panel: one per provider, month and file version.", rel(panel),
    "development")
add("scale_provider_codes", int(df.org_code.nunique()), "count",
    "Distinct provider codes across the whole history, including codes retired at mergers.",
    rel(panel), "development")
per_month = df.groupby("period").org_code.nunique()
add("scale_provider_codes_typical_month", int(per_month.median()), "count",
    "Distinct provider codes appearing in a typical month across all archived versions of "
    "that month (median over months).", rel(panel), "development",
    "Higher than the number of providers actually scored: a month's codes accumulate over "
    "its file versions, including codes later withdrawn or merged.")
scored = [int(r["n_series"]) for r in rows(T / "primary.table.csv")]
add("scale_providers_scored_typical_month", int(sorted(scored)[len(scored) // 2]), "count",
    "Provider series actually scored in the sealed window (median over horizons).",
    rel(T / "primary.table.csv"), "confirmatory",
    f"Range {min(scored)}-{max(scored)} across horizons. This is the number to quote for "
    "'how many trusts', not the raw code count.")

icbs, icb_src = grep(PREREG, r"\*\*ICB level: the current (36)-ICB mapping, under §9\.\*\*")
add("scale_icbs", int(icbs), "count", "Integrated care boards in the current mapping, "
    "applied to the whole history.", icb_src, "confirmatory")
add("scale_regions", 7, "count", "NHS England regions in the hierarchy.",
    f"{rel(DESIGN)} (hierarchy: providers → ICBs → regions → England)", "confirmatory")

dev_origins = one(T / "dev.coverage.primary.csv", oyear="2018", horizon="1")["n_origins"]
add("scale_development_origins", int(dev_origins), "count",
    "Forecast origins in the development window.", rel(T / "dev.coverage.primary.csv"),
    "development")
add("scale_sealed_origins", len(VERDICTS["context.counted"]), "count",
    "Distinct information sets in the sealed window, the unit of every pooled statistic.",
    rel(H / "verdicts.json"), "confirmatory",
    f"{VERDICTS['context.new_origins']} sealed origins were generated; three of them share "
    "one as-of information set, proved by hash, so 19 units are counted.")

test_files = sorted((ROOT / "tests").glob("test_*.py"))
n_tests = sum(len(re.findall(r"^def test_", f.read_text(), re.M)) for f in test_files)
add("scale_automated_tests", n_tests, "count",
    "Test functions in the suite, counted from the files.", "tests/test_*.py", "development",
    f"{len(test_files)} test modules. pytest collects more node ids than this, because "
    "parametrised tests expand; run `pytest -q --collect-only` for that number, which "
    "depends on which optional dependencies are installed.")


# ---------------------------------------------------------------- 12. the live forecast

add("live_forecast_model", "raw ETS (B1), uncalibrated", "model",
    "The model published on 31 October 2026: exponential smoothing with its own simulated "
    "intervals, no conformal step and no calibration pool.",
    rule_src if False else rel(ROOT / "docs" / "handover.md"), "confirmatory",
    "Fixed at the plan tag. Under P12 any later change to it is recorded as CONF-informed.")

pub, pub_src = grep_agreed(ROOT / "docs" / "handover.md",
                           r"release day,\s+\*?\*?Thursday (8 October 2026)")
add("live_forecast_origin_release_date", pub, "date",
    "The release day the live forecast is made from; the forecast itself publishes by 31 "
    "October 2026.", pub_src, "confirmatory")

score, score_src = grep_agreed(ROOT / "docs" / "handover.md",
                             r"against the outturn published on (12 November 2026)")
add("live_forecast_first_scoring_date", score, "date",
    "When the first live forecast's horizon-1 value is scored against the outturn.",
    score_src, "confirmatory")

add("live_forecast_output_paths", ["forecasts/2026-10/ets/quantiles.parquet",
                                   "forecasts/2026-10/ets/manifest.json",
                                   "forecasts/2026-10/ets/breach_illustrative.csv"],
    "paths", "Where the published forecast is written. The directory does not exist until "
    "the run on 8 October 2026; the same layout exists for the 2026-09 dry run.",
    rel(ROOT / "docs" / "handover.md"), "confirmatory",
    "breach_illustrative.csv carries the decision layer's illustrative label in every row.")

add("live_forecast_public_scorecard", "planned, not built", "status",
    "Whether a public scorecard tracking the live forecast's accuracy exists.",
    rel(ROOT / "docs" / "portfolio_brief.md"), "post_hoc",
    "The work order asks for a GitHub Pages scorecard updated by the monthly Action; no "
    "such page is in the repository.")


# ---------------------------------------------------------------- write

OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(ENTRIES, indent=2, ensure_ascii=False) + "\n")
missing = [e["id"] for e in ENTRIES if e["value"] == "NOT FOUND"]
print(f"wrote {rel(OUT)}: {len(ENTRIES)} entries, {len(missing)} NOT FOUND {missing}")
