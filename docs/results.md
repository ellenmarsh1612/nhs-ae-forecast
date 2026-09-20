# Results against the frozen pre-registration (`prereg-v1`)

> **Superseded in part by the confirmatory run of 2026-09-15.** This page is the
> development-window record: everything on it was scored before the sealed window was
> opened, and it is kept as the working history. Where it disagrees with
> `docs/confirmatory_results.md`, that page stands. Corrected here on 2026-09-19: the
> "not yet evaluated" list (all four have now been evaluated or declared not evaluable);
> the ETS reconciliation figures (superseded by the G1-guarded re-run); and the
> operational-model and best-calibrated claims (settled by D1 and D5, and by the sealed
> window's coverage). Corrected on 2026-09-20, each against the table named beside it: ETS's
> horizon-6 coverage (printed 0.85, value 0.8450, `results/backtest-v1/coverage_by_horizon.csv`);
> "roughly ties ETS on all-types attendances", which holds on MASE but not on WIS
> (`results/m1-v3/bootstrap_v3_vs_others.csv`); and "every method over-covers for 2021–22
> origins", which is true of the calibrated methods only. `site/REPORT.md` lists every
> correction with its source.

> **Status of everything on this page (relabelled 2026-09-10).** Every result below was
> scored on the full 2019-09 to 2025-09 window *before* it was re-split into DEV and a
> sealed CONF window (pre-registration §10, amendments of 2026-09-10). None of it is
> confirmatory for the work order's Stage H, which is evaluated on CONF. Within
> `prereg-v1` the labels are:
>
> - **[confirmatory under prereg-v1]** the default-M1 tests of H1, H2 (M1 clause) and H4
>   at tag `backtest-v1`: registered before M1 was run, and run once;
> - **[seen before the freeze]** anything about B0, B1 and B2, which were run before
>   `prereg-v1` was tagged (disclosed at the top of the pre-registration);
> - **[exploratory]** M1 tuned, v2 and v3: variants designed after the `backtest-v1`
>   results had been read.
>
> The window these numbers come from includes the CONF origins, so their CONF-period
> content (for example the 0.92 coverage of 2025 origins) has been seen.

Running log of pre-registered tests as they are evaluated. Numbers come from
`nhs-ae-backtest run --models b0 b1 b2 m1` over the 73 monthly origins 2019-09 to
2025-09, provider level, winter months (December–March), horizon 3, as-of mode unless
stated; intervals are 95% paired bootstraps over providers (1,000 resamples).
Evaluated 2026-09-09. Files: `data/processed/backtest/`.

## H1 — skill over baseline: **confirmed** [confirmatory under prereg-v1]

M1's MASE relative to B0. The pre-registered threshold is a 15% reduction; refuted if
the interval includes 15% or less.

| Target | M1 vs B0, MASE | ETS vs B0, MASE (context) |
|---|---|---|
| Emergency admissions via A&E | −35% [−41%, −28%] | −42% [−47%, −37%] |
| Attendances, all types | −29% [−34%, −25%] | −29% [−33%, −24%] |
| Attendances, Type 1 | −28% [−31%, −25%] | −30% [−33%, −27%] |

Every interval clears 15%. The context column is the honest part of the result: with
its fixed default hyperparameters, the global LightGBM model does not beat per-series
ETS. On WIS it is level with ETS for all-types attendances (+1.8% [−1.8%, +5.3%]) and
worse for Type 1 (+7.3% [+2.5%, +11.8%]) and admissions (+20.8% [+15.0%, +26.6%]).
Beating B0 was the pre-registered bar; beating ETS was not, and M1 does not.

## H2, M1 clause — conformal M1 misses the ±5pp coverage band at horizons ≥ 4: **confirmed** [confirmatory under prereg-v1]

90% central interval coverage, pooled across providers, as-of mode:

| Horizon | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| M1 | 0.83 | 0.81 | 0.80 | 0.79 | 0.78 | 0.76 |
| ETS | 0.85 | 0.84 | 0.84 | 0.84 | 0.84 | 0.84 |
| STL+ARIMA | 0.76 | 0.79 | 0.80 | 0.81 | 0.81 | 0.82 |
| B0 | 0.86 | 0.84 | 0.81 | 0.79 | 0.77 | 0.75 |

M1 is outside the 0.85–0.95 band at every horizon, not only from 4, and its coverage
decays with horizon. Pooled conformal calibration on twelve months does not survive
the regime shifts in this series: by origin year, M1's coverage was 0.65 in 2020 and
0.92 in 2025. The M2 clause of H2 awaits M2.

## H4 (reframed) — final within 2% of as-of, same ranking: **confirmed for all four models** [M1: confirmatory under prereg-v1; B0–B2: seen before the freeze]

| Target | B0 | ETS | STL+ARIMA | M1 |
|---|---|---|---|---|
| Admissions | −0.14% | −0.39% | −0.38% | +0.08% |
| Attendances, all | −0.01% | −0.57% | −0.42% | −0.16% |
| Attendances, Type 1 | +0.02% | +0.13% | −0.06% | −0.11% |

Every interval spans zero and lies well inside ±2%. The ranking (ETS, M1, STL+ARIMA,
B0 for admissions and Type 1; M1, ETS, STL+ARIMA, B0 for all types) is identical in
both modes. H4-original is therefore refuted as predicted. The open question was
whether a global model that pools across providers would be more exposed to late
submissions; it is not.

## Amendment of 2026-09-09: M1 tuned on pre-evaluation origins — **no material change** [exploratory]

Sixteen configurations, chosen by mean WIS on as-of origins 2018-04 to 2019-08 only
(`results/m1-tuning/m1_search.csv`); the spread across the search was 9% and the winner
(learning rate 0.1, 31 leaves, 200 rounds, feature fraction 0.7, 12-month calibration)
sits close to the defaults. Re-run over the 73 evaluation origins as `m1_tuned`
(`results/m1-tuning/`), provider level, winter, horizon 3, as-of:

| Target | Tuned vs default M1, WIS | Tuned vs ETS, WIS | Tuned vs ETS, MASE |
|---|---|---|---|
| Admissions via A&E | −0.5% [−1.2%, +0.0%] | +20.1% [+14.5%, +25.6%] | +10.6% [+5.7%, +15.1%] |
| Attendances, all types | +1.0% [+0.6%, +1.4%] | +3.0% [−0.5%, +6.4%] | −4.0% [−6.8%, −1.5%] |
| Attendances, Type 1 | +1.1% [+0.7%, +1.6%] | +8.5% [+3.6%, +13.0%] | +3.9% [+0.7%, +7.0%] |

90% coverage moves from 0.80 to 0.81 at horizon 3 and from 0.76 to 0.77 at horizon 6;
still outside the band at every horizon. The 24-month calibration windows in the search
gave better coverage (0.80 against 0.77) but worse WIS, and WIS was the pre-specified
criterion. H1 and H4 are unchanged for the tuned model (H4: within 0.3% of as-of).

Conclusion: within the pre-registered search space, hyperparameters are not why M1
trails ETS. The remaining candidates are the feature set (no external covariates, no
hierarchy features), the pooled conformal calibration, and the plain fact that
per-series exponential smoothing is hard to beat on ~100 smooth, strongly seasonal
monthly points per series. The operational candidate for 31 October stays ETS, or an
ETS/M1 ensemble, and the write-up narrative stands: ML cleared the naive bar, not the
classical one.

## Amendment of 2026-09-09: M1 v2 (per-horizon models + 3-month level) — **mixed; separated into v3** [exploratory]

Motivation: M1's deficit to ETS was concentrated at short horizons (WIS ratio to ETS
1.38–1.53 at horizon 1, ≤ 1.03 by horizon 3–6 on attendances), which points at the
shared multi-horizon model and the stale 12-month level rather than at the trees.

