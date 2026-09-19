# Confirmatory results on CONF (Stage H)

> **What makes this confirmatory.** Every number below comes from one scoring of the sealed
> CONF window, run on 2026-09-15 against a plan and a design frozen beforehand at the tag
> `conf-plan-v1`. The statistics, slices, verdict rules and fragility rules were fixed in
> `docs/confirmatory_plan.md` v1.0 and `docs/stage_h_design.md` v2.2 before any CONF row was
> read; the decisions those documents left open were taken at STOP 9 and recorded as
> amendments before the tag. Nothing here was adjusted and re-run: the run wrote its tables
> once, and no result on this page was recomputed after being seen.
>
> **What confirmatory does not mean here.** CONF is sealed going forward, not unseen
> (`docs/preregistration.md` §10, "Disclosure: CONF is sealed going forward, not unseen").
> B0, B1, B2 and M1 in every variant were scored on all 73 origins *before* the split, CONF
> origins included, and aggregate results over them were read. For those specifications CONF
> is a **re-test**. It is a first test only for the specifications created after 2026-09-10:
> the calibration methods (pooled conformal, G1) and M2. The prospective window, scored from
> February 2027, is the only test no specification has seen. H1, H2's M1 clause and H4 were
> also tested once before, at tag `backtest-v1`, on that old 73-origin window.
>
> This page is the CONF counterpart of `docs/results.md`, which holds the DEV and pre-freeze
> record. Where the two disagree, this one is the confirmatory statement and the other is
> exploratory.

## Verdicts

| Registered test | Verdict | Fragile? |
|---|---|---|
| **Primary** (§7.5): the recommended forecast's 90% intervals cover ≈ 90% | **within tolerance** | no |
| **H1** — M1 beats the seasonal-naive baseline by > 15% | **confirmed** | no |
| **H2, M1 clause** — conformal M1 misses the ±5 pp band at h ≥ 4 | **confirmed** (under-covers) | no |
| **H2, M2 clause** — M2's own intervals hold ±5 pp | **refuted** (over-covers) | no |
| **H3** — reconciliation improves ICB WIS without hurting providers | **fails** (headline: M1) | **yes** |
| **H4** — revised data does not change accuracy | **confirmed** (exploratory on CONF) | no |
| **H4-original** — revisions change the ranking or the gain by > 5 pp | **does not hold** | no |
| **H4b** — late submissions outweigh value revisions | **not confirmed** (*seen*) | n/a |
| **H5** — cold start | **not evaluable**, and never testable on a sealed split | n/a |

Three of the nine went against the pre-registration's stated expectation: H2's M2 clause, H3
and H4b. H4-original does not count — §7 registers it as *predicted to be refuted*, and
"does not hold" is that prediction coming true. The section "What did not work" collects
them.

## The run and its audit trail

| Fact | Value |
|---|---|
| Plan tag | `conf-plan-v1` → commit `14202e2`, tag object `c4e72e0` |
| Forecast-hash commit (H1) | `f56db9e` |
| Results commit (R) | `37892ab`, tagged `conf-run-v1` (tag object `d062813`) |
| Unseal log | **one line**, 2026-09-15T18:04:53Z, token = the tag commit, head = `f56db9e`, 21 sealed rows, origins 2024-01-01 … 2025-09-01 |
| Prior log lines / witness lines | 0 / 0 |
| Environment | Python 3.13.12, macOS 15.2 arm64, no drift from the lock (`fbb03112…`) |
| Inputs | 21 pinned files, generated at `026c420`; vintage table 1,072,039 rows (`db419ce4…`), 8 parse failures, exactly as pinned |
| Tables written | 175, plus `verdicts.json` and the run's own `confirmatory_results.md` |

Four integrity checks ran with the results, and all four passed:

- **Pre-seal forecasts reproduce (P13).** Regenerated B0, STL+ARIMA and default M1 forecasts
  are identical to the quarantined pre-seal files, row for row (691,254 as-of and 692,874
  final rows each). B1 differs as expected and only because the ETS seed bug was fixed on
  2026-09-12: it is now seeded, so its simulated intervals moved (29% of rows identical,
  median relative difference 0.6%).
