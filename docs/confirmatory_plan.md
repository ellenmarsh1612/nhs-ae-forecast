# Confirmatory plan: Stage H on CONF

> **Status: v1.0 (2026-09-15), final for STOP 9. Nothing in this plan has been run on CONF.**
> On Ellie's written go-ahead, the commit holding this version is tagged `conf-plan-v1`
> (annotated) and pushed (P9); the tag's timestamp is the evidence. Every worktree's
> `results/unseal_log.jsonl` is empty or absent (six worktrees on 2026-09-15: four empty logs,
> two agent worktrees with none), and there is no witness file (P8). The seal accepts only the
> tag commit as the token, and the first tokened call unseals only at the runner's hash commit
> on the tag or on an `--amendment` descendant (P11; `src/nhs_ae/evaluate/splits.py`,
> `seal_rules.py`).
>
> Since v0.4 (2026-09-11) all seven decisions are made (§8): D1 = exclude and D5 = (b) make the
> live forecast uncalibrated raw ETS and take Stage H off the live critical path. Every
> pre-flight item is closed except P9, the tag itself (§7): the runner is built (P3), the seal
> hardened (P11), the inputs pinned (P4, P5; §7.1), the pre-seal files quarantined (P13), and
> the final DEV dry run exits 0 (`results/H-dryrun/d8ff305dbbd7/`). v1.0 brings the text
> written before those decisions into line with them, with the runner and with
> `docs/stage_h_design.md` v2.2. No rule, threshold or decision changes, except that §6 states
> M2's fit-failure limit over the 19 counted origin units, as the design does (4 or more),
> where v0.4 said "more than 20% of an M2 model's origins" (5 or more of 21); Ellie chose the design's reading at STOP 9
> (D-21). The changes are listed in §12; the STOP 9 package is `docs/stage_h_stop9.md`,
> with `docs/stage_h_defaults.md` and `docs/stage_h_run_sheet.md`.
>
> The go-ahead is given on this text together with the design's [default] choices (the two §10
> rows "Stage H implementation details (P3)") and P12's exception for residuals the frozen
> models compute on their training data (design §2.1). Any of these that Ellie overrules is
> changed, with an amendment row, before the tag.
>
> v0.3 folds in two independent adversarial reviews: statistics and decision rules, and seal
> integrity with fidelity to the pre-registration. Every number quoted from them was re-checked
> on 2026-09-11 from DEV rows or metadata only; no sealed row was scored. The changes are
> listed in §11.

This plan fixes, before anything is unsealed, the four things the work order's H1 asks for
(`../CLAUDE_CODE_BRIEF.md`, Stage H; the work order lies outside the repository, so the tag does
not freeze it):

1. the exact model specifications under test;
2. the exact calibration method;
3. the hypotheses and their decision rules;
4. the primary comparison and the slice it is evaluated on.

It also fixes the run's inputs, outputs and failure handling, so that nothing is decided after
an outcome has been seen. Deviations from `docs/preregistration.md` are listed in §9; each
has an amendment row, cited by date and title (P7). If the work order and the
pre-registration conflict, the pre-registration wins.

**The finding that most changes the schedule** (written before D5; it is the reason D5 was
decided, and under D5 = (b) it no longer sets the schedule). A calibrated live forecast cannot
be produced before Stage H has run.
- *The live pools are sealed.* At the live origin 2026-10, pooled conformal would draw on the
  12 most recent resolved forecast origins at each horizon: 2025-05 to 2026-04 at horizon 6,
  five of them CONF origins; 2025-10 to 2026-09 at horizon 1, whose targets up to 2026-02 are
  sealed. Computing those errors means scoring sealed rows.
- *The seal stays in code.* `SEALED_TARGETS` is permanent. Before P11, every later calibration
  run would have needed the token and added a log line. P11's post-run state (`conf-run-v1`)
  lets the guard pass sealed rows without the token and without a log line, so the Definition
  of Done's single unseal entry can hold through later live work.
- *As decided (2026-09-12).* D5 = (b): the live model is uncalibrated raw ETS (after
  D1 = exclude), so Stage H is **off** the live critical path, and the live path computes no
  forecast error from a sealed row. Stage H still runs for the confirmatory claims. A
  calibrated live forecast would put it back on that path (§10).

---

## 1. What CONF is, and what it can and cannot show