| WIS ratio to ETS, all months, as-of | h=1 | h=2 | h=3 | h=4 | h=5 | h=6 |
|---|---|---|---|---|---|---|
| M1 default, attendances all | 1.38 | 1.06 | 0.94 | 0.89 | 0.88 | 0.90 |
| M1 v2, attendances all | 0.98 | 0.99 | 0.90 | 0.88 | 0.87 | 0.89 |
| M1 default, admissions | 1.49 | 1.24 | 1.15 | 1.11 | 1.11 | 1.12 |
| M1 v2, admissions | 1.20 | 1.16 | 1.12 | 1.11 | 1.10 | 1.13 |

The horizon-1 problem is largely gone. Winter, horizon 3, provider level, v2 against
tuned M1: admissions −7.5% WIS [−11.7%, −3.5%], all types −4.7% [−7.7%, −1.6%], Type 1
+9.0% [+4.1%, +13.4%]. Against ETS: admissions +11.0% (was +20%), all types −2.4%
[−6.0%, +1.0%], Type 1 +17.9% (was +7%).

The cost: 90% coverage collapsed to 0.57–0.70 (default M1: 0.76–0.83). A single-origin
ablation (October 2023, all-types attendances) isolated the cause. Per-horizon models
alone keep default M1's raw calibration coverage (0.70) and test coverage; the 3-month
level alone cuts raw calibration coverage to 0.60 and makes the intervals a third
narrower, and the constant conformal offset per horizon does not repair that beyond
horizon 2. The conformal step itself works: test coverage at horizon 1 after
calibration is 0.91–0.97 for every variant. Conclusion: the short level sharpens the
point forecast at the cost of calibration; the per-horizon models are a clean gain.
v3 (per-horizon, 12-month level) is registered and run separately. H4 for v2: final
within 1% of as-of on every target.

