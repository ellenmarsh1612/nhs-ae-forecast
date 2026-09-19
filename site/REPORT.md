# Verification report for the public snapshot and site/

Written 2026-09-19, from the private working repository at commit `03355fb` (before the
`site/` commits below). It records what was built, what could not be found, where two
tracked files disagree, and which claims in `docs/` the confirmatory run of 2026-09-15 no
longer supports.

Everything in sections 4 to 6 was checked in this session against the file named. Nothing
here is reported on trust.

## 1. What was built

| Artefact | What it is |
|---|---|
| `site/site_numbers.json` | 191 entries: every number the portfolio site may show, each with `value`, `unit`, `description`, `source_path`, `label` and `caveat`. Built by `site/build_numbers.py`, which reads each value from a tracked file and refuses to guess: a pattern that matches no line, or more than one, stops the build. |
| `site/build_numbers.py` | The extractor. Run it with `make numbers`. |
| `site/figures/` | Six figures, each as `.svg`, `.png` and `.caption.txt`, built by `site/build_figures.py` **from `site_numbers.json`**, so a figure and the text beside it cannot disagree. |
| `site/fan_chart.py` | Draws the live forecast's fan chart once `forecasts/2026-10/ets/quantiles.parquet` exists; until then it exits 1 and `live_forecast_fan_placeholder.*` stands in. |
| `site/build_snapshot.py` | Assembles the public snapshot. Its docstring lists everything excluded and why. |
| `site/print_tables.py` (snapshot only) | Prints the baseline table and the coverage table from the shipped CSVs; `make test` runs it after the suite. |

Labels used in `site_numbers.json`: `confirmatory` (116 entries — fixed before the sealed
window was opened, scored once), `development` (64), `exploratory` (9 — registered but not
confirmatory, or reported alongside), `post_hoc` (1), and one entry with no label, the one
that could not be found.

## 2. Repositories

| Repository | URL | Visibility |
|---|---|---|
| Private working repository | https://github.com/ellenmarsh1612/nhs-ae-forecast-dev | private |
| Public snapshot | https://github.com/ellenmarsh1612/nhs-ae-forecast | public |

The private repository was renamed from `nhs-ae-forecast` to `nhs-ae-forecast-dev` on
2026-09-19, and the local remote was repointed to the new URL in the same step. That
matters: GitHub redirects the old URL only until another repository takes that name, which
the public snapshot then does. A checkout left pointing at the old URL would afterwards have
been pushing private work at a public target.

## 3. Fresh-clone verification

Run on 2026-09-19 on macOS 15.2, arm64, Python 3.13, from a clone of the snapshot commit —
not from the working tree, so what was tested is what is published.

```
git clone <snapshot> verify3 && cd verify3
python3 -m venv .venv && source .venv/bin/activate
make install      # exit 0, 123 s
make test         # exit 0, 923 s (15 min 16 s)
```

**735 passed, 0 failed, 0 skipped**, in 916 s. `make test` then printed both headline tables,
reproduced here exactly as a stranger sees them:

```
Baseline table — H1: error against the seasonal-naive baseline
(MASE, horizon 3, winter, provider level, sealed window, 5 origins)

  target                         change          95% interval   verdict
  all-types attendances          -47.6%      [-52.5%, -42.1%]   confirmed
  Type 1 attendances             -44.8%      [-50.1%, -39.4%]   confirmed
  admissions via A&E             -38.4%      [-44.6%, -31.6%]   confirmed

  Pre-registered bar: a 15% reduction, with the interval entirely beyond it.

Coverage table — the primary comparison
(90% intervals, provider level, as-of, sealed window, 19 origins)

  horizon    calibrated  uncalibrated        95% interval
  1               87.5%         74.9%      [85.1%, 90.6%]
  2               88.3%         72.0%      [86.5%, 90.9%]
  3               88.7%         71.9%      [86.2%, 91.7%]
  4               89.6%         70.8%      [88.1%, 92.0%]
  5               89.5%         69.3%      [87.5%, 92.5%]
  6               90.3%         68.3%      [88.4%, 92.5%]

  Registered tolerance: 85–95% at every horizon. Verdict: within tolerance.
  The uncalibrated column is the same forecasts without the calibration layer.
```

An earlier run, before `make install` was changed to include PyMC, gave **716 passed, 2
skipped** in 787 s with a 70 s install. The 19-test difference is exactly `tests/test_m2.py`
(16) and `tests/test_m2_draws.py` (3), which need PyMC and are not collected without it —
verified by diffing the collected node ids of both environments. The published Makefile and
CI workflow install the `models` extra, so the whole suite runs from a clean clone.