- **The three duplicate origins are one information set (D7).** The as-of input slices for
  2025-07, 2025-08 and 2025-09 hash equal (`5418189190e6…`). Every deterministic forecast at
  2025-08 and 2025-09 — B0, B1, B2, default M1, M1 v3 raw — is bit-identical to the one at
  2025-07. M2's are not: `m2d_corr` re-samples, so its ICB, region and England forecasts
  differ at those origins (largest absolute difference 30,534 attendances at England level),
  and they are checked against the registered seed-stability limits instead (median ratio
  ≤ 0.05, p95 ≤ 0.2), which they meet. CONF therefore carries 19 distinct information sets;
  pooled statistics use CONF19, and CONF21 is reported alongside.
- **No statistic failed.** Every registered path produced a verdict or a recorded "n/a", and
  `verdicts.json` holds no `_errors` key — the runner writes one on any exception.
- **G1's failure mode does not occur on the new origins.** G1 marks all-zero forecasts for a
  live series; its registered scope is B1, B2 and M1 v3 raw. ETS has 318 provider, 194 ICB,
  45 region and 7 England failed forecasts and STL+ARIMA has 116 provider and 4 ICB, but
  **none of them falls on the 21 new origins**; all but one sit on DEV origins, the
  remaining one on a pre-DEV burn-in origin. So on CONF the "as issued" and "failed dropped"
  variants reach the same verdict wherever both exist, and are n/a where there is nothing to
  drop. B0 is outside G1's scope and does produce all-zero forecasts on CONF: 53 of them
  inside the H1 winter slice, counted and not treated, as registered.

## Primary comparison — **within tolerance**

The primary is the calibration selected at STOP 4: M1 v3 raw plus pooled conformal, G1 as
issued, provider level, as-of mode, all months, pooled over providers and targets, 19
origins. Under D5 = (b) this is the project's *recommended remedy*, not the model being
published in October; the live model has its own section below.

| Horizon | cov90 | 95% interval | Inside [0.85, 0.95]? |
|---|---|---|---|
| 1 | 0.875 | 0.851 – 0.906 | yes |
| 2 | 0.883 | 0.865 – 0.909 | yes |
| 3 | 0.887 | 0.862 – 0.917 | yes |
| 4 | 0.896 | 0.881 – 0.920 | yes |
| 5 | 0.895 | 0.875 – 0.925 | yes |
| 6 | 0.903 | 0.884 – 0.925 | yes |

Coverage rises with horizon rather than collapsing, which is the opposite of the pattern the
same forecasts show without calibration (0.749 at h = 1 falling to 0.683 at h = 6). The
tightest margin is at h = 1, where the lower bound is 0.8514. One of the twelve origin-year
cells sits outside DEV's range (2024, h = 2: 0.877 against DEV's 0.879–0.937). A range flag
decides nothing; it is reported because §7.13 requires it.

The calibration step is the part of this that CONF tests for the first time. The base
learner had already been scored on these origins before the seal.

## H1 — skill over the baseline: **confirmed**, not fragile

Slice: default M1 against B0, MASE, provider level, as-of, h = 3, winter months, the five
winter-h3 origins (W5). This test was also run once at `backtest-v1` on the old window.

| Target | Relative MASE | 95% interval | Verdict |
|---|---|---|---|
| All-types attendances | −47.6% | −52.5% to −42.1% | confirmed |
| Type 1 attendances | −44.8% | −50.1% to −39.4% | confirmed |
| Admissions via A&E | −38.4% | −44.6% to −31.6% | confirmed |

M1 v3 raw, reported alongside, clears the bar on all three targets as well (−35.5%, −33.0%,
−45.2%). Dropping any one of the five origins leaves every interval below −15%, so the
verdict is not fragile. Type 1's CONF figure lies outside DEV's winter range (DEV: −42.5% to
−2.9%); CONF is the better winter for M1, not the worse.

**The caveat that matters.** W5 is five origins — 2024-01, and 2024-10 to 2025-01 — whose
horizon-3 targets are March 2024 and then December 2024 to March 2025: one complete winter
plus one March, as the amendment "§9 applied to CONF" records. The bootstrap resamples
providers *within* that winter, so it measures provider variation, not between-winter
variation. On DEV, ETS's yearly coverage ranged from 0.51 to 0.96, which is the scale of the
between-winter variation this design cannot see. This is the registered §9 caveat, and it
applies to H1 and to both H2 clauses.