## Amendment of 2026-09-09: M1 v3 (per-horizon models, 12-month level) — **calibration kept, short horizons improved, standing at horizon 3 unchanged** [exploratory]

| WIS ratio to ETS, all months, as-of | h=1 | h=2 | h=3 | h=4 | h=5 | h=6 |
|---|---|---|---|---|---|---|
| v3, admissions | 1.14 | 1.13 | 1.14 | 1.13 | 1.15 | 1.18 |
| v3, attendances all | 0.97 | 0.93 | 0.92 | 0.89 | 0.91 | 0.93 |
| v3, attendances Type 1 | 1.15 | 1.06 | 1.05 | 1.03 | 1.03 | 1.04 |

90% coverage by horizon: 0.84, 0.82, 0.80, 0.78, 0.76, 0.75 — the same profile as
default M1 (v2 was 0.70 to 0.57). Winter, horizon 3, provider level, v3 against tuned
M1: admissions −2.9% WIS [−4.4%, −1.5%], all types +0.9% [−0.1%, +1.9%], Type 1 +3.9%
[+2.4%, +5.1%]. Against ETS: admissions +16.6% [+11.4%, +21.9%], all types +3.6%
[+0.5%, +6.6%], Type 1 +12.6% [+8.1%, +16.8%]. H4: within 0.1% on every target.

## Where the M1 line ends up [exploratory]

After the pre-registered tuning and two architectural amendments, the global LightGBM
model beats the seasonal-naive baseline by 25–40% on every target and horizon (H1
confirmed in every variant), ties per-series ETS on all-types attendances on MASE
(+0.8% [−2.1, +3.3]) while losing to it by 3.6% [+0.5, +6.6] on WIS, and
trails ETS by 13–17% WIS on admissions and Type 1 attendances at the winter horizon-3
slice, with 90% coverage of about 0.80 against ETS's 0.84. The per-horizon change is
worth keeping (v3 is the LightGBM of record from here); the 3-month level is not. The
remaining untested levers are an attendance-based rate feature for admissions and an
ETS/M1 ensemble. The operational candidate for the 31 October 2026 forecast is ETS
unless the ensemble beats it in as-of mode, and the write-up narrative is unchanged:
ML cleared the naive bar, not the classical one, and revised data flatter none of them.

## Not yet evaluated *(as at 2026-09-13; all four have since been settled)*

H2 (M2 clause), H3, H4b (decomposition of leakage into late submissions and value
revisions), H5. All four were settled by the confirmatory run of 2026-09-15: H2's M2
clause is **refuted** (the intervals cover 0.97–0.99 against a 0.85–0.95 tolerance), H3
**fails** and is fragile, H4b is **not confirmed** (it holds for all-types attendances
only), and H5 is **not evaluable** on any sealed split. See `docs/confirmatory_results.md`.

## What these results change

