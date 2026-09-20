# Project dossier

> **Rewritten 2026-09-20.** This replaces the dossier of 2026-09-11, which predated the
> confirmatory run and disclaimed its own accuracy. Those 982 lines remain in git history —
> `git show 82355c7:docs/project_dossier.md` — and everything in them that was true and
> recorded nowhere else is carried forward here, including several figures derived from files
> that are not tracked and could not be recomputed. Every figure here is read from a tracked file, named beside it. Where
> a number also appears in `site/site_numbers.json` it carries the same value, because both
> are read from the same source. Nothing in this document is a recollection.

One page per question: what was asked, what was built, what was decided, what was found, and
what is still uncertain. For the detail behind any line, follow the path.

---

## 1. The question

NHS England publishes monthly A&E attendance and emergency admission figures for every
hospital trust in England, and revises them afterwards. Almost every forecast evaluation in
the literature and in practice is scored against the *revised* data, using a model trained on
revised data. If revision is material, that practice flatters the model.

**The question:** by how much? And, underneath it: are the intervals such forecasts publish
worth anything?

Answering the first needs an archive of what was published *when* — which did not exist, and
had to be rebuilt from the Internet Archive's captures of the NHS England year pages
(`docs/preregistration.md:303`: 263 recovered files have a capture, each byte-identical to
the live copy). Answering the second needs a sealed window and a pre-registration, because
calibration is exactly the thing that looks fine until it is tested out of sample.

## 2. Status, 2026-09-20

| | |
|---|---|
| Pre-registration | Frozen 2026-09-09, tag `prereg-v1`; 83 amendments, all dated and reasoned (`docs/amendment_log.md`) |
| Confirmatory run | Done 2026-09-15, tag `conf-run-v1`. The sealed window was opened **once**, at 18:04:53Z, and scored once (`results/unseal_log.jsonl`) |
| Live forecast | Raw ETS, uncalibrated, from the 8 October 2026 release; published by 31 October; first scored 12 November (`docs/handover.md` §12). The runbook insists on `--snapshot`: without it `available_from` becomes the run date, so a late ingest would drop September from the origin and push March 2027 out to horizon 7 |
| Published | Public snapshot at https://github.com/ellenmarsh1612/nhs-ae-forecast; the working repository is `nhs-ae-forecast-dev` |
| Next | The prospective window opens with the October forecast: from February 2027 the published forecast is scored month by month, which is the only test no specification has seen |

## 3. The data

| Fact | Value | Source |
|---|---|---|
| Archived file versions | 720 | `data/raw/manifest.jsonl` |
| Dates on which a version became current | 121 | same |
| Panel rows (provider × month × version) | 1,072,039 | `data/processed/ae_monthly_all_vintages.parquet` |
| Period range | 2015-06 to 2026-08 | same |
| Provider codes over the whole history | 332 | same |
| Provider series actually scored | 194 (median over horizons) | `results/H-confirmatory/tables/primary.table.csv` |
| Hierarchy | providers → 36 ICBs → 7 regions → England | `docs/stage_h_design.md` |

**The revision mechanism, which the project got wrong at first.** The scope document assumed
files were revised in place. They are not: each revision gets a new URL and the original stays
on the server, which is what makes a true as-of archive possible at all
(`README.md`; `docs/scope.md` carries a correction banner).

**As-of and final.** As-of mode trains on the figures published at the origin; final mode
trains on today's. The outturn scored against is the same in both — "Truth for scoring is
always final mode over all periods" (`src/nhs_ae/evaluate/asof.py`). So the comparison
isolates the training vintage, which is what H4 asks about.