| | |
|---|---|
| Origins | 2024-01 to 2025-09: 21 monthly origins, 12 in origin-year 2024 and 9 in 2025 (`evaluate/splits.py`) |
| Distinct as-of information sets | **19.** Between the 2025-07 origin (as-of 2025-07-10) and 2025-11-13 no archive snapshot appeared, apart from one 2022-10 revision [verified from the archive's snapshot dates]. In as-of mode, origins 2025-07, 2025-08 and 2025-09 therefore all train to 2025-06 and forecast 2025-07 to 2025-12 at h = 1–6. Their calibration pools are identical, because nothing resolves between them. The DEV analogues confirm it: M1 v3 raw forecasts at truncated origin 2018-11 equal 2018-10's in 98.8% of rows, and 2021-10 equals 2021-09 in 97.3% (statistics review). D7 = (a) counts them once; their three as-of slices hash equal (§7.1) |
| Target periods | 2024-01 to 2026-02 in final mode. In as-of mode the last three origins stop at 2025-12. Every target is in the vintage archive, which runs to period 2026-08 (latest new file 2026-09-10; later manifest entries, to 2026-09-13, are identical re-sightings), pinned under P4 |
| Winter slice at h = 3 | 5 origins: 2024-01, 2024-10, 2024-11, 2024-12 and 2025-01, for target months March 2024 and December 2024 to March 2025. That is one winter and a fragment. None of the five is a truncated origin |
| COVID window | CONF lies entirely outside 2020-03 to 2021-06. Every CONF origin-year × horizon cell is assessable |

**CONF is sealed going forward, not unseen** (amendment "Disclosure", 2026-09-10). The
specifications fall into two groups:
- **Re-tests.** B0, B1, B2 and M1 (default, tuned, v2 and v3) were scored on all 73 old-window
  origins, CONF included, before the seal, and aggregate results were read (for example
  default M1's 90% coverage of 0.92 for 2025 origins). For these specifications, including the
  uncalibrated B1, B2 and M1 intervals in the descriptive headline (§4), CONF is a re-test.
- **First tests.** CONF is a first test only for specifications created after 2026-09-10: the
  Stage D calibration method with G1, Stage F reconciliation and the frozen M2 (`m2d_corr`).
  M2f-r4 is not on CONF (D1 = exclude); its first genuine test is PROSPECTIVE, as an
  unpublished live shadow.

PROSPECTIVE is the only test that no specification has seen.

**Exposures of sealed-window data, disclosed so the write-up cannot overclaim.**
1. *Pre-seal per-row CONF scores were on disk, readable without a token.*
   - `data/processed/backtest/scores.parquet` held 526,847 sealed rows (B0, B1, B2 and default
     M1, both modes, with outturns, WIS, MASE, coverage and PIT).
   - `backtest_m1_v3/scores.parquet` held 132,717 [both counts verified from origin and period
     columns]; the tuned and v2 files held about as many (seal review).
   - The matching forecast files were there too.

   All were readable without a token. On 2026-09-15 they were moved, without being parsed, to
   `data/processed/quarantine/pre-seal/`, each hashed before and after the move (P13). They are
   still readable there, and none is opened again except `backtest/forecasts.parquet`, for
   step 3's values-only reproducibility check.
2. *Stage G, 2026-09-10.* A bed-days coefficient fit used quarters up to 2026-04, which lie in
   the sealed window (`results/G-decision/los_coefficients.csv`, 154 rows with `as_of`
   2026-09-10). It fed nothing: the breach illustration uses coefficients as of its 2023-10
   origin (`evaluate/stage_g.py`, `breach_illustration`). The fit is only written to the CSV.
3. *Unguarded paths, closed by P11.*
   - `nhs-ae-backtest summary --include-sealed` printed the pre-seal CONF scores without a
     token. It is deleted.
   - `calibrate/online.py` and the Stage F error step computed forecast errors without calling
     the guard. `first_release`, `calibrate` and `_median_errors` now call it.
4. *Choices made with old-window knowledge.* D2 and D6 are chosen knowing the old-window
   results, which include CONF targets: the H1 result, whose winter slice contains 7 sealed
   target months, and default M1's 0.92 coverage for 2025 origins, read before Stage D was
   designed.

**Limits, stated now:**
- **One winter.** A CONF confirmation describes these providers in these five target months,
  not a typical winter. Bootstrap intervals over providers or ICBs are *within-period*; they
  miss between-winter variation.
- **The effect varies a lot between winters.** For M1 v3 raw against B0 at winter h = 3 on
  DEV (exploratory), all three targets clear H1's bar in only 1 of the 4 winter seasons the
  statistics review scored (the run's DEV side shows five, 2018/19 to 2022/23), although
  the pooled DEV effect (−28% to −34%) is about twice the bar. In the 2019-20 season, all-types
  attendances give −19.1% [−25.2, −13.8]; in 2020-21, admissions give −19.5% [−25.7, −12.2]
  [verified 2026-09-11 by re-running the statistics review's DEV-only script]. A "not
  confirmed" H1 on CONF is therefore weak evidence against the effect.
- **Calm period.** CONF has no regime shift comparable to COVID. Good calibration there says
  nothing about behaviour under a shock.

## 2. Specifications under test (frozen)

| Role | Specification | Where it is fixed | On CONF |
|---|---|---|---|
| Baseline | **B0**: seasonal naive with trailing growth; intervals from its own in-sample log errors | prereg §5; amendment "B0's intervals" | re-test |
| Baseline | **B1 (ETS)**: AICc choice among the four registered candidates; 1,000 simulated paths (seed 0, reaching statsmodels only from `9a17011`: amendment "B1 (ETS): the simulation seed now reaches statsmodels"; earlier B1 forecasts are unseeded); `min_obs` = 30; quantiles floored at 0 | prereg §5; amendment "B1 and B2 made concrete"; `models/statistical.py` | re-test |
| Baseline | **B2 (STL+ARIMA)**: robust STL with a seasonal window of 25; AICc over four ARIMA orders; Gaussian quantiles | same | re-test |
| **Registered M1 for H1, H2 and H4** | **Default M1** (`m1`): global LightGBM with in-model conformal on a 12-month window | amendments "M1 v2" (2026-09-09: "the frozen H1/H2 tests refer to `m1`") and "M1 specified as implemented" (2026-09-09); status labels (2026-09-10) | re-test |
| Point model of the recommended forecast | **M1 v3 raw** (`m1_v3_raw`): tuned hyperparameters, one model per horizon, 12-month level, no in-model conformal step, `min_train_rows` = 200 | amendments "M1 v3" and "Stage D design"; `models/__init__.py` | re-test; reported alongside H1 and H4 |
| **Recommended calibrated forecast (primary, §4)**; not the live forecast (D5 = (b)) | **M1 v3 raw + pooled conformal + G1** | STOP 4 selection by the registered rule (`results/D-calibration/stop4.txt`); G1 (§2.2) | first test of the calibration |
| Reconciliation (R1) | **MinT-shrink, quantile by quantile**, on calibrated B1, B2 and M1 v3 raw, with one "rest" node per ICB for providers that have no base forecast, plus G1 | amendments "Stage F design" and "Stage F implementation details" (2026-09-11); `reconcile/mint.py`, `evaluate/stage_f.py` | first test |
| Bayesian model | **M2 frozen = `m2d_corr`** at ICB level (36 ICBs, current mapping) | amendment "M2 specification FROZEN" (2026-09-11); tag `m2-frozen-v1` (16d47dd) | first test |
| Phase-1b hierarchical model | **M2f-r4** (commit b77430e): **not on CONF** (D1 = exclude, 2026-09-12); an unpublished live shadow | amendments M2f-r2, r3 and r4; "D1 = exclude" | not tested |

### 2.1 Pooled split conformal plus G1 (frozen at STOP 4, with G1)

This is the method implemented in `calibrate/online.py` (`calibrate(..., methods=("pooled",))`)
and registered in the "Stage D design" amendment:
- **Scale and scope.** It works on the log1p scale, separately per target, horizon and central
  interval (50/80/90/95%).
- **Scores.** It uses the CQR scores of the 12 most recent resolved forecast origins at that
  horizon, pooled across the level's series. It makes no adjustment below 10 pooled scores.
- **Adjustment.** The conformal quantile is taken at level min(1, (1 − a)(1 + 1/n)). Adjusted
  quantiles are sorted and floored at zero.
- **Timing.** A forecast from origin t′ for month P enters calibration only at the first origin
  whose as-of data contain P, using the first-published outturn.
- **Scoring** is always against the latest revision (the truth snapshot, §5).

At CONF origins the pools come from forecasts, DEV-period and earlier-CONF, that had resolved
by that origin, so the pools must advance through CONF: the run builds them itself and reads no
DEV first-release or calibration cache (P5). Periods whose original release was lost enter
calibration when their first archived version appears (2025-11-13), after the last CONF origin,
so they enter no CONF pool.

### 2.2 Guard G1: failed base forecasts (registered 2026-09-13, `8caf9d5`; implemented `fd0182a`)

**Rule.** A base forecast whose quantiles are all zero, for a series whose last observed month
is positive, is a failed forecast. It is excluded from every calibration pool, from the error
covariance, and from reconciliation inputs; in reconciliation the series becomes part of its
ICB's rest node. It is not calibrated: the issued forecast for that series is the failed one.

**In scoring, failed forecasts are scored as issued.** A zero forecast gets its real WIS, and
for coverage it counts as not covered. Every verdict is also shown with failed forecasts
dropped, and failed counts are reported per model and level.

**Why.** In Stage F on DEV, ETS forecast exactly zero at every level at origin 2020-05.
England's pooled set holds at most 12 scores, so one such forecast (a log-scale score of about
14, the log of the outturn itself) inflated upper quantiles by a factor of up to about
e¹⁴ ≈ 10⁶ until 2021-10. The largest England 95% quantile reached 9.7×10¹⁰ and the largest
97.5% quantile 4.8×10¹² [verified from `data/processed/stage_f/cal_b1_england.parquet`]. MinT
then pushed those quantiles down to the providers. Zero forecasts also occur on DEV for
STL+ARIMA (229 provider rows spread over many origins from 2017-12) and M1 v3 raw (up to 6)
(`results/F-reconciliation/calibration_blowups.csv`).

**What G1 changes.** G1 alters the STOP 4 method, and it could alter the contest that method
won (ETS + pooled's worst cells are all in 2021, the year after the blow-up). P2 therefore
re-ran the STOP 4 table with G1, under the rule that **the STOP 4 selection stands whatever that
re-run shows** and a different winner is reported as a finding. The registered rule still
selected M1 + pooled (`7ac8f3d`; row "P2 re-run with G1"). G1 caps nothing and leaves the
small aggregate pools as registered (D4).

## 3. Hypotheses and decision rules

**Common computation.**
- **Two-forecast comparisons** call
  `paired_bootstrap(a=reference, b=tested, unit="series", keys=("series", "target", "origin", "horizon", "period"))`
  with 1,000 resamples, seed 0 and 2.5/97.5 percentiles. rel = (mean over units of the tested
  forecast's per-unit mean) ÷ (the same for the reference) − 1, so **negative means the tested
  forecast is better**. The reference → tested pairs are:
  - H1: B0 → M1;
  - H3: calibrated base → MinT;
  - H4: as-of → final.
- **Coverage** is a one-model statistic. The point estimate is the row-weighted pooled share
  of scored rows (provider × target × origin) whose outturn lies inside the interval, computed
  unrounded. Its interval resamples units and recomputes that same share.
- **Band edges are inclusive**: 0.85 ≤ coverage ≤ 0.95. The verdict names its direction
  (over- or under-covering).
- **Definitions.** Winter means target months December to March (`harness.py`). The MASE scale
  is the in-sample mean absolute lag-12 difference of the training series at the origin
  (amendment "MASE scale"; identical across models on all 7,471 paired DEV rows, statistics
  review).
- **Which origins count** follows D7 = (a): the 19 distinct information sets, with the
  21-origin version reported alongside.
- **Sensitivity and fragility.** Every verdict is decided by its registered rule, and each
  comes with a sensitivity range:
  - for H1, H3 and H4, the minimum and maximum over the five leave-one-origin-out subsets;
  - for coverage, §4's two-way interval.

  A verdict whose threshold falls inside that range is labelled **fragile**. Design §7.3–§7.8
  (row "Stage H implementation details (P3): statistics") fixes the composite rules: H1's
  overall verdict, H3's two clauses, H4's 2% calls and ranking, and which horizons decide a
  coverage verdict. An H1, H3 or H4 verdict is also fragile if any leave-one-origin-out
  subset's verdict differs from the full sample's.
- **DEV side-by-side** (§5): the same statistic for each DEV winter season (winter-h3
  statistics) or each assessable DEV origin-year (coverage), with its minimum and maximum.

| # | Hypothesis (registered wording in prereg §7) | Forecasts (reference → tested) | Slice on CONF | Decision rule |
|---|---|---|---|---|
| **H1** | M1's provider-level MASE at h = 3, winter, at least 15% lower than B0's | B0 → **default M1** (its median), as registered. M1 v3 raw's median is reported alongside | provider; h = 3; winter; the 5 origins; as-of; per target | **Per target:** *confirmed* if rel_hi < −0.15. Otherwise *not confirmed* (refuted, as registered), qualified as *point estimate meets the bar* (rel ≤ −0.15), *partial support* (−0.15 < rel < 0) or *no improvement* (rel ≥ 0). **Overall:** *confirmed* only if all three targets are confirmed (as at `backtest-v1`); otherwise *not confirmed*, with the per-target labels |
| **H2, M1 clause** | Conformalised M1 does *not* achieve 90% coverage within ±5 pp at horizons ≥ 4 | **default M1** with its in-model conformal step, as registered | provider; h = 1–6; all months; as-of; 90% central interval; pooled over providers and targets (as in `results/backtest-v1/coverage_by_horizon.csv`) | The prediction is *confirmed* if coverage is outside [0.85, 0.95] at any horizon ≥ 4 (direction named); *refuted* if it is inside at **every** horizon 1–6; *neither* if it is outside only at horizons 1–3. Point estimates decide; the two-way intervals (§4) give the fragility label |
| **H2, M2 clause** | M2's 90% intervals achieve coverage within ±5 pp at every horizon | frozen `m2d_corr`, own posterior intervals (no conformal step) | **ICB level**, the level at which M2 exists: it was specified, fitted and frozen there from Stage E onward (the §9 fallback names this level, but its trigger, provider-level M2 failing to sample, was never tested, since provider-level M2 was never built); h = 1–6; all months; as-of; pooled over ICBs and targets | *Confirmed* if 90% coverage is inside [0.85, 0.95] at every horizon; *refuted* if outside at any (direction named). **Phase:** M2 is phase 1b under §5, because it was never sampled at provider level. This clause is therefore a phase-1b test run in Stage H, and the row "Phase-1b tests brought into Stage H" overrides the freeze-time deferral explicitly (§9). R-hat and ESS are reported and exclude no fit. *DEV context (exploratory):* coverage by horizon on the 35 ladder origins, all months, was 0.916, 0.840, 0.880, 0.838, 0.852 and 0.839 (`results/E-m2/ladder_results.csv`). Outside COVID, ICB coverage was 0.96. On calm CONF data the expected failure is **over**-coverage, the less dangerous direction |
| **H3 (R1)** | Reconciliation improves ICB-level WIS (95% interval excluding zero) **and** worsens provider-level WIS by no more than 2% | calibrated base → MinT-shrink, per base (B1, B2, M1 v3 raw), as in the Stage F design | ICB and provider; h = 3; winter; the 5 origins; as-of; targets pooled within a series | **Per base:** *holds* if the ICB interval lies entirely below 0 **and** the provider point estimate is ≤ +2%, as `evaluate/stage_f.h3_table` reads the registered wording. The provider interval is reported. **The headline is M1's verdict** (D3). Region is reported with a caution (bootstrap over 7 series); England is "n/a" (one series). The R2 clause is phase 1b and not tested |
| **H4** (reframed) | Final-mode winter-h3 provider WIS within 2% of as-of, and the same model ranking in both modes | as-of → final, for B0, B1, B2 and **default M1** (as registered); M1 v3 raw alongside | provider; h = 3; winter; the 5 origins; per target | **Exploratory on CONF** (amendment "§9 applied to CONF"). Rule as registered; the ranking is computed on the rows every model scored in both modes. M1 + pooled and M2 are excluded |
| **H4-original** | a ranking change, or an apparent improvement over B0 differing between modes by more than 5 pp | as H4 | as H4 | Descriptive. "Improvement over B0" is the relative winter-h3 WIS change against B0; the as-of and final values are differenced in percentage points |
| **H4b** | Late submissions outweigh value revisions | the training-leakage decomposition | the trailing-12-month England totals at the CONF origins | The registered two-component verdict: confirmed if the late-submission component is larger at more than half the origins. The original releases of periods 2025-07 to 2025-09 were lost; their first archived versions appeared on 2025-11-13 (§1, §2.1). Provider-months that are final-only for that reason are also reported as a separate "lost originals" split (descriptive): at each origin, the final provider-months in periods after its as-of end month and up to M−1 (design §7.10). On CONF these are periods 2025-07 and 2025-08, at origins 2025-08 and 2025-09 only, outside the 19 origins D7 counts. **Labelled *seen*:** `results/backtest-v1/training_leakage.csv` already covers the CONF origins. P14 confirmed the window alignment at the truncated origins |
| **H5** | Cold start: M2 against M1 on post-merger series | — | — | **Not evaluable on CONF, and never testable on a sealed split after Stage H.** M2 exists only at ICB level. The current 36-ICB mapping is applied to the whole history, so no ICB series has a cold start. A provider-level M2, which the merged-trusts rule (2026-09-10) anticipated, was never built |

**H2, M2 clause: sampling.** This follows the amendment "Sampling rule for the H2 M2 clause: Text A selected" (2026-09-11), and is flagged *[describes a result]*. Text A was selected because the seed-stability check returned STABLE (`5271eb2`). Both Text A and Text B were written before the check (`ea9ab01`).

> M2 sampling diagnostics degrade monotonically with origin date. Across the 69 DEV
> origins, median max R-hat rises from 1.015 (2018-19) to 1.069 (2023) and median min
> bulk ESS falls from 199 to 63 (Spearman 0.77 and -0.82). CONF and the live origin both
> lie after 2023, so the fits carrying the H2 M2 clause are expected to be the worst
> sampled in the project. **No fit is excluded on diagnostics**; the plan's rule (report
> everything, fail only on crashes) stands. A seed-stability check pre-specified at the
> three worst late DEV origins found forecast quantiles stable across seeds within the
> registered threshold. The H2 M2-clause verdict therefore stands as reported, with the
> sampling trend stated as a limitation.

Three accuracy notes on the opening sentences were committed with the text before the run. They are recorded in the amendment row:
- the pattern is a trend, not a monotone sequence;
- the 2018–19 ESS figure is 224, not 199;
- "the worst sampled" holds for the frozen M2's own fits, since M2f-r4's DEV fits already sample worse.

The check's statistic was the between-seed quantile shift as a fraction of the 50% interval width, over 16,524 ICB rows. It gave a median of 2.2% and a 95th percentile of 8.3%, against limits of 5% and 20%. The write-up states the trend as a limitation of the H2 M2 clause.

**F2 on CONF (secondary, descriptive; row "F2 on CONF").** It runs although M2f-r4 is excluded
(D1), since `m2d_corr` is coherent by construction. The contenders are:
- ETS + pooled and M1 + pooled, each with G1, each with and without MinT;
- `m2d_corr`.

For each, at ICB, region and England level, the report gives:
- the coherence gap, which for M2 measures median non-additivity;
- 90% and 50% coverage by horizon and by origin-year;
- winter-h3 WIS relative to M1 + pooled (England's interval n/a).

It uses the 19 CONF origins D7 counts (the 21-origin version in separate tables) and, for WIS,
the five winter-h3 origins; its DEV side covers all 69 DEV origins. The DEV pattern gives
expectations, not hypotheses: MinT over-covers the aggregates, and `m2d_corr` under-covers
England.

**Multiplicity.** No family-wise correction was registered, and none is added now. Each
hypothesis has its own rule. Every one is reported whatever the outcome, with the primary
comparison named in advance. No secondary result may be promoted to headline status after the
run.

## 4. Primary comparison (D2)

**Is the project's recommended calibrated forecast within ±5 pp of nominal 90% coverage at every horizon?** Under D5 = (b) this is not the live forecast, which is uncalibrated raw ETS.

**Measure.** For each h = 1–6, cov90_h is the share of scored rows (provider × target × origin)
whose outturn lies inside the 90% central interval of **M1 v3 raw + pooled conformal + G1**.
- Pooling: over providers and the three targets, each row weighted equally, computed
  unrounded.
- Slice: provider level, all months, as-of, the CONF origins counted under D7.

**Interval.** A 95% percentile interval from 1,000 two-way bootstrap resamples (seed 0). Each
resample draws providers with replacement and, independently, origins in moving blocks of
three consecutive origins, then recomputes cov90_h with row weights.

**Verdicts:**
- **Within tolerance** if at every horizon the interval lies inside [0.85, 0.95].
- **Outside tolerance** if at any horizon the interval lies wholly outside the band. Each such
  horizon is named as over- or under-covering.
- **Inconclusive** otherwise.

**Reported alongside, but not decisive:**
- the point estimates;
- the within-period (provider-only) intervals;
- per-target and 50% coverage;
- the 0.87–0.93 criterion per origin-year × horizon cell (2024; 2025), marked met or not met;
- the DEV minimum and maximum over origin-years at each horizon.

**The expected outcome, stated in advance.** On two CONF-sized DEV windows (origins 2018-04 to
2019-12 and 2021-07 to 2023-03), the two-way half-widths are 1.6–3.7 pp. Those intervals cross
a band edge (0.953 at h = 3 in one window, 0.845 at h = 1 in the other), so the rule would say
**inconclusive** on both [verified 2026-09-11 by re-running the statistics review's DEV-only
script; origins resampled independently there, so moving blocks would be wider still]. An
inconclusive primary is what 19 origins can honestly support, and the write-up will say so
rather than lean on point estimates.

**Why this is the primary.**
- It tests the project's recommended remedy, the calibration selected at STOP 4. Under
  D5 = (b) that is not the forecast that goes out on 31 October: the live forecast is
  uncalibrated raw ETS. Raw ETS's own CONF coverage appears in the descriptive headline below,
  and in its own table at ICB level, where the live forecast is issued (design §7.6).
- The I1 framing's claim that standard forecasts are overconfident is measured by the
  descriptive headline below, not by the primary.
- The registered H2 M1 clause, on default M1, is reported unchanged as a secondary.

**Key secondary:** H1.

**Descriptive headline, same slice:** "how overconfident are standard forecasts?" This is the
90% coverage of the *uncalibrated* B1, B2 and M1 raw intervals on CONF, against their
pooled-conformal versions, reported as coverage gaps in percentage points. The uncalibrated
intervals are re-tests.

## 5. Reporting protocol

- **Every comparison** states:
  - its point estimate and 95% interval;
  - the resampling unit;
  - the slice: split, winter or all months, horizon(s), level, mode and origins.

  No table mixes slices. Coverage is always shown by horizon and by origin-year.
- **DEV alongside CONF.** Every CONF statistic is computed on DEV by the same runner with the
  same code path. DEV statistics are scored with `unseal_token=None`, and DEV-origin forecasts
  for sealed targets enter CONF pools only and are never scored. The DEV figures include G1 and
  all 69 M2 origins. Earlier DEV reports stand as they are.
- **Comparing CONF with DEV.**
  - A CONF statistic is flagged **outside DEV's range** if it lies outside the minimum–maximum
    of the same statistic across DEV's winter seasons (winter-h3 statistics) or assessable
    origin-years (coverage).
  - The Stage A differences measure LightGBM seed noise on fixed data. They are quoted only
    when comparing two LightGBM runs on one slice, and are not a yardstick for DEV–CONF gaps,
    for M2, for ICB level, or for coverage beyond winter h = 3.
  - A CONF result materially worse than DEV is a finding, not a failure (brief H2).
- **Truth snapshot.** The run rebuilds the vintage table from the tagged `data/raw` (P4) and
  scores against the latest revision it contains. Later revisions do not trigger re-scoring.
- **Artefacts** go in `results/H-confirmatory/`:
  - `README.md` with the tag commit, run date, environment and data hashes;
  - `confirmatory_results.md`;
  - CSVs for every table;
  - failed-fit and failed-forecast counts;
  - the unseal-log entry reproduced.
- **No re-runs** (brief H3).

## 6. Run protocol (from Ellie's written go-ahead and the tag)

1. **Go-ahead (STOP 9).** This plan is committed as final, and `preflight` passes on that
   commit. Ellie reviews it with design v2.2's [default] choices and P12's exception; on her
   written go-ahead in the conversation, that commit is tagged and pushed (P9). `preflight` runs
   again just before `run`. `run` is not started before the go-ahead.
2. **Pre-run checks.** The runner refuses to start unless, in the order of design §3.2:
   - the output directories (P5) do not exist;
   - the tag is annotated, and the remote holds the same tag object (P9);
   - the token file (`--unseal-token-file`) holds the tag commit; the token is then discarded,
     and is never in argv, the environment or a worker's arguments;
   - HEAD is the tag commit or, under `--amendment TITLE`, a descendant whose §10 holds exactly
     one new row titled TITLE;
   - `data/raw`, `data/reference`, the pins and the lock are unchanged since the tag, and the
     pins and the lock are read from the tag;
   - the tree is clean, untracked files included, and `nhs_ae` imports from this worktree;
   - `pip freeze` matches the tag's lock and its editable line names HEAD, and Python and the
     platform match the pins (P6); drift in the last two is accepted only under `--amendment`,
     with the new values quoted and a reproduction reported;
   - the `data/raw` manifest hash, every stored file and the `data/reference` files match their
     pins (P4);
   - every other worktree's unseal log is absent or empty, this worktree's log equals HEAD's
     committed copy, and every witness line is in that copy (P0, P8); without `--amendment`,
     this worktree's log and the witness are empty; with it, the log may hold only earlier lines
     that the amendment row discloses by timestamp (design §3.2.10);
   - the 21 inputs match their pins, and the generation code is unchanged between the
     `prepare --dev-side` commit and the tag (P5, §7.1); a crash-fix commit after the tag is not
     covered by this check;
   - the quarantined forecast file matches its pin, git ignores it, and nothing under the
     quarantine is tracked (P13);
   - the vintage table rebuilt from the tagged `data/raw` matches its pins, and the three D7
     as-of slices hash equal to each other and to their pins (P4, D7).

   The load average is recorded, with a warning above 2; it never refuses.
3. **Generate every CONF forecast; no guarded call yet.** This covers:
   - B0, B1, B2, default M1 and M1 v3 raw at provider level;
   - B1, B2 and M1 v3 raw at ICB, region and England level;
   - final-mode forecasts of the five provider models at all 21 origins (H4 uses the five
     winter-h3 origins; all 21 complete the P13 check);
   - the 21 `m2d_corr` fits with the frozen settings (M2f-r4 is not generated: D1 = exclude).

   **Hashes and limits.** Before step 4 the runner commits the forecast hashes, the M2 fit table,
   the timings and the QA counts (`results/H-confirmatory/{forecast_hashes,m2_fits,timings,qa_counts}.csv`)
   as the hash commit H1, the start commit's single child, which adds only those files; the
   unseal log's `head` will be H1 (design §4). Checks between steps 3 and 5 are limited to
   counts, NaNs, quantile order and hashes. No CONF forecast is plotted or set against an outturn.

   **Reproducibility and D7 checks.** Regenerated B0–B2 and default-M1 forecasts are compared,
   on forecast values only, with the quarantined pre-seal forecasts (P13); B1 is expected to
   differ, since it is now seeded (`9a17011`). Forecasts at 2025-08 and 2025-09 are compared with
   2025-07's (D7). Both are reported, not stops (design §4).

   **Fit failures.**
   - The seeds are as in Stage E: the fit seed is year × 100 + month and the predictive-draw
     seed is the month.
   - An M2 exception gets one retry with both seeds + 1,000. If it fails again, that origin is
     recorded as failed and its forecasts are missing. An exception in a harness model, a broken
     process pool or an interrupt is a crash, not a fit failure (crash policy).
   - If 4 or more of the 19 counted origin units fail (more than 20%), H2's M2 clause is
     reported as **not evaluable**, with the 21-fit count alongside. A failed 2025-07 fit is not
     replaced by 2025-08 or 2025-09.
   - Sampling below the R-hat/ESS targets is reported and excludes nothing. On DEV, **0/69
     `m2d_corr` fits are on target** (R-hat < 1.01, bulk ESS > 400, no divergences), and the
     diagnostics worsen with origin date (`results/E-m2-rerun69/`, `0eeac08`):

     | Origin year | Median max R-hat | Median min bulk ESS |
     |---|---|---|
     | 2018 | 1.015 | 199 |
     | 2019 | 1.015 | 229 |
     | 2020 | 1.026 | 167 |
     | 2021 | 1.047 | 84 |
     | 2022 | 1.052 | 79 |
     | 2023 | 1.069 | 63 |

     By origin, Spearman's correlation with the date is 0.77 for R-hat and −0.82 for ESS. A
     seed-stability check at the three worst late origins found the scored quantiles stable
     (§3, H2's M2 clause; `5271eb2`).

   **Machine.** Nothing else heavy runs: contention multiplied fit times by about 30 on DEV.
4. **Unseal, calibrate, reconcile.** Everything in this step runs in **one parent process**.
   - The token is read from its file again, after every process pool has closed.
   - The first guarded call is an explicit `assert_not_sealed` on the 21 CONF origins with the
     token, at HEAD = H1 (P11), so the run's log entry records them. The new line is copied to
     the witness and checked at once; from then on, starting a process raises.
   - Then come the CONF first-release tables from the rebuilt vintage table, G1, pooled
     conformal at every level, MinT reconciliation and H4b's windows, each bounded by the end
     origin 2025-09.
   - No guarded call runs in a worker process.
5. **Score once**, in the same process: DEV frames with no token, then CONF frames with it.
   Every step-4 and step-5 output is written and hashed before any statistic is computed;
   writing the scores' `SHA256SUMS` is the crash policy's "score written" boundary. The runner
   asserts exactly one new line in this worktree's log, and none in any other, before it exits.
6. **Record.** The runner commits `results/H-confirmatory/`, which reproduces the unseal entry,
   with `results/unseal_log.jsonl`, as H1's only child. It prints the Stage H summary (every
   verdict, the primary comparison, and the DEV and CONF tables side by side), then the
   `git tag -a conf-run-v1` and `git push` commands. Tagging and pushing are done by hand, once
   the summary has been read; the tag must be annotated, or the post-run state does not hold
   (P11).

**Crash policy** (design §9). The case is read from disk. Every crash-fix commit goes on top of
the runner's last commit (H1 or later; the start commit if the runner made none), on the tag's
line of descent and never on `main`; the tag never moves.
- *Case 1, no unseal line:*
  - make a crash-fix commit, holding any code fix, which also removes `results/H-confirmatory/`
    if H1 added it and adds an amendment row;
  - move the step-3 outputs aside to `data/processed/stage_h/discarded/<timestamp>/`;
  - rerun with `--amendment TITLE`.
- *Case 2, an unseal line but no scores written* (neither the `scores-written` record nor the
  scores' `SHA256SUMS`): the same, and the crash-fix commit also commits
  `results/unseal_log.jsonl`, whose line the amendment row quotes by timestamp. The rerun's line
  is the second log entry.
- *Case 3, the scores written:* no change may alter a written number.
  - First commit the log and `results/H-confirmatory/` as the crashed run left them, with any
    code fix.
  - `report --from-scores` then rebuilds every table from the hashed step-4 and step-5 files,
    with no guarded call, into `results/H-confirmatory/recomputed-<HEAD>/`, and compares each
    with the original byte for byte. That result is committed, and its commit is tagged
    `conf-run-v1` by hand.
  - If a fix changes any step-4 or step-5 hash or any number, both runs are reported, the
    corrected one labelled "corrected after unsealing", and "no re-runs" is reported as not met.

## 7. Pre-flight checklist (all before the tag)

| # | Item | Why | Effort |
|---|---|---|---|
| P0 | **One branch, one worktree.** Merge `merge-check` and `m2f-redesign` into one branch, keeping all six rows the two branches added after the freeze row. The three M2f rows are merged even if D1 = exclude. Remove the stale worktrees (`m2f-dev` and the two agent worktrees), or make step 2 check every worktree's log. Cite amendment rows by date and title, since line numbers shift. **Status (2026-09-15): done.** The branches were merged at `c5cdefa` (2026-09-11). The stale worktrees were kept, so step 2 (check 10) and the post-run state read every worktree's log and the witness; on 2026-09-15 there are six worktrees, four with an empty log and two agent worktrees with none | The seal checks the tag's commit; the logs are per checkout | ~½ day |
| P0b | **Reproduction check on the merged code.** `m2d_corr` at DEV origins 2019-10 and 2023-12 reproduces the cached `m2-frozen-v1` forecasts with the same seeds; M2f-r4 reproduces b77430e (needed only if D1 = include; D1 = exclude); B1, B2, M1 v3 raw and default M1 reproduce at one origin. On `m2f-redesign`, `m2.py` changed inside `build_model` and `predictive_draws`, which are on `m2d_corr`'s path. **Status (2026-09-11):** `m2d_corr` reproduces `m2-frozen-v1` bit for bit at all 35 even-month origins (`0eeac08`). M2f-r4 reproduces `b77430e` at 2023-04 and 2023-08 (`5271eb2`). The baseline half (B1, B2, M1 v3 raw and default M1) is an environment check only, because no file on their code path has changed since `16d47dd`; it was deferred to P6 and passed there on 2026-09-13 (`results/P0b-baselines/`), so P0b is done | Confirms that the tagged code is the frozen specification | ~½ day plus minutes of compute |
| P1 | **Frozen M2 on the 34 odd-month DEV origins**, on the merged commit. First make `run_rung` raise if the cached origins differ from the requested ones: today it returns the 35-origin cache whatever is asked, so P1 as first written would add nothing. **Status: done** (`0eeac08`). The reproduction is exact, and the sampling is 0/34 on target, as it was 0/35; the new fits are no worse under the stop rule fixed before running. The sampling checks sit here under P1, including the seed-stability check (`5271eb2`, §3). P2 is G1 | Required by the freeze and E0 amendments; M2 then has DEV figures on all 69 origins | About 1 hour serially on an idle machine. The fits are identical to M2d's (98 s each); the 49 min recorded for `m2d_corr` was contention [verified] |
| P2 | **G1**: implement it, add a unit test, register the amendment. Re-run on DEV with G1 (exploratory): Stage F, and the STOP 4 table. The STOP 4 selection stands whatever the re-run shows. **Status: done.** Registered before any code (`8caf9d5`), implemented with five unit tests (`fd0182a`), re-run at `7ac8f3d` (`results/D-calibration-G1/`, `results/F-reconciliation-G1/`; two runs byte-identical; outcome row "P2 re-run with G1"). The registered STOP 4 rule still selects M1 + pooled, and every H3 verdict is unchanged. G1 removes most of the ETS blow-up (England forecasts with a 97.5% quantile above ten times the median: 113 → 27). It leaves a residual from ETS forecasts with a zero median but positive upper quantiles, which the registered definition does not catch; on DEV that touches four ETS winter-h3 cells at England | Confirms G1 removes the ETS blow-up; discloses any effect on the Stage D contest | ~½ day; minutes of compute |
| P3 | **Stage H runner** (the package `src/nhs_ae/evaluate/stage_h/`, in place of the planned `evaluate/stage_h.py`), one entry point for steps 2–6, plus its tests. It includes:<ul><li>an `h1_table` whose unit test uses synthetic data with the tested MASE at 0.8 × the reference: it must give rel = −0.20 and "confirmed", and `n_pairs` must equal the row count when targets are pooled;</li><li>the two-way coverage bootstrap and the leave-one-origin-out functions, with tests;</li><li>tests that the pool's origin set advances at each CONF-like origin, and that the first-release table used at origin t holds every period published by t.</li></ul>A dry run on DEV origins 2023-07 to 2023-12 *without* the token must see the seal drop their 2024 targets. `stage_f.score` keeps only DEV origins and scores without a token, so the runner takes its own paths. **Status (2026-09-15): done.** Built on 2026-09-14; the DEV dry run and the tokened rehearsal pass. The runner is `src/nhs_ae/evaluate/stage_h/` (`python -m nhs_ae.evaluate.stage_h {pin, prepare, preflight, dry-run, run, report}`), specified in `docs/stage_h_design.md` (v2.1; v2.2 adds P11) after two design reviews, and fixed after two adversarial code reviews; its choices are the two §10 rows "Stage H implementation details (P3)", each open choice marked [default] in the design for STOP 9. The dry run at `dc0904a` (`results/H-dryrun/dc0904a815dc/`) wrote no log or witness line in any worktree; the seal dropped exactly the 15 embargoed origin × horizon pairs and no 2024 period was scored; the forecasts, calibrations and reconciliations reproduce the DEV caches (`reproduction.md`; B1 differs only where it is now seeded); `report --from-scores` rebuilt all 144 tables and the verdicts byte for byte. It exited with status 1, by design, because four DEV-side statistics (H1 and H4 seasons, H4-original, H2 M1 DEV coverage) need design §8's inputs, which `prepare --dev-side` generates (agreed 2026-09-14). The rehearsal, in a temporary repository with a real annotated tag, runs steps 2–6 with the token and the three crash cases. 626 tests pass. **Final dry run (2026-09-15, `d8ff305`, `results/H-dryrun/d8ff305dbbd7/`):** after `prepare --dev-side` and `pin`, on the pinned inputs (check 11: all 21 verified), it exits with status 0: every statistic computed, DEV side included; no log or witness line anywhere; the 15 embargoed pairs dropped and no 2024 period scored; `report --from-scores` rebuilt all 148 tables and the verdicts byte for byte; `reproduction.md` is identical to the `dc0904a` run's, and 138 of the 144 tables both runs share are byte-identical (the other six: DEV ranges now present, and M2 fit times) | The existing code silently reuses DEV caches, and the H1 code behind `backtest-v1` was never committed | ~2 days |
| P4 | **Data pinned.**<ol><li>Ingest the 2026-09-10 release with an explicit `--snapshot` date; without one, `available_from` becomes the run date.</li><li>Commit `data/raw` before the tag, recording the manifest SHA-256 and a row-content hash.</li><li>The run rebuilds the vintage table from the tagged raw data into its own directory: the shared parquet is gitignored and rewritten by whichever worktree runs the build.</li></ol>**Status (2026-09-15): done.** The 2026-09-10 release was ingested with `--snapshot 2026-09-10` (`e004a21`); `data/raw` is committed, and `pin` recorded its manifest SHA-256 and row hash (§7.1). Check 14 rebuilds the table into `data/processed/stage_h/<tag-commit>/vintages/`, and check 5 refuses any change to `data/raw` after the tag. | Fixes the outturns before the tag | ~2 hours |
| P5 | **No cache reads.**<ul><li>The runner writes only under `data/processed/stage_h/<tag-commit>/` and `results/H-confirmatory/`, besides the unseal log, the witness and its own commits (design §2.8), and refuses to start if either exists.</li><li>It builds every first-release table, calibration and reconciliation inside the run.</li><li>Besides the tagged `data/raw` and `data/reference` (P4), the pins and the lock read from the tag, the quarantined forecast file for step 3's check (P13) and the committed DEV G1 counts that step 4 checks against (`results/F-reconciliation-G1/failed_counts.csv`, design §5.4), the only permitted inputs are the DEV forecasts that feed CONF pools (origins 2017-07 to 2023-12, every level and model). Their SHA-256s are recorded in this plan, and they are copied read-only to `data/processed/stage_h/inputs/` before the tag. **Widened by Ellie's decision of 2026-09-14 (design §8; §10 row "P5 widened"):** the permitted set is 21 files: these 12 pool files, the 69 DEV `m2d_corr` fits from P1, and 8 DEV-side files (B0 and default M1 as-of at the 69 DEV origins; final-mode B0, B1, B2, default M1 and M1 v3 raw, and seeded as-of B1, at the 23 DEV winter-h3 origins), generated before the tag by `prepare --dev-side` with the run's step-3 code and pinned.</li></ul>This matters because the existing first-release caches stop at period 2023-11. If the run used them, every CONF origin would be calibrated with the pool frozen in late 2023, silently. **Status (2026-09-15): pinned.** `prepare --dev-side` at `026c420` made the 21 inputs; `pin` recorded their SHA-256s, listed in §7.1 | Blocker in the seal review | built into P3 |
| P6 | **One environment.**<ul><li>Install with `pip install -e '.[dev,xls,models,plots]'`, plus nutpie, which no extra lists: add it to `models`.</li><li>Commit `pip freeze` before the tag.</li><li>Tests pass and lint is clean.</li><li>The baseline half of P0b runs here: B1, B2, M1 v3 raw and default M1 must reproduce at one origin in this environment.</li></ul>**Status (2026-09-12): done locally.** `.venv-m2` now has `.[dev,xls,models,plots]`, adding only xlrd, openpyxl and et_xmlfile; nothing else changed. It is pinned in `requirements-lock.txt`. All 241 tests pass. It parses the archive identically to the shared vintage table, and a fresh environment built from the lock reproduces `forecasts/2026-09` bit for bit. CI still installs unpinned, as a cross-check. **Baseline half of P0b: done (2026-09-13, `results/P0b-baselines/`).** At origin 2019-10, B2, M1 v3 raw and default M1 reproduce their committed forecasts exactly, on 39,690 rows each. B1 reproduces across runs; its gap from its unseeded pre-`9a17011` file (median 0.25%) is simulation noise | Reproducibility; one environment runs everything | ~2 hours |
| P7 | **Amendment rows** (by date and title) for:<ul><li>G1 and the STOP 4 re-run;</li><li>D1–D7 as decided, and the primary rule;</li><li>H1's overall rule and qualifiers;</li><li>H2's M1-clause "neither" outcome;</li><li>H2's M2 clause as a phase-1b test at ICB level, and ICB-level H3, each explicitly overriding the freeze-time deferral;</li><li>H4's model list and common-row ranking, and H4-original's metric;</li><li>H4b's "lost originals" split and *seen* label;</li><li>H5 as never testable;</li><li>F2 on CONF;</li><li>D7's treatment of the duplicate origins, which modifies Appendix A's keep rule;</li><li>the status of origins 2025-10 to 2026-09 (P12);</li><li>the post-run seal state (P11);</li><li>the quarantine (P13).</li></ul> **Status (2026-09-15): done.** Added on 2026-09-15: H1's rules and qualifiers; H2's M1-clause "neither"; the phase-1b override for H2's M2 clause and ICB-level H3; H4 and H4-original; H4b's lost-originals split and *seen* label; H5; F2 on CONF; P12; P13; and, from §9, "The DEV calibration target is not met, and Stage H proceeds". Already recorded: G1 and the P2 re-run, D1–D7 (the primary rule in D2), D7's keep rule, and P11's post-run state. Drafted from the plan's text, each with its sources, and checked sentence by sentence by an independent reviewer; its corrections are applied | Brief section 0.3: decisions are recorded when they are made | ~2 hours |
| P8 | Every worktree's `results/unseal_log.jsonl` is empty (0 bytes in all four on 2026-09-11). **Status (2026-09-15): holds.** Six worktrees: four logs of 0 bytes, two agent worktrees with none, and no witness file; step 2 checks again | Definition of Done | — |
| P9 | This file finalised and committed; then `git tag -a conf-plan-v1 -m "..."`, an annotated tag, which carries its own timestamp. Push it to the private remote before `run`, since step 2 refuses unless the remote holds the same tag object (design §3.2, check 2); that is Ellie's action, or needs her approval. **Status: open.** It closes with the tag, on Ellie's written go-ahead at STOP 9 | "The tag timestamp is the evidence" (brief H1) | minutes |
| P10 | **Correct Appendix A** by amendment. The coverage check dated origins to the 1st of the month; the loader uses the second Thursday. The corrected list:<ul><li>DEV: 2018-11 and 2021-10, not 2018-12 and 2021-11 [verified from `stage_d/forecasts_b1.parquet`];</li><li>2017-07 was covered, since period 2017-04 was available on its as-of date, 2017-07-13;</li><li>CONF: 2025-08 and 2025-09, which duplicate 2025-07 (§1).</li></ul>The loader was always right; only the record is wrong. **Status (2026-09-15): done.** §10 row "Appendix A corrected (P10)". The DEV list was re-checked with `asof.load_asof` at all 78 DEV-side origins (periods to 2023-11, presence only): exactly 2018-11 and 2021-10 are truncated. The CONF entries are the plan's (§1, D7). `nhs-ae-ingest coverage`, which produced the wrong list, now dates origins to their second Thursday, and the loader's docstring names all four truncated origins, including that final mode keeps the missing month there | The registered record must match the code | ~1 hour |
| P11 | **Seal hardening.**<ul><li>Guard the rows that yield a score, each guard taking `unseal_token=`: in `_calibrate_target`, `assert_not_sealed(wide.loc[wide["y_first"].notna(), ["origin", "period"]], token)` on every forecast row that carries a first release, before the `valid` filter, because the CQR scores are computed before it; the same on `_median_errors`' merged rows (origin and period). `first_release` raises if its output holds a sealed period and no token is given. Stage H's pools pass their token to each.</li><li>Delete `summary --include-sealed`; `summary` always drops sealed rows, and the pre-seal figures are in committed CSVs.</li><li>`run --split conf`, or `--origins` reaching a sealed origin, refuses before reading anything, whatever the seal's state, and `run --unseal-token` is deleted. Stage H runs only through `python -m nhs_ae.evaluate.stage_h`.</li><li>The token check also requires, on the first tokened call of a process: HEAD is the hash commit H1, the start commit S's single child made by the runner, whose diff from S only adds `results/H-confirmatory/{forecast_hashes,m2_fits,timings,qa_counts}.csv` (design §4). S is the tag, or a descendant whose preregistration carries exactly one new §10 row named by `--amendment`. HEAD = S itself is refused. The process is `python -m nhs_ae.evaluate.stage_h run` (its argv); the tree is clean outside `results/` and `data/`; `nhs_ae` imports from this worktree's `src/` (check 7). Later tokened calls of the process need HEAD unchanged and reuse the amendment (design §2.10).</li><li>**Post-run state:** once an annotated `conf-run-v1` tags a descendant of the tag that holds the completed run's record, whose committed log ends with that run's entry, and every other line of every worktree's log and of the witness is disclosed by timestamp in a §10 row added after the tag (design §9), `assert_not_sealed` returns without the token and without logging, so later live calibrations add no entries. Any git error keeps the seal.</li></ul>Each part gets a unit test. The post-run path is written and tested before `conf-plan-v1`. **Status: done** (built 2026-09-14; committed 2026-09-15 as `87ee1c5`, with review fixes in `339d527`), with Ellie's permission to edit `splits.py` (given 2026-09-14): `evaluate/seal_rules.py` (new), `splits.py`, the guards in `online` and `stage_f`, and `cli`, specified in `docs/stage_h_design.md` v2.2 (§1, §2.10, §4, §9) after two adversarial reviews of the specification. Every part has unit tests on temporary git repositories. The rehearsal takes the amendment path end to end, and reaches the post-run state on a real run's step-6 commit and on a case-3 recomputation's commit. 724 tests pass. `prepare --dev-side`, `pin` and the final dry run followed on 2026-09-15 (P3, P5); then the tag | No sealed-period error can be computed before the tag, and the single entry survives the live forecast | ~1 day |
| P12 | **Origins 2025-10 to 2026-09 and live work.**<ul><li>These origins are in no split: they become live-pipeline history, never used for confirmatory claims.</li><li>Until the Stage H entry exists, no forecast for a 2024-01 to 2026-02 target is compared with an outturn in any form.</li><li>Live dry runs use raw intervals or pre-2024 pools.</li><li>*Generating* (not scoring) forecasts for these origins before Stage H is allowed.</li><li>The live model (raw ETS: D1 = exclude, D5 = (b)) is fixed at the tag; any later change is recorded as CONF-informed.</li></ul> **Status (2026-09-15): recorded** as the §10 row "Origins 2025-10 to 2026-09, and live work before the run (P12)", which also states design §2.1's exception for residuals the frozen models compute on their training data; Ellie confirmed it at STOP 9, closed to a list (§10 row "STOP 9 decisions") | These origins' targets up to 2026-02 are sealed. Under D5 = (b) the live forecast needs no pool; these rules keep the live work that remains from scoring sealed targets outside the logged unseal | amendment only |
| P13 | **Quarantine** the pre-seal score and forecast files: `data/processed/backtest*/`, which holds 526,847 sealed score rows in `backtest/scores.parquet` and 132,717 in `backtest_m1_v3/scores.parquet`, plus the tuned and v2 files. Move them to `data/processed/quarantine/pre-seal/` (ignored by git, unlike `data/quarantine/`, which would fail step 2's clean-tree check) with their SHA-256s recorded. Score files are never opened again; forecast files only for step 3's values-only check. **Status (2026-09-15): done.** All 12 files under `data/processed/backtest*/` (554,329,182 bytes) were renamed into `data/processed/quarantine/pre-seal/`, each hashed from its bytes before and after the move (identical) and made read-only; nothing was parsed. The hashes are in `results/P13-quarantine/manifest.csv` and the quarantine's `SHA256SUMS`. Check 12's rule finds the quarantine ignored and untracked | Removes the easiest unlogged look | ~1 hour |
| P14 | Check that the training-leakage decomposition fixes each origin's 12-month window at its as-of end month, including at the truncated origins. **Status (2026-09-15): done; no code change.** `hypotheses.h4b_components` ends each origin's window at E_o, the last month up to M−1 with a provider version on o's as-of date, which is the rule `asof.load_asof` uses to end the training data. So W_o runs from E_o − 11 to E_o, and the months after E_o up to M−1 form the lost-originals split. A new unit test (`test_h4b_window_is_the_loaders_last_12_months_at_the_truncated_origins`) uses synthetic vintage tables to check this against the loader's own as-of and final panels at the truncated DEV origins 2018-11 and 2021-10 and the CONF-like 2025-08 and 2025-09, with their neighbours. On the real vintage table, read only to period 2021-10, the loader and H4b both end at 2018-09 at origins 2018-10 and 2018-11, and at 2021-08 at origins 2021-09 and 2021-10. The first surviving versions of 2018-10 and 2021-09 are revisions dated 2018-12-13 and 2021-11-11, so 2018-12 and 2021-11 are not truncated. H4b is computable as registered. The older `audit.training_leakage`, which produced the *seen* table, anchors its window at M−1, and Stage H does not use it. | H4b is computable as registered | ~1 hour |

### 7.1 P5's pinned inputs (`pin`, 2026-09-15)

Written by `python -m nhs_ae.evaluate.stage_h pin` at `026c4202c3a1` (the `prepare --dev-side` commit), committed as `docs/stage_h_pins.json`; step 2 reads the pins from the tag and check 11 compares every input with them. The runner's P4 rebuild matched the shared vintage table exactly (1,072,039 rows, row hash `db419ce45b6039a2…`; manifest SHA-256 `0adeded94ccf43506c8f01158f3477ed426147f36b6c695682ee3f1ddc7ee293`; 8 parse failures, as pinned). The three D7 as-of slices (2025-07, 2025-08, 2025-09) hash equal (`5418189190e64955…`), so the premise of 19 information sets holds. The quarantined pre-seal forecast file (P13) is `data/processed/quarantine/pre-seal/backtest/forecasts.parquet`, SHA-256 `6c369958a08ef4443de7a899b58bb107d599e8370ea1492f9089748d8e7f9614`.

| Input | Model | Level | Mode | Origins | Rows | SHA-256 |
|---|---|---|---|---|---|---|
| `dev_side/forecasts/b0_provider_asof.parquet` | b0_seasonal_naive | provider | asof | 2018-04..2023-12 (69) | 2,581,146 | `65fddc98036f74d0b018bd08686474a26d60dd22ba46d36b267b046d4cf4d86b` |
| `dev_side/forecasts/b0_provider_final.parquet` | b0_seasonal_naive | provider | final | 2018-10..2023-12 (23) | 854,064 | `8a48c945b8513baa71004fecb3943dfbb1b72ac4d50bb8b09747881170d76968` |
| `dev_side/forecasts/b1_provider_asof.parquet` | b1_ets | provider | asof | 2018-10..2023-12 (23) | 853,416 | `ef6708a7c0f34688bf98a9c326ec3964024a7f601970ec55261424462a3e1348` |
| `dev_side/forecasts/b1_provider_final.parquet` | b1_ets | provider | final | 2018-10..2023-12 (23) | 854,064 | `74a299bc081806e7d63d31576a57a43c6419d4b2ebcd39db3c9325648d00ab82` |
| `dev_side/forecasts/b2_provider_final.parquet` | b2_stl_arima | provider | final | 2018-10..2023-12 (23) | 854,064 | `958d2d31e24f8382957df5747c8db681be7be1c13bdc39916cd46156fec18ceb` |
| `dev_side/forecasts/m1_provider_asof.parquet` | m1_lightgbm | provider | asof | 2018-04..2023-12 (69) | 2,581,146 | `cb8e23d7fe22888567c5442cfa2d6e8dcd46d2ba497f9ab879b6ab1a42e38c1d` |
| `dev_side/forecasts/m1_provider_final.parquet` | m1_lightgbm | provider | final | 2018-10..2023-12 (23) | 854,064 | `3aa55bab00805ddb7ac099df624a9d4c1c3988bda958657bc29ad4d6ad29be1e` |
| `dev_side/forecasts/m1_v3_raw_provider_final.parquet` | m1_lightgbm_v3_raw | provider | final | 2018-10..2023-12 (23) | 854,064 | `72cba012c249f892cfe99e0d5dbf4d31afc3a7f348a627ddba129ac95014e7fe` |
| `m2/forecasts_m2d_corr.parquet` | m2d_corr | england, icb, region | asof | 2018-04..2023-12 (69) | 491,832 | `58b43b3dcdfab40e18860fa2ffb6898130265c89247e7def0d91071999a35356` |
| `pool/base_b1_england.parquet` | b1_ets | england | asof | 2017-07..2023-12 (78) | 12,636 | `637057c8152cc5d66645cc857dcb976619ce8a100b5c29af01a838206ce4e1bb` |
| `pool/base_b1_icb.parquet` | b1_ets | icb | asof | 2017-07..2023-12 (78) | 464,130 | `96ee765796e02cda12beaf77ad63108d8ca47fddb54c16119d74f8bba38ce950` |
| `pool/base_b1_provider.parquet` | b1_ets | provider | asof | 2017-07..2023-12 (78) | 2,960,388 | `852e1017eee2053007acea8a235a95cfa5b07fd63f413a997f274bb31b4d8633` |
| `pool/base_b1_region.parquet` | b1_ets | region | asof | 2017-07..2023-12 (78) | 88,452 | `3aa2f828186b539759098ba266e571feada039a25ce04e0bd4a6f35f267848b8` |
| `pool/base_b2_england.parquet` | b2_stl_arima | england | asof | 2017-07..2023-12 (78) | 12,636 | `9e68ed296a417353c2cc8b67ce1c491e3b83e0b31fc50e54d8f7979104f31a17` |
| `pool/base_b2_icb.parquet` | b2_stl_arima | icb | asof | 2017-07..2023-12 (78) | 464,130 | `33ebdd3d8e84dd8c5a53c3a54fe7e26c2866286b86e7ba402dc3d34e9303fad0` |
| `pool/base_b2_provider.parquet` | b2_stl_arima | provider | asof | 2017-07..2023-12 (78) | 2,960,388 | `1de3a60010a1421cd3de18841609fbefe4f62f4344af951b02cef311e8c123a0` |
| `pool/base_b2_region.parquet` | b2_stl_arima | region | asof | 2017-07..2023-12 (78) | 88,452 | `40929ffc271b3b8612605f34b805254046b009c1296a9ee9a731d10da887dffa` |
| `pool/base_m1_v3_raw_england.parquet` | m1_lightgbm_v3_raw | england | asof | 2017-07..2023-12 (78) | 12,636 | `a1f0806f0bd9ac0f812ff801e74ab8eb1f9a96f397aaea1efc05c615c97b42a9` |
| `pool/base_m1_v3_raw_icb.parquet` | m1_lightgbm_v3_raw | icb | asof | 2017-07..2023-12 (78) | 464,130 | `21766f4984c7f2ace494506d412c538e9ab6cbabf03cf792f77fef1e89ae3222` |
| `pool/base_m1_v3_raw_provider.parquet` | m1_lightgbm_v3_raw | provider | asof | 2017-07..2023-12 (78) | 2,960,388 | `02e305b46c66ff191c28926f6fd8c3b85f76ba7688476488a66df530249cc62c` |
| `pool/base_m1_v3_raw_region.parquet` | m1_lightgbm_v3_raw | region | asof | 2017-07..2023-12 (78) | 88,452 | `2e617fc963547a2c24d83a854a3b896c79d34407cc1d84cb565cfe582079a13c` |

## 8. Decisions for Ellie

All seven were decided on 2026-09-12 and 2026-09-13, each recorded by a §10 row. The STOP 9
go-ahead is given on this plan together with design v2.2's [default] choices and P12's
training-residual exception. Overruling one needs an amendment row, and any code change it
implies, before the tag; any code change also means the dry run again at the new code, and a
change to check 11's paths means `prepare --dev-side` and `pin` before it (design §1, "Order
before the tag").

| # | Decision | Options | Recommendation |
|---|---|---|---|
| **D1** | Does M2f-r4 go to CONF? | **(a)** Freeze it now (annotated tag `m2f-r4-frozen` at b77430e) and include it in F2 on CONF as a pre-specified secondary contender. **(b)** Keep it off CONF; its first genuine test is then PROSPECTIVE, which needs a shadow live forecast | **(a).** It costs about 1 hour of compute (mean 142 s per fit) and is the only contender that answers F2 on unseen data. CONF is then burned for it and any refinement. **Caveat: M2f-r4 samples below target throughout its 35 DEV fits.** Its median max R-hat is 1.079 and its median min bulk ESS 47. Two fits are above R-hat 1.15 with ESS under 20 (2020-04 and 2022-02, both on `kappa_all`). `m2d_corr`'s better median comes from its early origins: at the even-month 2018–19 origins its median R-hat is 1.015, against M2f-r4's 1.082. At the six even-month 2023 origins the two are 1.076 and 1.065, with median ESS 48 and 45. So at post-2023 origins the two candidates are plausibly comparable. Both passed the seed-stability check at 2023-04, 2022-07 and 2023-08 (`5271eb2`). M2f-r4's retry fit at 2023-08 reached R-hat 1.257 with ESS 12, its worst fit on record. **Decided 2026-09-12: exclude**, by the pre-committed condition (amendment "D1 = exclude"; `results/E-m2f-69/`). M2f-r4 is not on CONF, and the live model is raw ETS; M2f-r4 runs as an unpublished live shadow |
| **D2** | The rule for the primary comparison (§4) | **(a)** The two-way-interval rule with three outcomes (within / outside / inconclusive). **(b)** Cheaper: point estimates in 0.85–0.95 at every horizon, labelled *fragile* whenever the two-way interval crosses a band edge | **(a).** DEV shows that point estimates from 19 origins move by up to 5.7 pp between windows at the same horizon. (b) keeps about 90% of the value and gives a crisper, more fragile verdict **Decided 2026-09-13: (a)** (amendment "D2 = (a)"). |
| **D3** | The H3 headline | **(a)** M1's verdict. **(b)** Holds if any base holds. **(c)** Holds only if all three hold | **(a), for a new reason (revisited 2026-09-13).** The original reason, that (c) ties the headline to baselines no one would deploy, has lapsed: under D5 = (b) raw ETS is deployed. The case for (a) is now consistency. H3's headline would test reconciliation on the project's recommended calibrated forecast, M1 v3 raw + pooled + G1, the same forecast the primary tests (D2). No H3 arm is the deployed forecast: raw ETS would have to be calibrated before it could be reconciled (work order §0.5), and STOP 7 keeps MinT off the live path. ETS's and STL+ARIMA's verdicts are reported alongside. A new option, **(d) ETS's verdict**, would speak to the deployed model's family, but its DEV arm measures the calibration blow-up and depends on G1 working (P2). (b) still inflates false positives **Decided 2026-09-13: (a)** (amendment "D3 = (a)"). |
| **D4** | Guard scope | **(a)** G1 as in §2.2, with failed forecasts scored as issued. **(b)** G1 plus a cap on adjustments or a minimum aggregate pool | **(a).** It repairs the observed failure without inventing a new calibration method after seeing DEV results **Decided 2026-09-13: (a)** (amendment "D4 = (a)"). G1 was registered (`8caf9d5`) and implemented (`fd0182a`) under P2. The DEV re-run left a residual ETS blow-up from zero-median forecasts, which (a) by design does not treat (row "P2 re-run with G1"). **Ellie confirmed on 2026-09-13 that G1 stays as registered.** |
| **D5** | **The live model and the order of work** (the binding constraint) | **(a)** A calibrated live forecast (M1 + pooled + G1, the STOP 4 selection): **Stage H runs first**. **(b)** An uncalibrated live forecast: Stage H can come later, but the live intervals are the overconfident ones the project measures. **(c)** Calibrate the live forecast on pre-2024 pools only (stale by nearly three years) | **(a).** Only (a) is consistent with both the seal and the project's claim. P0–P14 are about 7–8 working days of agent work plus about 1 hour of M2 compute, so aim to tag by **2026-09-30**, run by **2026-10-02**, and build the live forecast from the **2026-10-08** release. If the tag slips past about 2026-10-12, the live forecast falls back to (c), labelled as such. Recording the live model also closes STOP 4; STOP 7 and 8 remain to be recorded **Decided 2026-09-12: (b).** D1 = exclude made raw ETS the live model, so the live forecast is uncalibrated and Stage H no longer gates it (amendment "D5 = (b)"). The dates above now apply to Stage H alone, and (c) is moot. STOP 7 and STOP 8 were recorded on 2026-09-12 |
| **D6** | Which M1 carries H1, H2's M1 clause and H4 | **(a)** Default M1, as registered: the amendment "M1 v2" says the frozen H1/H2 tests refer to `m1`. M1 v3 raw and M1 + pooled are reported alongside, and the operational forecast is tested by the primary. **(b)** M1 v3, which needs an amendment explicitly superseding those clauses | **(a).** The pre-registration wins. v0.2's claim that it names only "M1" was wrong. (a) also keeps the `backtest-v1` → CONF gap for an unchanged specification visible, which is the optimism the brief asks to quantify **Decided 2026-09-13: (a)** (amendment "D6 = (a)"). Under D5 = (b) the primary tests the recommended calibrated forecast, not the operational one. |
| **D7** | Origins 2025-07, 2025-08 and 2025-09, one information set | **(a)** Pooled statistics count the 19 distinct information sets. 2025-08 and 2025-09 are generated, checked equal to 2025-07, and reported, but not pooled; in origin bootstraps the three form one block. The 21-origin version is reported alongside. This amends Appendix A's rule that truncated origins "remain in the evaluation". **(b)** Keep all 21, as Appendix A states, with the 19-set version reported alongside | **(a).** Counting one forecast three times puts it in 14% of H2's rows at each horizon and a third of the 2025 cells. Appendix A's rule did not anticipate an origin that exactly duplicates its predecessor. Deciding now, before unsealing, removes the forking path **Decided 2026-09-13: (a)** (amendment "D7 = (a)"). |

## 9. Deviations and conflicts to record before the tag

All are recorded: each has a §10 row in `docs/preregistration.md` (P7, done 2026-09-15).

- **G1** is new, and changes the STOP 4 method (§2.2).
- **The primary comparison and its rule** (D2) were not in the pre-registration. The work order
  requires a primary.
- **H1:** the overall "all three targets" rule matches `backtest-v1` practice but was never
  written down. "Partial support" is a qualifier of *not confirmed*.
- **H2, M1 clause:** the "neither" outcome fills a gap in the registered rule.
- **H2, M2 clause:** a phase-1b test (§5) at ICB level, where M2 was specified, fitted and
  frozen (the pre-registration's §9 fallback names that level, but its trigger was never
  tested), run in Stage H. It explicitly overrides the freeze-time amendment that deferred
  phase-1b work past 31 October.
- **H3 at ICB level:** the same override. The Stage F design amendment brought it back once the
  mapping was ingested, and the freeze-time deferral is revoked for it by a row.
- **H3's headline base** (D3) is new.
- **H4:** M1 + pooled and M2 are excluded, and the ranking uses common rows. H4-original's
  metric is fixed.
- **H4b:** the "lost originals" split is added, and the *seen* label applied.
- **H5** is not evaluable, and never testable on a sealed split after Stage H.
- **F2 on CONF** is added as a secondary, descriptive comparison; F2 was registered on DEV only.
- **D7** amends Appendix A's keep rule for duplicate information sets; P10 corrects Appendix A's
  list.
- **Origins 2025-10 to 2026-09** get a defined status, and the post-run seal state is defined
  (P11, P12).
- **Conflict: which M1 carries H1, H2 and H4.** The brief asks for the specifications frozen at
  STOP 4 and STOP 6; the pre-registration names `m1` for the frozen H1/H2 tests. The
  pre-registration wins (D6). The recommended calibrated forecast (M1 v3 raw + pooled + G1) is
  tested by the primary; the live forecast is raw ETS (D5 = (b)).
- **Conflict: "both clauses" of H2.** The M2 clause says "pooled across providers", but M2
  exists only at ICB level, so it is tested there. The pre-registration's §9 fallback names
  that level, but its trigger, provider-level M2 failing to sample, was never tested
  (row "Phase-1b tests brought into Stage H").
- **Conflict: sample-path reconciliation (R2).** The freeze amendment defers it to phase 1b; the
  pre-registration wins.
- **Conflict: the DEV calibration target.** The Definition of Done's "0.87–0.93 at every
  horizon and origin-year on DEV" was not met: M1 + pooled's worst assessable cell was 4.7 pp
  from nominal. This does not block Stage H, and it is reported.

## 10. After Stage H

- **The live forecast** is uncalibrated raw ETS (D1 = exclude, D5 = (b)), built for origin
  2026-10 from the 2026-10-08 release whether or not Stage H has run; no forecast error is
  computed from a sealed row (the ETS fit's own training residuals fall under P12's exception),
  and M2f-r4 runs beside it as an unpublished shadow. A calibrated live forecast would need
  pools from origins 2025-05 to 2026-09, scored only after Stage H (P12), and would be recorded
  as a CONF-informed change. After `conf-run-v1`, calibration runs without the token and without
  new log entries (P11).
- **PROSPECTIVE.** The live forecast is scored from February 2027 as a standing test.
- **Stage I write-up.** It reports CONF next to DEV, with fragility labels, and gives the "what
  did not work" section prominence.
- **After the run** nothing is adjusted and re-run.

## 11. Changes from v0.2

From the statistics review:
1. The primary is now a three-outcome rule based on two-way intervals (§4, D2), with its
   likely "inconclusive" outcome stated in advance.
2. The duplicate origins 2025-07 to 2025-09 are identified, and D7 fixes their treatment.
3. The bootstrap call is specified exactly: reference and tested named, sign convention, keys
   including target.
4. H1's rule is reworded with qualifiers, and its low power is quantified with DEV winter
   seasons.
5. Leave-one-origin-out ranges and fragility labels added.
6. Stage A's noise yardstick replaced by an "outside DEV's range" flag.
7. H2's M1 clause gains a "neither" outcome; band edges are inclusive and unrounded; each
   verdict names its direction.
8. H3's provider clause reading stated.
9. G1's scoring treatment set: failed forecasts are scored as issued.

From the seal and fidelity review:
1. Cache substitution closed (P5, and `run_rung` in P1).
2. D6 corrected: the pre-registration names `m1`.
3. The single unseal entry secured: one parent process, every worktree's log, the token tied
   to HEAD and to a clean tree, `--include-sealed` deleted, `run --split conf` refused.
4. The post-run seal state defined (`conf-run-v1`).
5. Crash policy tightened, with no looks between generation and scoring.
6. G1's effect on STOP 4 addressed (P2).
7. DEV figures scored without the token.
8. Pre-seal CONF scores quarantined (P13).
9. Guard placement made exact (P11).
10. Reproduction check on the merged code (P0b).
11. Data and environment pinned (P4, P6).
12. Rules for live work before the run (P12).
13. H4 and H4b fidelity fixed.
14. Stage G disclosure corrected: the 2026-09-10 fit fed nothing.
15. An annotated tag (P9).

Checked by Claude: the claims quoted above, from DEV rows and metadata only.

## 12. Changes from v0.3

From the work order of 2026-09-11 ("M2 seed stability, CONF sampling rule, and v0.4
housekeeping"):
1. **P1 done.** The frozen M2 was re-run on all 69 DEV origins (`0eeac08`). P0b's M2 part
   reproduces exactly, and the new fits are 0/34 on target, as before.
2. **H2's M2 clause gains its sampling statement** (§3). This is Text A, selected by the
   seed-stability check (`5271eb2`) from two texts committed before it ran (`ea9ab01`). It is
   recorded as the amendment "Sampling rule for the H2 M2 clause: Text A selected".
3. **§6:** "0 of 35" becomes 0/69 on target, with the origin-year trend table.
4. **D1's caveat is strengthened** with M2f-r4's sampling record and the like-for-like 2023
   comparison. D1 itself is not decided.
5. **P0b's status is recorded.** Its baseline half is an environment check, deferred to P6.
6. **Numbering.** The sampling checks sit under P1; P2 is G1.

After v0.4 (2026-09-12, recorded as amendments):
7. **D1 decided: exclude.** The 69-origin M2f-r4 re-run was applied to the pre-committed
   condition (`docs/d1_precommitments.md`), and Ellie accepted the verdict. The §8 D1 row is
   updated; every "if D1 = include" clause in this plan now falls away.
8. **B1's seed.** The §2 B1 row notes that the seed takes effect only from `9a17011`, and that
   earlier B1 forecasts are unseeded.

9. **D5 decided: (b).** The live forecast is uncalibrated raw ETS, and Stage H is off the live
   critical path. The §8 D5 row, the schedule consequences and §4's rationale for the primary
   are updated.
10. **P6 done locally.** One pinned environment (`requirements-lock.txt`). The baseline half of
    P0b is still open.
11. **STOP 7 and STOP 8 recorded** (amendments of 2026-09-12). MinT stays out of the live path, and
    MinT on CONF is unchanged. The decision layer is illustrative only, and the memo ships with that
    label once it is corrected for the new live model.
12. **Memo draft corrected** (2026-09-13) for the raw-ETS live model, as the STOP 8 row requires.
    Its figures were recomputed for ICB admissions on DEV, and its four references were reconfirmed
    against primary sources: Bagust 1999, NICE NG94 ch. 39 rec. 22, Friebel & Juarez 2020, and NHS
    England 2023/24 planning guidance for the 92% line.
13. **P0b's baseline half done** (`results/P0b-baselines/`). B2, M1 v3 raw and default M1 reproduce
    exactly at origin 2019-10, and B1 reproduces across runs.
14. **D2, D4, D6 and D7 decided as recommended** (amendments of 2026-09-13). §4's lead question now
    names the recommended calibrated forecast rather than the operational one. **D3's recommendation
    revisited**, since its reason lapsed under D5 = (b); it is still open.
15. **D3 decided: (a).** M1's verdict is H3's headline, for consistency with the primary. **All seven
    decisions D1–D7 are now decided.**
16. **P2 done** (`8caf9d5`, `fd0182a`, `7ac8f3d`). G1 is registered, implemented and re-run on DEV.
    The STOP 4 rule still selects M1 + pooled and H3's verdicts are unchanged. G1 removes most of the
    ETS blow-up, leaving a residual from zero-median forecasts that D4 = (a) by design does not treat.
    §2.2's heading and D4's entry are updated to match.
17. **P3 built** (`8f3fe82`, `cebd3f6`, `dc0904a`; evidence `results/H-dryrun/dc0904a815dc/`). The
    Stage H runner, its tests and the DEV dry run; its implementation choices are two §10 rows. The
    plan's P5, P11, P13 and step-2 texts gain the notes the design needs (the 21-file input set of
    design §8, the hash-commit HEAD rule, the quarantine path, the `--amendment` log exception).
    P11's `splits.py` parts need Ellie's permission to edit that file.
18. **Design §8 agreed** (2026-09-14). P5 widens to 21 permitted input files; recorded as the
    amendment "P5 widened". The DEV-side files are generated by `prepare --dev-side` on the final
    pre-tag code, then pinned.
19. **Pre-flight closed** (2026-09-15). P11 done (`87ee1c5`, review fixes `339d527`); P13, P14,
    P10 and P7 done (`026c420`); P4 and P5 pinned, with §7.1 added (`d8ff305`); the final DEV
    dry run exits 0 on the pinned inputs (`8398d8b`, `results/H-dryrun/d8ff305dbbd7/`). Only
    P9, the tag, remains.
20. **v1.0, final for STOP 9** (2026-09-15). A consistency pass before the freeze; no rule,
    threshold or decision changes. Text written before D1 = exclude and D5 = (b) is brought into
    line: the opening finding (annotated under its original heading, which two §10 rows cite),
    §1's first tests, §2's roles and M2f-r4 row, F2, §6 step 3, §9's conflict on which M1
    carries H1, H2 and H4, §10's live forecast and P12's reason. Statuses and tenses are brought
    up to date (P0, P0b, P2, P3, P4, P8, P11 and D7; P9 stays open until the tag), and paths
    updated (the `stage_h/` package, its inputs directory, the quarantine, the archive's reach,
    the work order). §6 now matches the runner and design v2.2 in the go-ahead's order (the
    committed text is approved, then tagged), the step-2 checks, the token file, `--amendment`,
    the hash commit H1, the fit-failure count over the 19 counted units, step 6's commit and
    by-hand `conf-run-v1` tag, and the three crash cases. §1's H1 season count, §2.1's lost
    periods, §3's fragility rules, H2 M2-clause slice and H4b split, §9's two H2 M2-clause
    bullets, and §4's raw-ETS ICB table follow the §10 rows and design v2.2. §8 gains a note on what the STOP 9 go-ahead covers, and
    §9 a status line under its unchanged heading, with F2 on CONF added.

21. **Three statements in §10 rows dated 2026-09-15 corrected in place before the tag**, after the
    STOP 9 audit (git history keeps the earlier text): in "Appendix A corrected (P10)", H4's DEV
    side at the truncated origins 2018-11 and 2021-10 (their as-of and final rows do not pair, so
    both drop out) and a sentence on Appendix A's heading; in "Phase-1b tests brought into Stage
    H", ICB level described as where M2 was fitted and frozen, the §9 fallback's trigger never
    tested. No row title changed. After the tag no row is edited; a correction is a new row.
22. **STOP 9 decisions** (2026-09-15, by Ellie; §10 row "STOP 9 decisions"): D-1, the training-residual
    exception, confirmed and closed to a list; D-20, Künsch blocks kept; D-21, M2's failure limit counted
    over the 19 units (4 or more). Design §2.1 carries the closed list.