`site/site_numbers.json` also rebuilds **byte-identically inside the snapshot**, which the
CI workflow checks with `git diff --exit-code`. Getting there required one fix: a caveat in
the vintage entry counted snapshot directories under `data/raw/`, which the snapshot does not
ship, so it rebuilt differently there. The count now comes from the manifest alone and the
directory comparison lives in section 5 of this report.

## 4. NOT FOUND

One requested id could not be sourced from any tracked file.

### `sealed_wis_by_model_by_target`

**Searched:** `results/H-confirmatory/tables/` (all 175 CSVs), `results/H-confirmatory/verdicts.json`,
`docs/confirmatory_plan.md`, `docs/stage_h_design.md`.

**Why it does not exist.** No sealed-window statistic selected the published model, so there
is no such table to select it with. The sealed run reports WIS only as ratios against
M1 + pooled at aggregate levels (`tables/f2.wis__level=*.csv`) and inside the H3
reconciliation comparison; the primary comparison is coverage, and H1 uses MASE.

**What actually chose the published model**, recorded in `site_numbers.json` as
`live_model_selection_rule` and quoted verbatim from `docs/preregistration.md:227`: the
D5 = (b) amendment of 2026-09-12, which applied the pre-commitment in
`docs/d1_precommitments.md` to a **development-window** re-run. No sealed row informed it.
The site must not describe raw ETS as "the model that won on the sealed data".

## 5. Numbers two tracked files disagree about

Each row was checked against both files in this session. "Authority" is the later or
better-evidenced source.

| Quantity | Value A | Value B | Authority |
|---|---|---|---|
| Test count | `README.md:39` "82 unit tests"; `docs/build_strategy.md:18` "32 tests pass"; `docs/project_dossier.md:248` "213 tests in 16 files"; `docs/handover.md:36` "241 tests" | 480 `def test_` functions in 41 files (`tests/test_*.py`); 735 node ids collected in the pinned environment | The files. All four documents are stale; `README.md` is the one a stranger meets first and is off by roughly seven times. The public README states no count. |
| Archived file versions | `docs/build_strategy.md:9`, `docs/project_dossier.md:59` "500 files" | 720 rows in `data/raw/manifest.jsonl` | The manifest. |
| Snapshot dates | `docs/project_dossier.md:184` "117 availability dates" | 121 distinct `available_from` dates in the manifest; 118 directories under `data/raw/` | The manifest. The three extra dates (2026-09-12, -13, -15) are revisions that became current without a new directory — verified by set difference. |
| Amendments | `docs/project_dossier.md:778` "46 / 46" | 83 entries in `docs/amendment_log.md`, generated from §10 | The generated log. |
| NCtR occupancy variant | `docs/project_dossier.md:467` "7.14 pp and 61.4%, against 7.31 pp and 62.0%" | `results/G-decision/occupancy_validation.md`: `trust+nctr` 7.1 pp / **49%**; `trust_same_rows` **8.1** pp / **60%** | The artefact, which `docs/preregistration.md:229` and `docs/amendment_log.md` both match. The dossier is wrong on all three figures. |
| ETS reconciliation, H3 | `docs/results.md:388`, `docs/project_dossier.md:661`: ICB −53.1%, provider **+3,449%**, region −98.3%, England −100.0% | `results/F-reconciliation-G1/README.md`: ICB **+9.0%**, provider **+5.4%**, region **+4.6%**, England **−13.4%** | The G1 re-run. G1 is the guard the confirmatory run applies; the unguarded figures are an artefact of all-zero ETS forecasts at origin 2020-05. |
| Vintage archive contents | `README.md:94` "committed vintage archive (CSV only; XLS ignored)" | `git ls-files data/raw` returns 290 `.xls`/`.xlsx` files | The repository. The exclusion was removed and the README never updated. |
| Providers / trusts | `docs/scope.md:102` "~180 providers"; `docs/portfolio_brief.md:54` "~200 trusts" | 332 provider codes over the whole history; 194 provider series scored in the sealed window (`tables/primary.table.csv`, median over horizons) | The scored tables. `site_numbers.json` carries both, as `scale_provider_codes` and `scale_providers_scored_typical_month`, with the difference explained. |

Not a disagreement, though it was reported as one: the M2f-r4 COVID figure. Both
`docs/project_dossier.md:639` and `docs/m2f_redesign.md` carry the correction from +91.7% to
**+88.6%**, and say the first figure could not be reproduced.

## 6. Claims in `docs/` that the confirmatory results no longer support

All of these are in files **excluded from the public snapshot** by the maintainer's
decision of 2026-09-19, so none reaches a public reader. They remain in the private
repository and should be corrected or marked superseded there.