- The 31 October forecast should not default to M1. ETS is the best model on two of
  three targets and, on this development window, the best calibrated at every horizon beyond
  the first — at horizon 1 the seasonal-naive baseline is marginally closer to nominal, 0.856
  against 0.850 (`results/backtest-v1/coverage_by_horizon.csv`, corrected 2026-09-20).
  The candidate operational forecast is ETS, or an ensemble, with M1 kept as the model to
  improve. *(Settled since: D1 = exclude and D5 = (b) made raw ETS the live model on
  2026-09-12, and the ensemble was rejected. On the sealed window ETS is no longer the
  best calibrated — its intervals cover 97–98% at ICB level against 90% nominal, while
  M1 + pooled conformal covers 87.5–90.3%.)*
- M1's obvious next steps are the pre-registered tuning on pre-2019-09 origins,
  per-series rather than pooled conformal scores, and a wider calibration window.
  Any of these is an amendment before the results are re-inspected.
- The as-of machinery has done its job: it shows, for this collection, that revised
  data do not flatter any of these models.

---

# Work order of 2026-09-10: Stages A, D, G and E on DEV [exploratory]

Everything in this part is scored on DEV origins only (2018-04 to 2023-12, targets before
2024; CONF is sealed in code). It is development evidence, not a confirmatory test.
Designs, windows and selection rules were written into the pre-registration's amendment
log, and committed, before each stage produced a result. Tables live in
`results/A-noise-floor/`, `results/D-calibration/`, `results/G-decision/` and
`results/E-m2/`.

## Stage A — noise floor

Seed 0 of the winning M1 configuration reproduces the tuning search's recorded WIS exactly
(300.1924). On the search's own slice, WIS varies with the seed alone by an SD of **0.86%**.
The 16 configurations vary by 1.30% (12-month calibration window) and 1.46% (24-month) within a
window, so tree hyperparameters add little beyond seed noise. The 12- versus 24-month
calibration window moves WIS by about 5%, roughly six seed SDs. The reported "9% tuning
spread" was mostly that structural choice. The search winner sits at the low end of its own
seed distribution (297–305), so part of its margin was luck. On DEV (winter, horizon 3,
provider, as-of) the minimum meaningful differences are **2.6–3.4% in WIS** and
**1.0–2.7 pp in 90% coverage**, depending on the target.

## Stage D — calibration

Ten candidates; none meets the acceptance criterion (0.87–0.93 in every assessable
origin-year × horizon cell).

| Candidate | Winter-h3 WIS vs raw ETS (registered) | Outside COVID window | Worst cell | Cells in band |
|---|---|---|---|---|
| **M1 + pooled conformal (selected)** | +10.9% | +7.0% | 4.7 pp | 21/30 |
| ETS + pooled conformal | +10.2% | +3.8% | 8.3 pp | 14/30 |
| ETS raw | 0 | 0 | 14.1 pp | 5/30 |
| M1 + DtACI | +1,142% | +168% | 5.9 pp | 17/30 |
| M1 v3, in-model CQR (status quo) | +22.0% | +23.8% | 16.8 pp | 1/30 |

- **Selection by the registered rule.** No candidate meets the criterion, and M1 + pooled
  conformal has the smallest worst cell. M1 + DtACI lies within the 1.7 pp tie margin but has far
  worse WIS, so the tie-break selects M1 + pooled.
- **Coverage.** Outside the COVID window the selected method covers 0.89–0.91 at every horizon;
  in winter months it covers 0.86 at horizon 1 and 0.89–0.91 beyond.
- **Every *calibrated* method over-covers for 2021–22 origins.** Their calibration windows
  still contain the 2020 collapse. The uncalibrated and in-model methods go the other way over
  the same origins: M1 v3 raw covers 0.56–0.68, its in-model conformal 0.81–0.87 and EnbPI
  0.80–0.90 (`results/D-calibration/coverage_by_horizon_year.csv`).
- **DtACI as registered fails.** When its level reaches zero it reads the largest pooled score,
  and during and after COVID that score widens intervals by orders of magnitude (one 97.5%
  bound of 1.4 billion attendances). Its typical forecast is no worse than pooled conformal:
  the median row-wise WIS ratio is 1.09 for both. A capped variant would be a new, registered
  test.
- **Per-series conformal is worse than pooled.** It is +30–40% on WIS and over-covers:
  36 months per provider are too few once regime shifts enter the window.

## Stage G — decision layer: **fails its registered check; illustrative only**