## H2, M1 clause — **confirmed**: conformal M1's own intervals under-cover

Default M1 (in-model conformal), provider level, all months, 19 origins.

| Horizon | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| cov90 | 0.846 | 0.846 | 0.843 | 0.833 | 0.819 | 0.814 |
| 95% interval | .808–.888 | .819–.878 | .817–.871 | .810–.861 | .796–.852 | .788–.843 |

The clause turns on the point estimate falling outside [0.85, 0.95] at some horizon in 4–6;
it does, at all three, and the direction — under-coverage — is named, not decisive. On
CONF19 the point estimate is below the band at every horizon; under the 21-origin variant
h = 1 is 0.8501, just inside, and the verdict is unchanged. The interval crosses 0.85 at
horizons 1–5.

## H2, M2 clause — **refuted**

The frozen hierarchical model `m2d_corr`, its own posterior intervals, no conformal step, ICB
level, all months, 19 origins.

| Horizon | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| cov90 | 0.970 | 0.993 | 0.989 | 0.992 | 0.990 | 0.992 |
| 95% interval | .931–.993 | .983–.998 | .976–.997 | .979–.999 | .976–.999 | .981–.999 |

The registered prediction was that M2 would hold the ±5 pp band at every horizon. It misses
the band at every horizon by being too wide: at h ≥ 2 roughly one outturn in a hundred falls
outside a 90% interval. Of the models whose intervals were *designed* to be calibrated, M2 is
now the worst on CONF. Its winter-h3 ICB WIS is also about 21–27% worse than M1 + pooled
(geometric mean +24%).

The clause was evaluable: all 21 fits completed, 0 failed, against a registered limit of 4
failures among the 19 counted units, and no fit was excluded on its diagnostics, as
registered. Sampling was better than the DEV trend predicted but is not clean: the
origin-year medians of the maximum R-hat are 1.048 (2024) and 1.039 (2025) against 1.069 for
DEV's 2023 origins, yet **9 of the 21 individual fits exceed §5's R-hat target of 1.05**, the
worst at 1.122 (origin 2024-04, minimum bulk ESS 25.9). No fit had a divergence. The
registered limitation — diagnostics degrading with origin date, so the CONF fits would be the
worst-sampled in the project — did not materialise at the level of origin-year medians, but
the fits carrying this verdict are not well mixed.

**A labelling note, not an erratum.** `verdicts.json` records `h2_m2.phase` as "a phase-1b
test at ICB level, under the §9 fallback: M2 was never sampled at provider level, so the
clause registered as pooled across providers is tested at ICB level, in Stage H, by an
amendment that overrides the freeze-time deferral". The opening phrase is the frozen design's
own sentence (`docs/stage_h_design.md` §7.5 at the tag), and the run reproduced it correctly.
It is shorthand: the amendment of 2026-09-15 ("Phase-1b tests brought into Stage H") states
the position more carefully — §9's fallback *names* the ICB level, but its trigger, a
provider-level M2 failing to sample, was never tested, because a provider-level M2 was never
built. The authority for testing the clause at ICB level is that amendment, which explicitly
overrides the freeze-time deferral. The write-up should use the amendment's wording; the run
output stands as written.

## H3 — reconciliation: **fails**, and the headline verdict is fragile

Slice: MinT-reconciled against unreconciled base forecasts, winter h = 3, W5. The headline is
M1's verdict (D3 = (a)).

| Base | Verdict | ICB, upper end of the interval | Provider, point | Fragile |
|---|---|---|---|---|
| ETS | holds | −0.022 | −0.005 | yes (fails when 2024-10 is dropped) |
| STL+ARIMA | fails | +0.119 | +0.060 | no |
| M1 (headline) | fails | +0.020 | +0.052 | yes (holds when 2024-12 is dropped) |

For M1, reconciliation adds about 5% to provider-level WIS while leaving ICB-level WIS
statistically unchanged, which is the registered rule's definition of failing. Two of the
three verdicts flip on a single origin out of five, so the honest statement is that one
winter cannot settle H3. Why reconciliation helps ETS here is not established by this run:
the zero-forecast pathology that motivated G1 sits on a DEV origin, and ETS has no failed
forecasts on the CONF origins, so any mechanism would have to be argued from the W5 rows
themselves. R2 (sample-path reconciliation) stays in phase 1b and was not tested.

