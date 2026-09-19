"""Build the public snapshot: a fresh tree with no history, holding only what a stranger
needs to check the confirmatory claims and re-run the tests.

What is left out, and why:

* ``data/raw/`` (106 MB of archived NHS England files). Redistributable under the Open
  Government Licence, but large and rebuildable: ``nhs-ae-ingest run`` fetches it. The
  1.9 MB processed panel ships instead, so nothing here needs a download to check.
* documents whose claims the confirmatory run no longer supports (``docs/results.md``,
  ``docs/project_dossier.md``, ``docs/memo_draft.md``, ``docs/scope.md``,
  ``docs/build_strategy.md``, ``docs/m2f_redesign.md``), by the maintainer's decision of
  2026-09-19. They stay in the private repository; site/REPORT.md lists every claim.
* ``docs/stage_h_run_sheet.md``, a machine-specific runbook holding absolute paths.
* the monthly ingest workflow, which commits to its own repository and fetches from NHS
  England on a schedule. The public snapshot gets a test workflow instead.

Usage: python site/build_snapshot.py [--out DIR] [--force]
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT.parent / "nhs-ae-forecast-public"

# (source, destination) — destination defaults to the source path
TREES = [
    "src", "tests", "site",
    "results/H-confirmatory/tables",
    "data/reference",
]
FILES = [
    "requirements-lock.txt",
    "pyproject.toml",
    "docs/confirmatory_results.md",
    "docs/preregistration.md",
    "docs/amendment_log.md",
    "docs/confirmatory_plan.md",
    "docs/stage_h_design.md",
    "docs/stage_h_stop9.md",
    "docs/stage_h_defaults.md",
    "docs/stage_h_pins.json",
    "docs/handover.md",
    "docs/portfolio_brief.md",
    "docs/d1_precommitments.md",
    "tools/render_amendment_log.py",
    # the confirmatory run's own record, byte-identical
    "results/H-confirmatory/confirmatory_results.md",
    "results/H-confirmatory/verdicts.json",
    "results/H-confirmatory/provenance.json",
    "results/H-confirmatory/unseal_entry.json",
    "results/H-confirmatory/README.md",
    "results/H-confirmatory/d7_check.csv",
    "results/H-confirmatory/p13_check.csv",
    "results/H-confirmatory/m2_fits.csv",
    "results/H-confirmatory/timings.csv",
    "results/unseal_log.jsonl",
    # reconciliation summaries, guarded and unguarded
    "results/F-reconciliation/README.md",
    "results/F-reconciliation/h3_results.csv",
    "results/F-reconciliation/h3_results.md",
    "results/F-reconciliation/coherence_vs_calibration.csv",
    "results/F-reconciliation/coherence_vs_calibration.md",
    "results/F-reconciliation-G1/README.md",
    # sources site/build_numbers.py reads, so the numbers file rebuilds here too
    "results/m1-tuning/m1_search.csv",
    "results/A-noise-floor/noise_table.csv",
    "results/A-noise-floor/README.md",
    "results/A-noise-floor/noise_floor.md",
    "results/D-calibration/coverage_by_horizon_year.csv",
    "results/D-calibration/README.md",
    "data/raw/manifest.jsonl",
    # decision layer: summaries only, and every one carries its failed validation
    "results/G-decision/README.md",
    "results/G-decision/occupancy_validation.md",
    "results/G-decision/occupancy_validation.csv",
    "results/G-decision/breach_probabilities.csv",
    "results/G-decision/los_coefficients.csv",
    # the panel, so `make test` and the figures run with no download
    ("data/processed/ae_monthly_all_vintages.parquet",
     "data/processed/ae_monthly_all_vintages.parquet"),
]
SKIP_NAMES = {"__pycache__", ".pytest_cache", ".DS_Store", ".ipynb_checkpoints"}


def copy_tree(src: Path, dst: Path) -> int:
    n = 0
    for p in sorted(src.rglob("*")):
        if any(part in SKIP_NAMES for part in p.parts) or p.is_dir():
            continue
        target = dst / p.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, target)          # copyfile follows symlinks, which we want
        n += 1
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--force", action="store_true",
                    help="replace an existing snapshot built by this script")
    args = ap.parse_args(argv)
    out: Path = args.out

    if out.exists():
        if not args.force:
            raise SystemExit(f"{out} exists; pass --force to rebuild it")
        if not (out / ".snapshot-built-by").exists():
            raise SystemExit(f"{out} exists and was not built by this script; refusing")
        for child in out.iterdir():           # keep .git: a rebuild is a new commit, not a
            if child.name == ".git":          # new repository
                continue
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    out.mkdir(parents=True, exist_ok=True)
    (out / ".snapshot-built-by").write_text("site/build_snapshot.py\n")

    total = 0
    for tree in TREES:
        total += copy_tree(ROOT / tree, out / tree)
    for item in FILES:
        src_rel, dst_rel = item if isinstance(item, tuple) else (item, item)
        src = ROOT / src_rel
        if not src.exists():
            raise SystemExit(f"missing: {src_rel}")
        (out / dst_rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, out / dst_rel)
        total += 1

    for name, text in SUPPORT.items():
        path = out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text.lstrip("\n"))
        total += 1

    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                            text=True, check=False).stdout.strip()
    (out / "PROVENANCE.md").write_text(PROVENANCE.lstrip("\n").format(commit=commit))
    print(f"built {out} from {commit[:12]}: {total + 1} files")
    return 0


# --------------------------------------------------------------------------- files

SUPPORT: dict[str, str] = {}

SUPPORT[".gitignore"] = """
.snapshot-built-by
__pycache__/
*.pyc
.pytest_cache/
.venv/
.DS_Store
data/cache/
data/processed/backtest*/
data/processed/stage_*/
forecasts/*/**/draws/
"""

SUPPORT["LICENSE"] = """
MIT License