The registered out-of-sample reconstruction (A&E admissions × trust bed-days-per-admission,
fitted only on KH03 quarters published before each quarter) misses published G&A occupancy
by a median **8.7 pp**, with **57%** of trust-quarters within 10 pp. The tolerance is 5 pp and
80%. It fails in every year and every trust-size band. Under the rule of 2026-09-09 the bed
numbers are illustrative.

Two further results from the same data:

- **Exploratory.** Naive persistence predicts occupancy far better: the latest published
  occupancy gives a 2.4 pp median error with 96% within 10 pp, and the same quarter last year
  does the same. Occupancy is managed around capacity, so A&E demand carries little of its
  quarterly variation. A redesign (occupancy persistence plus an admissions-surprise term)
  would have to be registered before it is tested.
- **Breach probabilities have no skill.** Across 1,065 DEV winter trust-quarters (47% of them
  breaching 92%), every candidate's P(breach) scores a Brier of 0.26–0.31, worse than always
  forecasting the base rate (0.249). The decision-loss ranking is therefore uninformative, and
  under the registered rule it was not used for selection.

## Stage E — M2 ladder at ICB level (M2a, M2b, M2c)

36 ICBs (current mapping, under §9), 35 even-month DEV origins, PyMC 6.3 + nutpie.

| Rung | Winter-h3 WIS vs ETS | Outside COVID | 90% coverage by horizon | Fits meeting R-hat < 1.01, ESS > 400 |
|---|---|---|---|---|
| M2a (registered spec) | +63.7% | +50.9% | 0.82 → 0.78 | 0/35 (max R-hat 1.08, min ESS 56) |
| M2b (hierarchical seasonality) | +64.6% | +50.5% | 0.82 → 0.78 | 0/35 |
| M2c (structured dispersion, on M2a) | +73.4% | +51.5% | 0.79 → 0.77 | 0/35 |
| M1 + pooled conformal at ICB level | +18.1% | +5.5% | 0.93 → 0.87 | — |

- **Retention (work-order rule).** M2b is rejected (WIS +0.5%, needed below −3.0%). M2c is
  rejected (+5.9%). The highest retained rung is M2a.
- **Diagnosis.** The linear trend and COVID dummy put M2's level in the wrong place after
  COVID. For 2021 origins the median over-forecasts by about 15%, and 22% of outturns fall below
  the 10th percentile. Before COVID its intervals are twice as wide as ETS's.
- **What it points to.** This is the failure the work order's M2d (random-walk level) is
  designed to fix.
- **Sampling.** No divergences, but mixing is poor under the mandated non-centred
  parameterisation with very informative data. That is a known pathology [inference], and a
  centred parameterisation of the ICB effects is the likely remedy.
- **Pending.** STOP 5 decision: continue to M2d, whether M2 enters the 31 October forecast,
  and ICB versus provider level.

### Stage E continued — centred M2a and M2d (random-walk level) [exploratory]

The centred parameterisation, the M2d specification and four development changes to it
were registered before the M2d backtest (see the amendment rows of 2026-09-10). The
development changes were found through diagnostic fits at three origins, none of them
scored:

1. The booked-era flag was dropped, because it is not identified next to a heavy-tailed walk.
2. ICB-month reporting artefacts (≤ 0 or below 10% of the trailing median) are treated as
   missing.
3. The noise scales got priors that vanish at zero.
4. All-types attendances are modelled directly rather than as Type 1 + other.

| Rung (ICB level, 35 DEV origins) | Winter-h3 WIS vs ETS | 90% coverage h1 → h6 | Worst assessable cell | Fits meeting R-hat < 1.01 and ESS > 400 |
|---|---|---|---|---|
| M2a, centred (`m2a_c`) | +60.0% | 0.83 → 0.79 | 7.8 pp | 33/35 |
| **M2d** | **+12.8%** [+6 to +26% by target] | 0.92 → 0.84 | 9.1 pp | 0/35 (median R-hat 1.04) |
| M1 + pooled conformal at ICB level | +18.1% | 0.93 → 0.87 | 8.5 pp | — |

- **Centring works as the probe predicted.** Sampling quality went from 0 of 35 fits meeting
  the targets to 33 of 35. The scores are unchanged (+60% against +64%), as they should be for
  a reparameterisation.