## H4 — revision leakage: **confirmed** (exploratory on CONF)

Winter h = 3 WIS in final mode against as-of mode, provider level, W5, per model and target.
The registered bar is 2%.

Across the twelve deciding cells — B0, B1, B2 and default M1 × three targets — the largest
deviation is **0.37%** (default M1, admissions), and every interval lies inside ±1%. The
model ranking is identical in both modes for all three targets. M1 v3 raw, reported
alongside and the base learner of the primary, moves further: −1.35% on admissions with an
interval reaching −3.45%. That is still inside the 2% bar on the point estimate, which is
what the rule uses, but it is the one cell where revision sensitivity is visible at all.

H4-original — a ranking change, or a gain over B0 differing between modes by more than 5 pp
— **does not hold**: the largest move is 0.66 pp (M1 v3 raw, admissions).

Under the amendment "§9 applied to CONF", H4's CONF result is exploratory, because the winter
slice has one winter rather than the four §9 requires. Its confirmatory statement was made at
tag `backtest-v1`, on the old 73-origin window — which included the CONF origins. CONF agrees
with it: for this collection, backtests on revised data are not materially optimistic.

## H4b — late submissions against value revisions: **not confirmed** (*seen*)

| Target | Origins where the late-submission component is larger | Needed | Verdict |
|---|---|---|---|
| All-types attendances | 16 of 19 | 10 | confirmed |
| Type 1 attendances | 0 of 19 | 10 | not confirmed |
| Admissions via A&E | 0 of 19 | 10 | not confirmed |

Overall: not confirmed, and this is the third result to go against the registered
expectation. The CONF pattern is sharp — all-types attendances are dominated by late
submissions at 16 of 19 origins, the other two targets never are. DEV shows the same
ordering much more weakly (21 of 69, 11 of 69, 11 of 69), so the strength of the CONF split
is a CONF finding, not a DEV one. All-types attendances are the target that sums only
providers with complete returns, which is a plausible mechanism for the split but is not
something this run tests. The test is labelled *seen*: the decomposition was computed and
read before the freeze.

## H5 — cold start: **not evaluable**

M2 exists only at ICB level, and the current 36-ICB mapping is applied to the whole history,
so no ICB series has a cold start. A provider-level M2 was never built. CONF is the only
sealed split and is scored once, so no sealed test of H5 remains. This was recorded as an
amendment before the tag, so the omission is a decision rather than a silence.

## The live model's own numbers — and why they are now CONF-informed

The forecast being published on 31 October is raw ETS at ICB level (D1 = exclude, D5 = (b)),
with no conformal step. Its CONF coverage is reported descriptively in the headline:

| Horizon | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| cov90, ICB, as-of | 0.977 | 0.974 | 0.978 | 0.978 | 0.981 | 0.982 |

The live forecast's 90% intervals are **conservative**: they cover about 97–98% where 90% is
intended, so they are wider than they need to be, in the direction that over-warns rather
than under-warns. The comparable DEV figure, 0.889–0.930 by horizon outside COVID, is
recorded in the D5 = (b) amendment (`docs/preregistration.md` §10), so this is a CONF-period
result rather than a restatement of DEV.

**What this must not become.** Under P12 the live model is fixed as of the tag, and *any*
later change to it is recorded as CONF-informed. Narrowing the live intervals because of the
numbers in this table would be exactly such a change: a choice made after seeing the sealed
window, after which the published forecast could no longer be described as untouched by CONF.
The recommendation is to publish as fixed, state the conservatism as a known property, and
let the prospective scoring from February 2027 settle it.

## What did not work

Kept prominent, as the brief requires.

- **The hierarchical model failed its own calibration test.** M2 was built to be the
  well-calibrated probabilistic model. On CONF its intervals cover 0.97–0.99 at 90% nominal,
  and its winter-h3 ICB WIS is about a quarter worse than M1 + pooled. Nine of its 21 fits
  also sample above the registered R-hat target.
- **Reconciliation did not deliver.** H3 fails for the headline model and for STL+ARIMA, and
  the one base where it holds is fragile. MinT bought coherence and cost provider accuracy.