Copyright (c) 2026 Ellen Marsh

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

---

DATA

The NHS England statistics in this repository, and every figure derived from
them, are published by NHS England under the Open Government Licence v3.0:
https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/

Source: NHS England, "A&E Attendances and Emergency Admissions" (monthly
provider-level files), "KH03 bed availability and occupancy" and the
provider-to-ICB mapping. Contains public sector information licensed under the
Open Government Licence v3.0.
"""

SUPPORT["Makefile"] = """
.PHONY: install test tables figures numbers amendments panel lint

install:   ## install the package and its test dependencies
\tpip install -e ".[dev,xls,stats,gbm,plots,models]"

test:      ## run the test suite, then print the two headline tables
\tpytest -q
\t@python site/print_tables.py

tables:    ## print the baseline table and the coverage table
\t@python site/print_tables.py

numbers:   ## rebuild site/site_numbers.json from the tracked sources
\tpython site/build_numbers.py

figures:   ## rebuild site/figures/ from site_numbers.json
\tpython site/build_figures.py

amendments: ## regenerate docs/amendment_log.md from preregistration.md section 10
\tpython tools/render_amendment_log.py

panel:     ## rebuild the vintage panel from a local archive (needs data/raw, not shipped)
\tnhs-ae-ingest build

lint:
\truff check src tests
"""

SUPPORT[".github/workflows/tests.yml"] = """
name: tests

on:
  push:
    branches: [main]
  pull_request:
  workflow_dispatch:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - name: Install
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev,xls,stats,gbm,plots,models]"
      - name: Test
        run: pytest -q
      - name: Headline tables
        run: python site/print_tables.py
      - name: Numbers file is current
        run: |
          python site/build_numbers.py
          git diff --exit-code site/site_numbers.json
"""

SUPPORT["site/print_tables.py"] = '''
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
    print("\\nBaseline table — H1: error against the seasonal-naive baseline")
    print("(MASE, horizon 3, winter, provider level, sealed window, 5 origins)\\n")
    print(f"  {'target':<28}{'change':>9}{'95% interval':>22}   verdict")
    names = {"att_all": "all-types attendances", "att_type1": "Type 1 attendances",
             "adm_via_ae": "admissions via A&E"}
    for r in read("h1.table.csv"):
        if r["model"] != "m1_lightgbm" or r["role"] != "decides":
            continue
        lo, hi = float(r["rel_lo"]) * 100, float(r["rel_hi"]) * 100
        print(f"  {names[r['target']]:<28}{float(r['rel']) * 100:>8.1f}%"
              f"{f'[{lo:.1f}%, {hi:.1f}%]':>22}   {r['verdict']}")
    print("\\n  Pre-registered bar: a 15% reduction, with the interval entirely beyond it.")

    print("\\nCoverage table — the primary comparison")
    print("(90% intervals, provider level, as-of, sealed window, 19 origins)\\n")
    print(f"  {'horizon':<9}{'calibrated':>12}{'uncalibrated':>14}{'95% interval':>20}")
    raw = {r["horizon"]: r for r in read("headline.by_horizon.csv")
           if r["model"] == "m1_lightgbm_v3_raw"}
    for r in read("primary.table.csv"):
        h = r["horizon"]
        lo, hi = float(r["lo"]) * 100, float(r["hi"]) * 100
        print(f"  {h:<9}{float(r['point']) * 100:>11.1f}%"
              f"{float(raw[h]['point_raw']) * 100:>13.1f}%"
              f"{f'[{lo:.1f}%, {hi:.1f}%]':>20}")
    print("\\n  Registered tolerance: 85–95% at every horizon. Verdict: within tolerance.")
    print("  The uncalibrated column is the same forecasts without the calibration layer.\\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

SUPPORT["README.md"] = """
# nhs-ae-forecast