### Verified in this session

1. **`README.md:7` — "Late submissions matter more than revisions."** H4b is *not
   confirmed*: the late-submission component is larger at 16 of 19 origins for all-types
   attendances, and **0 of 19** for Type 1 attendances and for admissions
   (`tables/h4b.table.csv`). This is one of the three registered expectations that failed.
2. **`README.md:31` — "Status: week 1 — ingestion and vintage archive."** The project has
   since completed a pre-registered confirmatory run. Everything downstream in that README
   is frozen at week one.
3. **`README.md:26-28` — the bed decision layer presented without its failed validation.**
   `results/G-decision/occupancy_validation.md` records median error 8.7 pp against a 5 pp
   tolerance and 57% of trust-quarters within 10 pp against 80% required: the layer is
   illustrative only, by registered rule.
4. **`docs/memo_draft.md:9-11, 47-50` — "The admissions ranges … lean low: outturns fall
   above them more often than they should."** On the sealed window the published model
   *over*-covers: 97.7–98.2% at ICB level (`tables/headline.icb_raw_ets.as_issued.by_horizon.csv`)
   and 95.0–96.9% at provider level (`tables/headline.by_horizon.csv`, `b1_ets`,
   `point_raw`), against 90% nominal. The memo's central caveat now points the wrong way,
   and the "lower bound" framing at `:47-50` rests on it. This is the client-facing document.
5. **`docs/results.md:388` — the ETS reconciliation row.** Superseded by the G1 re-run, as
   in section 5.
6. **`docs/results.md:155-158` — "Not yet evaluated: H2 (M2 clause), H3, H4b … H5."** All
   four were evaluated or formally declared not evaluable on 2026-09-15.

### Reported by the audit, consistent with the files but not re-derived here

7. `docs/results.md:162-164` — "ETS … the best calibrated at every horizon" (on the sealed
   window it over-covers more than the calibrated primary does).
8. `docs/results.md:151-152`, `:432-447` — the operational model presented as open, and
   M2f-r4 promoted as "the route that works", after D1 = exclude removed it.
9. `docs/project_dossier.md` — says `conf-plan-v1` does not exist, the unseal log is empty,
   there is no forecast code and no `forecasts/` directory, H5 is undecided, and H2's M2
   clause would fail by *under*-covering. The file is dated 2026-09-11, four days before the
   run, and its own header says it was never independently fact-checked.
10. `docs/build_strategy.md:82` — "All six winters are usable", against the one winter the
    sealed window actually provides.

## 7. Decisions taken while building

- **`data/raw/` (106 MB) is not in the snapshot.** It is redistributable under the Open
  Government Licence, but it is large and rebuildable with `nhs-ae-ingest`. The parsed
  panel (1.9 MB) ships instead, so `make test` and every figure run with no download, per
  the brief's default. `data/raw/manifest.jsonl` (628 KB) ships, because it is the evidence
  for the vintage-provenance numbers.
- **Absolute paths are left in the run's integrity records.**
  `results/H-confirmatory/provenance.json`, `unseal_entry.json`, `README.md` and
  `results/unseal_log.jsonl` contain paths from the machine the run was made on, including
  `/Users/trin3615/.stage_h/conf-plan-v1.token`. The token's *value* is the plan commit
  `14202e2`, public by design. Editing these files would break the hashes that make the
  record checkable, so they ship byte-identical and `PROVENANCE.md` says why.
  `docs/stage_h_run_sheet.md`, which has the same paths and no integrity role, is excluded.
- **The monthly ingest workflow is not in the snapshot.** It commits to its own repository
  and fetches from NHS England on a schedule. The snapshot gets a test workflow instead.
- **No secrets were found.** A scan of all tracked files for keys, tokens, passwords and
  credential files returned nothing, and no `.env`, `.pem` or `.key` file is tracked.
- **No patient-level data.** Every figure in the repository is a published trust-month
  total.

## 8. Still needs a human

1. **The 92% occupancy threshold.** `docs/confirmatory_plan.md:669` sources it to NHS
   England's 2023/24 planning guidance, but `docs/amendment_log.md` records that it "still
   carries a [needs citation] marker". `site_numbers.json` carries the threshold with that
   caveat attached. Confirm the source before it appears on a public page.
2. **`docs/portfolio_brief.md:139`** still describes the repository as private, and its
   asset table points at `docs/results.md`, `docs/project_dossier.md` and
   `docs/memo_draft.md`, which the snapshot excludes. Update it for the published state.
3. **The stale documents in the private repository** (section 6) are still stale there.
4. **The memo must be corrected before it ships to anyone**, on item 4 of section 6.