- **The uncalibrated tree model is badly overconfident.** M1 v3 raw covers 0.749 at h = 1,
  falling to 0.683 at h = 6, against 90% nominal. Conformal calibration is doing the work in
  the primary, not the learner.
- **H4b is confirmed for one target in three.** The pre-registration's expectation that late
  submissions dominate generally is not supported.
- **A registered hypothesis turned out to be untestable.** H5 could never be evaluated on any
  sealed split, because the model it compares never existed at the level it needed.
- **The live model over-covers**, and the rules that protect the pre-registration are what
  stop that finding from being acted on before the forecast ships.

## Limitations

1. **One winter.** H1, H3, H4 and F2 all rest on W5: five origins whose horizon-3 targets are
   March 2024 and December 2024 to March 2025. Provider bootstraps within one winter cannot
   capture between-winter variation; DEV's yearly ETS coverage spread (0.51 to 0.96) is the
   scale of what is unmeasured.
2. **CONF is a re-test for the pre-seal specifications**, as the disclosure at the top says.
   The genuinely first tests here are the calibration methods and M2.
3. **Fragility is reported, not hidden.** Two of H3's three verdicts each turn on one origin.
   H1's and the primary's do not.
4. **19 information sets, not 21.** Origins 2025-07, 2025-08 and 2025-09 share one as-of
   information set, proved by hash. Pooled statistics use CONF19; CONF21 is reported
   alongside and reaches the same verdict everywhere.
5. **M2's sampling.** The registered target is R-hat ≤ 1.05 with no divergences; there is no
   registered ESS target. DEV's origin-year medians exceed 1.05 in two of six years (1.052 in
   2022, 1.069 in 2023), and on CONF 9 of 21 individual fits exceed it. No fit was excluded
   on diagnostics, by rule.
6. **Labels.** H4 on CONF is exploratory (amendment "§9 applied to CONF"); F2 on CONF is
   secondary and descriptive; H4b is *seen*; H3's region level carries a 7-series caution and
   England is n/a with one series.

## What this changes

- **The live forecast does not change.** Under D5 = (b) it never depended on Stage H, and P12
  fixes it at the tag. Publish as fixed, with the conservatism stated.
- **The recommended remedy stands.** M1 + pooled conformal + G1 holds its 90% band at every
  horizon across the sealed window. The calibration layer is the part CONF tested first-hand,
  and it held.
- **The headline claim is evidenced.** Forecasts of this kind, uncalibrated, are overconfident
  — the tree model covers 0.68–0.75 against 90% nominal — calibration fixes it (0.875–0.903),
  and the size of the gap is now measured on a sealed window rather than asserted. The claim
  is about this model class, not about every method here: raw ETS errs the other way and
  over-covers.
- **Nothing is re-run.** The plan's "after the run nothing is adjusted and re-run" holds: this
  page reports the single scoring, including the three results that went against the
  pre-registration.

## Sources

Everything above is read from `results/H-confirmatory/` at commit `37892ab` (tag
`conf-run-v1`): the run's own `confirmatory_results.md`, `verdicts.json`, `tables/*.csv`,
`provenance.json`, `m2_fits.csv`, `p13_check.csv`, `d7_check.csv`, `unseal_entry.json` —
except the DEV coverage figure for raw ETS and the disclosure and label statements, which
come from `docs/preregistration.md` §10 and are attributed where used. The registered rules
are `docs/confirmatory_plan.md` v1.0, `docs/stage_h_design.md` v2.2 and §10's amendment
table.

For the public write-up, the independent corroboration the brief asks to cite early (Stage
I2) is Cece, Köse & Elmas (2026), *International Journal of Medical Informatics* 219:106579,
which reaches a "nothing beats seasonal naive" conclusion for A&E demand at national level,
with multiple-comparison correction. Reference checked by Ellie, 2026-09-18.

Cite it for what it actually supports. It is **not** corroboration of H1: at provider level,
in winter, this project finds large skill over the seasonal-naive baseline (−38% to −48%
MASE, confirmed). What it corroborates is the negative half of the project's model-class
finding — that the gains do not come from the learner. On DEV, default M1 does not beat ETS;
on CONF, the uncalibrated tree model is the most overconfident forecast in the comparison,
and the calibration layer, not the machine learning, is what carries the primary.