**Four origins are short.** Where a month had no surviving as-of version, training stops at
the last month that has one and the horizons shift with it: 2018-11 and 2021-10 on the
development window, 2025-08 and 2025-09 on the sealed one. Appendix A of the pre-registration
lists them; it was itself corrected on 2026-09-15 (`docs/amendment_log.md`, "Appendix A
corrected").

## 4. The models, and where each one died

| Model | What it is | Outcome |
|---|---|---|
| **B0** seasonal naive | Last year's same month, with intervals from its own trailing log errors | The baseline everything is measured against. Beaten by 38–48% in winter |
| **B1 ETS** | Exponential smoothing, native simulated intervals | **The live model.** Best of the statistical baselines; chosen by a rule fixed before the sealed window opened |
| **B2 STL+ARIMA** | Seasonal decomposition then ARIMA | Never competitive at provider level |
| **M1 LightGBM** | Global quantile model, conformal calibration | The registered test model for H1, H2 and H4 |
| M1 tuned | 16 pre-registered configurations | **Null result.** Spread across configurations 9.2%, against a seed-noise floor of 2.3–4.1% on the same metric — the search moved less than the noise on most targets (`results/m1-tuning/m1_search.csv`, `results/A-noise-floor/noise_table.csv`) |
| M1 v2 | Per-horizon models + 3-month level | **Rejected.** The 3-month level destroyed calibration |
| **M1 v3** | Per-horizon models, 12-month level | The learner under the primary comparison |
| M2a–M2c | Hierarchical Bayesian ladder at ICB level | Winter-h3 ICB error +63.7%, +64.6% and +73.4% against ETS; M2b and M2c rejected by the retention rule, M2a retained (`docs/results.md`) |
| M2d | Student-t random-walk level, centred | Kept by an explicit override of the retention rule (`docs/amendment_log.md` entry 33) |
| M2d2, M2e | Regime volatility; winter conversion term | Both rejected against M2d |
| M2f | Shared latent factor | **Not identified, and not run** — it traded against the ICB walks and the shared seasonality |
| **`m2d_corr`** | M2d plus correlated ICB innovations | **The frozen M2**, tag `m2-frozen-v1`. Its intervals are what H2's M2 clause tested |
| M2f-r2 → r4 | The redesign: two-stage seasonality, zero-sum walks, a national walk, COVID-window volatility | **Excluded by D1** on 2026-09-12: its winter-h3 ICB advantage moved from +23.5% (35 origins) to +12.4% (69 origins), past the pre-committed limit. Never frozen, never tagged, runs only as an unpublished shadow |
| ETS/M2f-r4 ensemble | Equal-weight quantile average | **Rejected by its own registered rule**, on a coverage guard it missed by 0.03 pp |

The pattern across the whole ladder: **structure moved calibration, tuning moved nothing.**
Hyperparameter search shifted WIS by less than seed noise, while the v2 level feature dropped
90% coverage from 0.76–0.83 to 0.57–0.70 (`docs/results.md`).

## 5. Calibration, and the guard

Ten calibration candidates were compared on the development window (Stage D). The registered
rule selected **M1 + pooled conformal**, and the acceptance criterion — 0.87–0.93 coverage in
every origin-year cell — **was not met by any candidate**, which was recorded as an amendment
before the confirmatory run rather than quietly relaxed (`docs/amendment_log.md`, "The DEV
calibration target is not met, and Stage H proceeds").

**G1, the all-zero guard.** ETS forecasts exactly zero for some series at origin 2020-05; a
pooled conformal set built on ≤12 such scores produces upper quantiles inflated by a factor of
about 10⁶. G1 marks those forecasts failed rather than letting them flatter a comparison. It
was registered on 2026-09-13, before its re-run, and it matters: without it, reconciliation
appears to improve ETS at ICB level by 53%, and with it, it costs 9%
(`results/F-reconciliation-G1/README.md`). Every confirmatory table applies it.

**DtACI, the adaptive alternative, failed for a reason that was not COVID.** When its level
reaches zero the rule reads the largest pooled score, and the 97.5% bound then reaches
1.37 × 10⁹. The blow-ups are not confined to the COVID window: at 2018 origins its mean WIS
is **8.35 times** pooled conformal's. That figure was derived from a scores file that is not
tracked, so it is recorded here and nowhere else.

## 6. Reconciliation

MinT-shrink reconciliation was tested up the hierarchy, and a second comparison (F2) set it
against models coherent by construction. On the development window H3 failed for all three
bases. On the sealed window it fails for the headline model and for STL+ARIMA, holds for ETS,
and two of those three verdicts flip if a single origin is dropped (§9).

The finding underneath: reconciliation helps the model whose aggregates are worst and costs
the models that are already reasonable. For M1 it adds about 5% to provider-level error while
leaving ICB-level error statistically unchanged.

## 7. The decision layer — illustrative only

Admissions forecast → bed-days via a lognormal length of stay → probability of exceeding 92%
G&A occupancy → escalation beds. A validation check was registered **before** it was run
(2026-09-09): median absolute error at most 5 percentage points against published KH03
occupancy, and at least 80% of trust-quarters within 10 points.

**It failed both limbs**: median error 8.7 pp, 57% within 10 points, over 2,274 trust-quarters
outside COVID (`results/G-decision/occupancy_validation.md`). Every number the layer produces
therefore ships labelled illustrative, in the memo and in every row of the live
`breach_illustrative.csv`. A simple alternative — carrying the latest published occupancy
forward — does far better (median error 2.38 pp, 95.5% within 10 points, same rows) but was
not registered, so it is exploratory and cannot replace the registered method without a new
pre-registration.

Four further things travel with it, three of which are recorded only here:

- **P(breach) has no demonstrated skill.** Every candidate's Brier score (0.26–0.31) is worse
  than forecasting the observed breach rate, and a constant base-rate forecast also wins on
  mean cost-loss expense (0.272–0.273 against 0.274–0.298).
- **The published table's "median error (pp)" column is actually the mean** — 37.3, against a
  true median of 2.06 (`stage_g.py` L97 against L325). Anyone quoting that column is quoting
  a mean labelled as a median.
- **74 of 390 trust-months reconstruct to over 100% occupancy**, which is the sharpest single
  demonstration of why the layer cannot be operational.
- **A seal exposure that was never remediated.** `results/G-decision/los_coefficients.csv`
  holds a fit made on 2026-09-10 that used KH03 quarters inside the sealed window. It predates
  the seal hardening, which touched the splits, the backtest CLI and the calibration path but
  not this file. It is one more reason nothing from this layer is confirmatory.

And the 92% line itself is a planning convention whose current source is
**still unconfirmed** (`docs/confirmatory_plan.md:669` cites 2023/24 planning guidance;
`docs/amendment_log.md` records that it "still carries a [needs citation] marker").

## 8. The split, and the seal

Origins were split on 2026-09-10: **DEV** 2018-04 to 2023-12 (69 origins), **CONF** 2024-01 to
2025-09 (21 origins, 19 distinct information sets), **PROSPECTIVE** from the live forecast on.

**What sealing did and did not buy.** The pre-registration's own disclosure is blunt about it:
B0, B1, B2 and every M1 variant had already been scored on those months before the split, so
for them CONF is a **re-test**. It is a first test only for the calibration methods and for
M2. PROSPECTIVE is the only window no specification has seen. No claim in this project goes
further than that.

**The machinery.** A seal guard refuses to load sealed rows without a token; the token is the
commit of the plan tag; the first tokened call may unseal only at the runner's own hash
commit, with a clean tree and imports from the project root; every unsealing appends a line to
a log that is checked afterwards. Thirteen pre-flight checks run before the run is allowed to
start — environment drift, input pins, a quarantine of the pre-seal score files, a rebuild of
the vintage table compared by hash. The design is `docs/stage_h_design.md`; the plan and its
pre-flight items are `docs/confirmatory_plan.md`.

**What actually happened.** One line in the log, at 2026-09-15T18:04:53Z, 21 sealed rows,
origins 2024-01 to 2025-09. No prior lines, no witness lines, no environment drift, 21 pinned
inputs, 175 tables written (`results/H-confirmatory/provenance.json`).

**Three duplicate origins.** The as-of inputs for 2025-07, 2025-08 and 2025-09 hash equal, so
those three origins carry one information set, and pooled statistics count 19 units, not 21
(decision D7). Every deterministic model's forecasts at the three origins are bit-identical;
`m2d_corr` re-samples, so its forecasts differ and are checked against registered
seed-stability limits instead (`results/H-confirmatory/d7_check.csv`).

## 9. What the confirmatory run found

| Registered test | Verdict | Fragile? |
|---|---|---|
| **Primary** — do the recommended forecast's 90% intervals cover ≈90%? | **within tolerance**: 87.5, 88.3, 88.7, 89.6, 89.5, 90.3% by horizon | no |
| **H1** — beat seasonal naive by >15% in winter | **confirmed**: −47.6%, −44.8%, −38.4% by target | no |
| **H2, M1 clause** — conformal M1 misses the band at h ≥ 4 | **confirmed** (under-covers: 0.814–0.846) | no |
| **H2, M2 clause** — the hierarchical model's intervals hold ±5 pp | **refuted** (over-covers: 0.970–0.993) | no |
| **H3** — reconciliation improves ICB accuracy | **fails** for the headline model | **yes** |
| **H4** — revisions do not change accuracy | **confirmed**: worst cell 0.37% against a 2% bar | no |
| **H4-original** | **does not hold**, as predicted | no |
| **H4b** — late submissions outweigh revisions | **not confirmed**: 16/19 origins for all-types attendances, 0/19 for the other two | n/a |
| **H5** — cold start | **not evaluable**, and never testable on a sealed split | n/a |

**Three registered expectations failed**: H2's M2 clause, H3 and H4b. The M2 failure is the
sharpest: the model built to be the well-calibrated one is, on the sealed window, the worst
calibrated of those designed to be calibrated, and its winter-h3 ICB error is about a quarter
worse than M1 + pooled.

**The headline finding.** Uncalibrated, the tree model's "90%" intervals cover 74.9% at one
month ahead falling to 68.3% at six. With the calibration layer, 87.5% to 90.3%. That gap —
roughly 20 points of overconfidence, closed by a layer that costs nothing at forecast time —
is the result this project exists to demonstrate.

**The live model's own numbers.** Raw ETS at ICB level covers 97.7–98.2% on the sealed window
against 90% nominal: conservative, erring towards over-warning. Under P12 the live model is
fixed as of the plan tag and any change made because of this is recorded as CONF-informed, so
it publishes as fixed with the conservatism stated.

## 10. Limitations, in the order they bite

1. **One winter.** Every winter statistic — H1, H3, H4, F2 — rests on five origins whose
   horizon-3 targets are March 2024 and December 2024 to March 2025. The bootstraps resample
   providers *within* that winter. On the development window ETS's yearly coverage ranged from
   0.51 to 0.96; that is the scale of the variation this design cannot see.
2. **The sealed outturns can still move.** Every confirmatory verdict was scored against the
   data as they stood on 2026-09-15. NHS England revises twice a year, so the November 2026
   revision can change outturns inside the sealed window. Nothing in the pre-registration
   says what happens then, and re-scoring after a revision would not be a second confirmatory
   test — it would be a second look. The verdicts should be read as "against the data as at
   2026-09-15", and any re-score reported as exploratory.
3. **CONF is a re-test** for the baselines and the tree model (§8).
4. **Fragility is real where it is reported.** Two of H3's three verdicts turn on one origin.
   H1's and the primary's do not.
5. **M2's sampling never met its target.** 9 of the 21 sealed fits exceed R-hat 1.05, the
   worst at 1.122 with a minimum bulk ESS of 26. No fit was excluded on diagnostics, by rule
   (`results/H-confirmatory/m2_fits.csv`).
6. **The decision layer is illustrative** (§7), and its threshold is unsourced.
7. **The machine-learning model's COVID flag uses the retrospective window** (2020-03 to
   2021-06, `models/gbm.py`). That is hindsight inside an as-of harness: at an origin in early
   2020 the forecaster could not have known the window's end.
8. **Three reporting conventions were not kept.** Stage F reports no coverage by origin-year;
   the F2 figures carry no intervals; and Stages D and E apply a cross-target, provider-level
   minimum meaningful difference to ICB-level statistics, where the registered rule says per
   target and metric.
9. **Some development-window figures have no committed artefact** — the default-M1-against-ETS
   comparison, the 2020 and 2025 origin-year coverage quoted in `docs/results.md`, and the
   v2→v3 ablation. Recomputing them now would touch sealed rows, so they stand as reported or
   not at all.
10. **The 2020 cells are unassessable.** Only two development origins in 2020 fall outside the
   COVID window, so the year fails the ≥6-origin rule; its coverage (73–81%) is reported from
   the Stage D table, marked unassessed.

## 11. The decision record

Seven decisions were put to the maintainer, each with a recommendation and each recorded
before the work it governs. All seven are decided; the amendment log holds the full text.

| | Decision | Outcome |
|---|---|---|
| D1 | Does M2f-r4 go to the sealed window? | **Exclude** — the pre-committed condition flipped on the 69-origin re-run |
| D2 | The primary comparison's rule | Two-way interval rule, three outcomes |
| D3 | H3's headline | M1's verdict, for consistency with the primary |
| D4 | Scope of the all-zero guard | G1, as issued, and nothing more |
| D5 | The live model | **(b) uncalibrated raw ETS**, which takes Stage H off the live critical path. The trap it avoids: pooled conformal at the live origin calibrates on origins 2025-05 to 2026-09, five of which are sealed, so a calibrated live forecast could not be built until the sealed window had been opened |
| D6 | Which M1 carries H1, H2 and H4 | Default M1, as registered |
| D7 | How the duplicate origins count | 19 information sets |

Numbered STOP gates punctuated the work, running to nine (1 and 4 to 9 are recorded in
`docs/`); the last, STOP 9, was the written go-ahead to tag the plan and run. **Two gates
never got a decision row**: STOP 1 and STOP 4. Their outcomes are visible in the artefacts,
but the amendment table does not record them as decisions, which is a gap in the discipline
the rest of the project kept. Its three residual choices — the closed list of permitted live work, keeping
Künsch blocks for the bootstrap, and a failure limit of 4 of 19 M2 fits — were taken before
the run.

## 12. Errata: corrections this project made to itself

Kept because a record of what was got wrong, and when it was caught, is part of what makes
the rest credible.

- **The ETS seed never reached the sampler.** Under statsmodels 0.15 `np.random.seed` did not
  reach `ETSResults.simulate`, so every B1 interval before 2026-09-12 was unseeded Monte
  Carlo. Fixed with a test; the confirmatory run's P13 check shows B1 differing from its
  pre-seal file for exactly this reason, and the other three models identical.
- **The ingest dropped 358,581 rows and exited 0.** Without xlrd and openpyxl installed the
  build silently skipped every XLS file. The build now refuses rather than continuing.
- **+91.7% could not be reproduced.** M2f-r4's inside-COVID figure was corrected to +88.6%
  the day after it was first reported.
- **Appendix A listed the wrong truncated origins**, corrected 2026-09-15 before the run.
- **The previous dossier's NCtR occupancy figures were wrong** (7.14 pp / 61.4% against the
  artefact's 7.1 pp / 49%), as were its archive and amendment counts. This rewrite is the fix.
- **Still uncorrected in `docs/results.md`**, found when this dossier was rewritten: ETS's
  horizon-6 coverage is printed as 0.85 when the value is 0.8450; M1 v3 is said to "roughly
  tie" ETS on all-types attendances when it is +3.6% [+0.5, +6.6]; and "every method
  over-covers for 2021–22 origins" is false — M1 raw (0.56–0.68), the status quo (0.81–0.87)
  and EnbPI (0.80–0.90) all under-cover.
- **Appendix A's "63–79% of months revised" counts late submitters as changes**, which is a
  different thing from a value being revised. Still uncorrected in the pre-registration, which
  can only be changed by amendment.
- **A Stage F row-count bug dropped 153 of 1,242 M1 origin-target-horizons**, fixed in
  `d70d0a2` before any table was read. Recorded here because the count cannot be recovered
  from a tracked file now that the bug is fixed.
- **The M2 timings were contention, not cost.** 48.9 minutes per fit against 1.6 minutes for
  fits whose per-origin diagnostics are identical. The compute plan that used 98 s per fit was
  therefore optimistic by a factor of about thirty under load.
- **A "stale label" that was not stale.** After the run, the assistant reported that
  `verdicts.json`'s description of H2's M2 clause contradicted an amendment. It does not: the
  wording is the frozen design's own sentence, and the claim came from reading a truncated
  quotation. Recorded in `docs/confirmatory_results.md` as a labelling note, not an erratum.

## 13. Definition of done

The work order that set this project out is not part of the repository, so its ten-item
definition of done survives only here. Status as at 2026-09-20.

| # | Item | Status |
|---|---|---|
| 1 | Seal guard, exactly one unseal entry | **Met.** One line, 2026-09-15T18:04:53Z |
| 2 | The noise floor used as the minimum meaningful difference throughout | **Partly.** Used in Stages D and E as cross-target means, not per target and metric; not used in Stage F's prose |
| 3 | A specification curve | **Not met.** Stage B was skipped on 2026-09-10 and no amendment ever waived this item |
| 4 | 0.87–0.93 coverage at every horizon and origin-year on the development window | **Not met, and recorded.** Best candidate 4.7 pp outside; the amendment "The DEV calibration target is not met, and Stage H proceeds" says so explicitly |
| 5 | M2 frozen and dated before the confirmatory run | **Met.** `m2-frozen-v1` |
| 6 | Occupancy validated against KH03 with a stated tolerance | **Check met, reconstruction failed** — hence illustrative only (§7) |
| 7 | The confirmatory plan tagged before unsealing | **Met.** `conf-plan-v1`, and the run refused to start anywhere else |
| 8 | An amendment log in which every row is a decision | **Partly.** 83 rows, all dated and reasoned, but some early rows that describe results are not flagged as such, and STOP 1 and STOP 4 have no row |
| 9 | `results.md` separates exploratory from confirmatory | **Met**, with a superseded banner added 2026-09-19 |
| 10 | The live forecast published by 31 October 2026 | **Pending.** The path is built and rehearsed; the run is 8 October |

## 14. Where everything lives

| Want | Path |
|---|---|
| What was registered | `docs/preregistration.md` (§7 hypotheses, §10 amendments) |
| Every amendment, readable | `docs/amendment_log.md` (`make amendments` regenerates it) |
| What the sealed run found | `docs/confirmatory_results.md`; raw output in `results/H-confirmatory/` |
| The development-window record | `docs/results.md` |
| How the run was specified and policed | `docs/confirmatory_plan.md`, `docs/stage_h_design.md` |
| The live forecast | `docs/handover.md` §12, `src/nhs_ae/live.py`, `forecasts/` |
| Every number a public page may use | `site/site_numbers.json`, with a source path each |
| Verification, disagreements, what is stale | `site/REPORT.md` |

**How to check any of it.** `make install && make test` runs the suite and prints the baseline
and coverage tables from the shipped result files. `make numbers` rebuilds
`site/site_numbers.json` from the tracked sources; CI fails if it differs by a byte.