**Does backtesting a forecasting model on revised official statistics flatter it?**

NHS England publishes monthly A&E figures for every hospital trust, then revises them.
This project recovered every version of every published file since 2015, stored each under
the date it became current, and used that archive to train models on exactly what was known
at the time. Across the four registered models and three targets, training on revised data
rather than the figures published at the time changes winter accuracy by at most **0.37%**,
and the ranking of models does not move.

The second finding is the one most forecasts get wrong. Uncalibrated, the machine-learning
model's "90%" intervals contain the outturn **68-75%** of the time. With a conformal
calibration layer, the same forecasts contain it **87.5-90.3%** of the time — inside the
tolerance band registered before the test data were opened.

Everything here was pre-registered: hypotheses, decision rules and a sealed evaluation
window, with 83 dated amendments and a single, logged opening of the seal.

> **What "sealed" does and does not mean.** The window 2024-01 to 2025-09 was sealed going
> forward, not unseen. The baselines and the machine-learning model had been scored on those
> months before the split; for them this is a re-test. It is a first test only for the
> calibration methods and the hierarchical Bayesian model. The project's own disclosure says
> so, in `docs/preregistration.md` section 10, and no claim here goes further than it.

## From clone to the numbers

```
git clone https://github.com/ellenmarsh1612/nhs-ae-forecast.git
cd nhs-ae-forecast
python -m venv .venv && source .venv/bin/activate
make install && make test
```

`make install` installs the package with its test, model and plotting extras. `make test`
runs the suite and then prints the two headline tables: the baseline table (how much the
model beats seasonal naive in winter) and the coverage table (how often the intervals
contain the outturn, with and without calibration). Nothing is downloaded: the parsed
vintage panel ships with the repository.

Both tables are read from `results/H-confirmatory/tables/`, the output of the single
confirmatory run. To print them without running the suite: `make tables`.

`make install` includes PyMC and nutpie, which the hierarchical Bayesian model and its
tests need, so the whole suite runs from a clean clone. `site/REPORT.md` records the
fresh-clone verification: what was run, how long it took and what passed.

## What is in here

| Path | What it holds |
|---|---|
| `docs/preregistration.md` | The frozen hypotheses and decision rules, section 7, and every amendment, section 10 |
| `docs/amendment_log.md` | The same amendments as one readable entry each, generated by `make amendments` |
| `docs/confirmatory_results.md` | What the sealed run found, hypothesis by hypothesis, with the caveats |
| `docs/confirmatory_plan.md`, `docs/stage_h_design.md` | How the run was specified and policed before it was allowed to start |
| `docs/handover.md` | How the live forecast is produced, checked and published |
| `results/H-confirmatory/` | The run's own output: verdicts, 175 tables, provenance, the unseal record |
| `results/F-reconciliation*/`, `results/G-decision/` | Reconciliation and decision-layer summaries |
| `site/site_numbers.json` | Every number the portfolio site may show, each with the file it was read from |
| `site/figures/` | Those numbers as figures, built by `make figures` |
| `src/`, `tests/` | The pipeline and its suite |

## Headline results, in one table