- **M2d removes the bias that sank M2a–M2c.** WIS is 29.5% lower than its base, beats the
  Stage D selection at ICB level, and the PIT histogram is nearly flat (largest bin 0.13
  against 0.21). All types fell below Type 1 in 0.2% of forecasts.
- **Its intervals have the wrong shape over time.** They are too wide in calm years (0.94–1.00
  in 2019, 2022 and 2023) and too narrow around the shock. One random-walk scale, estimated over
  a history containing COVID, is inflated for everything that follows.
- **Retention rule: M2d is rejected.** The work order requires the worst cell to move towards
  nominal, and it moved 1.2 pp away.
- **Its sampling is still short of target**, so its tail quantiles carry Monte Carlo noise.
- **The next step is a decision.** Keep the rule's verdict (M2a stays the highest retained
  rung), or override it and build the next rung on M2d with a registered fix for its interval
  width.

### Stage E continued — M2d carried forward (override), M2d2 and M2e [exploratory]

Ellie overrode the retention rule for M2d (amendment of 2026-09-10). M2d2 and M2e were
registered before either was fitted, and each was judged by the rule against M2d.

| Rung (ICB level, 35 DEV origins) | Winter-h3 WIS vs ETS | Worst cell | Sampling | Rule |
|---|---|---|---|---|
| M2d (base, carried forward) | +12.8% | 9.1 pp | median R-hat 1.04 | override |
| M2d2 (COVID-regime walk volatility) | +48.1% | **6.6 pp** | median R-hat 1.018, ESS 222 | rejected (WIS +31%) |
| M2e on M2d (ICB winter term on the admission rate) | +12.2% | 9.1 pp | 7 divergences in 35 fits | rejected (WIS −0.5%, within noise) |

- **M2d2 fixes what it targeted, but is rejected on WIS.** Outside the COVID window its intervals
  are a third narrower than M2d's (19% of the median against 28%), its worst cell improves from
  9.1 to 6.6 pp, and its 2023-origin WIS is 24% better. Its WIS is lost inside the COVID window
  (2,715 against 1,314): the registered forecast rule assumes the COVID volatility persists
  through the horizon, which makes forecasts made during COVID very wide. Outside the window
  its WIS is 3.6% above M2d's, just beyond the 3.0% minimum meaningful difference. The rule
  counts COVID-window origins in WIS, so M2d2 is rejected.
- **M2e adds nothing measurable.** The ICB-specific winter conversion term moves WIS by 0.5%
  and produced the ladder's first divergences (7 across 35 fits). That is the centred
  parameterisation's known weakness when a group has little data: roughly eight winters per
  ICB inform each winter term.
- **Result.** M2d remains the highest retained rung, and M2f is built on it.

### Stage E — M2f not run; aggregate coherence measured on M2d [exploratory]

- **M2f as registered is not identified.** Diagnostic fits (none scored) showed the national walk
  trading places with the ICB walks: R-hat 3.2–3.5, fixed by centring the ICB walks. They also
  showed it trading places with the shared Fourier seasonality: R-hat 4.0 after centring, with no
  clean constraint, because a walk smooth enough not to mimic seasonality would also be too smooth
  to carry COVID. The specification is returned to Ellie.
- **Aggregate coherence is nonetheless a real problem.** M2d was refitted with joint draws
  (same model and seeds; its ICB forecasts are reproduced exactly), and its ICB draws were summed:

| M2d, 90% interval coverage by horizon (DEV ladder origins) | h1 | h3 | h6 | all horizons (90% / 50%) |
|---|---|---|---|---|
| ICB | 0.92 | 0.88 | 0.84 | — |
| Region (sum of ICB draws) | 0.67 | 0.74 | 0.69 | 0.70 / 0.35 |
| England (sum of ICB draws) | 0.28 | 0.37 | 0.49 | 0.40 / 0.16 |