| Registered test | Verdict |
|---|---|
| Primary: do the recommended forecast's 90% intervals cover about 90%? | **within tolerance** (87.5-90.3%) |
| H1: does the model beat seasonal naive by more than 15% in winter? | **confirmed** (-38% to -48%) |
| H2, M1 clause: do the model's own conformal intervals under-cover? | **confirmed** |
| H2, M2 clause: are the hierarchical model's intervals calibrated? | **refuted** — they cover 97-99% |
| H3: does reconciliation improve ICB accuracy? | **fails**, and the verdict is fragile |
| H4: do data revisions change accuracy? | **confirmed** — they do not, within 0.37% |
| H4b: do late submissions outweigh revisions? | **not confirmed** — only for all-types attendances |
| H5: cold start | **not evaluable**, and never testable on a sealed split |

Three of these went against what the pre-registration predicted. They are reported here,
not buried: `docs/confirmatory_results.md` has a section called "What did not work".

Two standing caveats travel with everything above. The winter tests rest on **one winter**
(five forecast origins), and two of the three reconciliation verdicts flip if a single
origin is dropped. Every figure derived from the bed-occupancy decision layer is
**illustrative only**: its registered validation failed, at a median error of 8.7 percentage
points against a 5-point tolerance.

## The live forecast

The forecast published on 31 October 2026, for December 2026 to March 2027, is **raw ETS**,
uncalibrated, chosen by a rule committed before the sealed window was opened. On that window
its intervals cover 97-98% where 90% is intended: wider than nominal, erring towards
over-warning. That is published as a known property rather than tuned away, because changing
the model in response to sealed-window results would contaminate it.

## Data, licences and rebuilding the archive

Code is MIT. The data are NHS England statistics, published under the Open Government
Licence v3.0 and reproduced here under it: *Contains public sector information licensed
under the Open Government Licence v3.0.* See `LICENSE`.

`data/processed/ae_monthly_all_vintages.parquet` (1.9 MB) is the parsed panel: one row per
provider, month and file version. The 106 MB archive of original files it was built from is
not shipped. To rebuild it:

```
nhs-ae-ingest discover --years 2025-26 2026-27   # list the published file URLs
nhs-ae-ingest run                                # archive today's vintage and rebuild
nhs-ae-ingest build                              # rebuild the panel from a local archive
```

Historical versions, from before the archive existed, were recovered from the Internet
Archive's captures of the NHS England year pages.

## Provenance

See `PROVENANCE.md` for what this snapshot is, what was left out of it and why, and
`site/REPORT.md` for the verification record: the fresh-clone run, every number that could
not be found in a tracked file, and every place two files disagree.
"""

PROVENANCE = """
# Provenance of this snapshot

This repository is a snapshot, without history, of the private working repository
`nhs-ae-forecast-dev` at commit `{commit}`. It was assembled by
`site/build_snapshot.py`, which lists in its own docstring everything left out and why.

## What is here

* `src/`, `tests/` — the code and its suite, unchanged.
* `docs/` — the pre-registration, the amendment log, the confirmatory plan and design, the
  confirmatory results, the live-forecast handover, and the brief for the portfolio site.
* `results/H-confirmatory/` — the sealed run's own output, byte-identical, including its
  provenance and unseal records.
* `results/F-reconciliation*/`, `results/G-decision/` — summaries of the reconciliation and
  decision-layer work. **Every decision-layer figure is illustrative only**: the registered
  validation failed (median error 8.7 pp against a 5 pp tolerance), and that label travels
  with every table derived from it.
* `site/` — one machine-readable file of every number the portfolio site may show, each with
  the path it was read from, plus the figures built from it.
* `data/processed/ae_monthly_all_vintages.parquet` — the vintage panel (1.9 MB).

## What is not here

* `data/raw/` — 106 MB of archived NHS England files. Rebuild it with
  `nhs-ae-ingest run`, which fetches from NHS England, or `nhs-ae-ingest discover` to list
  the URLs first. The panel above is the parsed result, so nothing here needs it.
* Documents the confirmatory run no longer supports, and a machine-specific runbook. They
  remain in the private repository; `site/REPORT.md` lists every claim and where it failed.

## Absolute paths in the run records

`results/H-confirmatory/provenance.json`, `unseal_entry.json`, `README.md` and
`results/unseal_log.jsonl` contain absolute paths from the machine the confirmatory run was
made on, including the path of the token file it read. The token's *value* is the plan
commit `14202e2`, which is public by design. These files are the integrity record of the
run: editing them would break the hashes that make the record checkable, so they are left
exactly as the run wrote them.
"""


if __name__ == "__main__":
    raise SystemExit(main())