- **Why.** Independent ICB walks let common shocks cancel in the sum, so aggregate intervals are
  far too narrow. Any hierarchical forecast built on M2d needs correlated ICB innovations, either
  by construction (a working M2f) or after fitting (Stage F's sample-path reconciliation).

### Stage E — correlated innovations and the M2 freeze (STOP 6) [exploratory]

`m2d_corr` keeps M2d's fitted model and draws future ICB innovations with the historical
cross-ICB correlation of M2d's own walks (registered before it was run). At ICB level it is
M2d, as designed: winter-h3 WIS +12.7% against +12.8%, with coverage within 0.002 at every
horizon. At aggregate levels:

| Summed ICB draws, all months | Region 90% / 50% coverage | England 90% / 50% coverage | England winter-h3 WIS |
|---|---|---|---|
| M2d (independent innovations) | 0.70 / 0.35 | 0.40 / 0.16 | 51,038 |
| **`m2d_corr` (correlated innovations)** | **0.80 / 0.47** | **0.74 / 0.44** | **31,921** |

- **Correlated innovations close most of the gap, not all of it.** Aggregates still under-cover.
  The likely reasons are the 20% shrinkage and correlations estimated from posterior-mean
  paths, which are smoother than the true innovations [inference].
- **The freeze.** M2 is frozen at `m2d_corr` on 2026-09-11 (tag `m2-frozen-v1`; the STOP 6 table
  is in `results/E-m2/stop6.txt`). Its known weaknesses are listed in the freeze amendment.
- **M2f.** The redesign continues as a separate phase-1b model (branch `m2f-redesign`,
  `docs/m2f_redesign.md`). Its first attempt, a sparse-jump national walk, failed identification.

## Stage F — reconciliation (F1, H3) and built-in coherence (F2) [exploratory]

The design was registered on 2026-09-11 before any result: the Stage F and F2 amendments,
plus an implementation-details amendment written after a two-origin smoke run with no scores.
**Hierarchy:** mapped providers → 36 ICBs → 7 regions → England. **Base models:** ETS, STL+ARIMA
and M1, each fitted and pooled-conformal calibrated at every level. **Reconciliation:**
MinT-shrink, applied quantile by quantile. Providers without a base forecast are carried as one
unobserved "rest" node per ICB.

Two problems surfaced during the run:
- **Row-count bug (fixed).** Where M1 had no England forecast, whole origin-horizons were
  dropped. This was found from row counts before any table was read (commit d70d0a2).
- **ETS artefact.** It surfaced in the first tables (below). F2's WIS reference therefore
  moved from ETS + pooled to M1 + pooled. That is a presentation choice; no test depends on it.

Full tables are in `results/F-reconciliation/`.

**H3 fails on DEV for all three bases.** H3 is registered as ICB WIS improving (95% interval
below zero) *and* provider WIS worsening by no more than 2%. The figures below are winter h=3
WIS, reconciled relative to the calibrated base:

| Base | ICB (95% CI) | Provider | Region | England | H3 |
|---|---|---|---|---|---|
| ETS (unguarded) | −53.1% [−94.7%, +8.0%] | +3,449% | −98.3% | −100.0% | fails (**artefact**, below) |
| ETS (G1, as issued) | +9.0% [+7.1%, +10.7%] | +5.4% [+4.5%, +6.3%] | +4.6% | −13.4% | fails |
| STL+ARIMA | +0.3% [−1.5%, +1.9%] | +2.7% [+1.1%, +4.2%] | −2.7% | −7.5% | fails |
| M1 | +11.1% [+10.2%, +12.0%] | +11.6% [+8.8%, +14.8%] | +2.8% | −2.9% | fails |

- **Read the G1 row, not the unguarded one.** The guard registered on 2026-09-13 marks
  all-zero ETS forecasts as failed; the confirmatory run applies it. With it, reconciliation
  costs ETS 9.0% at ICB level rather than appearing to save 53%
  (`results/F-reconciliation-G1/README.md`). The unguarded row is kept because the
  blow-up it exposes is the reason the guard exists.
- **The unguarded ETS rows measure a calibration blow-up, not reconciliation.** The chain has four links:
  1. At origin 2020-05, ETS forecasts exactly zero (every quantile) for 7 England, 45 region,
     194 ICB and 324 provider series-horizons. That is its damped trend extrapolating April
     2020 below zero.
  2. These forecasts enter the pooled conformal sets, and aggregate pools are tiny. England's
     pool holds at most 12 scores per horizon, so the 95% and 97.5% adjustments equal its
     largest score. With a zero forecast, that score is the log of the outturn itself, about
     14 for England. It inflates upper quantiles by a factor of up to about e¹⁴ ≈ 10⁶: the
     largest England 95% quantile is 9.7×10¹⁰ and the largest 97.5% quantile 4.8×10¹².
     (Corrected 2026-09-11; the first version said "about 13" and "9×10¹⁰", which was the
     95% quantile.)
  3. The inflation lasts until 2021-10. It affects 6–9% of calibrated ETS aggregate forecasts.
  4. MinT then pushes those quantiles down onto the providers: 1,859 provider 97.5% quantiles
     inflated more than tenfold.

  STL+ARIMA and M1 have no such rows at any aggregate level (`calibration_blowups.csv`).
- **STL+ARIMA:** reconciliation is neutral at ICB level. It helps the aggregates a little and
  costs providers 2.7%, so it fails both clauses narrowly.
- **M1, the operational model:** reconciliation hurts by about 11% at both ICB and provider
  level. At ICB level the reconciled winter-h3 median error is 8.8% of outturn. That is worse
  than both M1's own ICB forecast (8.0%) and the sum of its provider forecasts (8.7%), so the
  pull comes from above the ICBs. The likely source is M1's region and England models,
  LightGBM fitted to 7 and 1 series [inference]. *Check:* rerun MinT without the region and
  England rows.

**F2 (35 ladder origins, winter-h3 WIS relative to M1 + pooled; coverage all months / outside
COVID):**

| Contender | Level | Mean gap between medians | WIS vs M1 + pooled | 90% / 50% cov. | Outside COVID |
|---|---|---|---|---|---|
| M1 + pooled | ICB / region / England | 3.0% / 3.6% / 3.6% | 0 | 0.91/0.55 · 0.87/0.51 · 0.86/0.54 | 0.94/0.63 · 0.91/0.59 · 0.90/0.69 |
| M1 + pooled + MinT | ICB / region / England | 0.5% / 0.03% / 0.02% | +23.1% / +13.9% / −14.4% | 0.90/0.46 · 0.94/0.55 · 0.94/0.57 | 0.93/0.54 · **0.99/0.65 · 1.00/0.69** |
| **M2f-r4** (phase 1b) | ICB / region / England | n/a / 0.12% / 0.06% | +4.7% / −2.4% / −26.7% | 0.90/0.59 · 0.88/0.56 · 0.88/0.56 | **0.93/0.58 · 0.90/0.52 · 0.90/0.52** |
| `m2d_corr` (frozen M2) | ICB / region / England | n/a / 0.18% / 0.07% | −4.5% / −13.4% / −37.4% | 0.86/0.55 · 0.80/0.47 · **0.74/0.44** | 0.96/0.65 · 0.91/0.56 · 0.85/0.52 |

- **The registered prediction holds.** MinT delivers coherence but not calibration.
  - Quantile-by-quantile reconciliation over-covers the aggregates outside COVID: 90%
    coverage is 0.99–1.00 at region and England level, for both ETS and M1.
  - The ICB-level gap left after MinT is the rest nodes. The region and England gaps come from
    re-sorting quantiles that cross after projection.
- **M2f-r4 is the only contender that is both coherent and close to nominal at every level
  outside COVID.**
  - Its WIS is level with M1 + pooled at ICB and region level, and 27% better at England
    level. The England gain partly reflects how weak M1's one-series England model is
    [inference].
  - Its known weakness is unchanged: forecasts made inside COVID are very wide (Stage E).
- **Unreconciled M1 + pooled is incoherent.** Its region and England medians differ from the
  sum of their children by 3.6% on average. For comparison, the median non-additivity of M2's
  coherent draws is 0.06–0.18%.
- **The frozen M2 is the sharpest contender but under-covers England:** 0.74 at 90% across all
  months, 0.85 outside COVID.

**What this changes.**
- MinT stays out of the live pipeline, since it makes M1 worse.
- The built-in-coherence route (M2f-r4) is the one that works. That argues for M2f-r4 over
  post-hoc reconciliation wherever aggregate forecasts are needed, once phase 1b allows it.
- The ETS artefact exposes a fragility in the registered calibration: pools of 12 scores at
  England level, and zero forecasts accepted as valid. The Stage H plan should guard against
  both before CONF is unsealed. CONF's calibration windows do not reach 2020, but the fragility
  is general.
