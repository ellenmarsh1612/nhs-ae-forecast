# D1 pre-commitments (WO-A, step 1), written before any 69-origin M2f-r4 fit

Sections (a), (b) and (c) are copied verbatim from Ellie's WO-A of 2026-09-12. They were committed before any fit of WO-A's step 2. The commit SHA and time are recorded in the git history, and in `results/E-m2f-69/README.md` beside the first fit's time.

**(a) D1 condition.** D1 = include stands only if the 69-origin re-run reproduces the
35-origin picture. It flips to **exclude**, and the live model reverts to raw ETS, if any
of these hold:
- median max R-hat across the 69 fits exceeds 1.10, or the 2023-onward median exceeds 1.12;
- winter-h3 ICB gm WIS vs raw ETS moves from the 35-origin figure (+23.5%) by more than
  10 pp, in either direction;
- 90% ICB coverage (all months) falls outside [0.85, 0.95] at any horizon;
- the coherence gap exceeds 1% at region or England.
Divergence within the measured seed noise (median quantile shift 2.2% of 50% width) is not
a flip.

**(b) Expected CONF behaviour**, stated before unsealing, so that a pass on a favourable
split means something:
- 90% ICB coverage inside [0.85, 0.95] at every horizon;
- 50% coverage **over**-covering at h3-h6, in 0.55-0.70, per the DEV defect;
- coherence gap under 1% at region and England;
- winter-h3 ICB WIS within ±8% of raw ETS — the DEV outside-COVID interval was ±7%, so
  anything inside that is *indistinguishable at this power*, **not** *as accurate as ETS*;
- median-exceedance share above 0.5 at h3-h6, per the diagnosed admissions drift.

**(c) Ship rule.** M2f-r4 ships as the live model unless, on CONF: 90% ICB coverage falls
outside [0.85, 0.95] at any horizon in 3-6; **or** the coherence gap exceeds 1% at region
or England; **or** winter-h3 ICB WIS is worse than raw ETS by more than 10% with the
interval excluding zero. Any of those reverts the live forecast to raw ETS, with its
failing upper tail (PIT top bin 1.90x) stated as a known limitation.

## How (a) is applied: details fixed before any fit

1. **R-hat.**
   - Each fit's max R-hat follows `m2.diagnostics`' definition.
   - "Across the 69 fits" is the median of the 69 values.
   - "2023-onward" means the 12 fits with origins in 2023, since DEV ends at 2023-12.
2. **Winter-h3 ICB gm WIS against raw ETS.** This is the computation behind the +23.5% figure (`results/E-ensemble/covid_split_verification.md`, `stage_e_ensemble.compare`), extended from the 35 ladder origins to all 69 DEV origins.
   - Target months are December to March, at h = 3, at ICB level, as-of.
   - Scoring is Stage E's `score`: the latest revised ICB totals, with embargoed rows dropped.
   - Raw ETS is `data/processed/stage_e/comparator_b1.parquet`, the file behind +23.5%. It covers all 78 origins from 2017-07 to 2023-12.
   - Each target gets a paired bootstrap over ICBs (1,000 resamples, seed 0), and the gm a joint bootstrap.
   - "Moves by more than 10 pp" is tested on the point estimate: |gm₆₉ − 23.5| > 10.
3. **90% ICB coverage (all months).** Pooled over ICBs and the three targets, per horizon h1–6, over all 69 origins, on the rows Stage E's `score` keeps. The band is inclusive: coverage of exactly 0.85 or 0.95 is inside.
4. **Coherence gap.** The Stage F definition, as the E-ensemble rule applied it: the mean over rows of |aggregate median − sum of its children's medians| ÷ aggregate median. Region's children are ICBs; England's are regions. All months are included. The maximum is reported alongside but is not used.
5. **The seed-noise clause** is applied in two places:
   - **The 35 committed origins.** The refits of these origins are compared with the `b77430e` forecasts using the seed-stability statistic. A divergence whose median is within 2.2% of the 50% width is not a flip. Bit-identity is expected, as found at 2023-04 on 2026-09-11 and again on 2026-09-12.
   - **Threshold crossings.** A crossing smaller than that statistic's measured between-seed difference is reported as within seed noise and is not a flip. For M2f-r4 (`5271eb2`), 90% coverage moved by at most 1.0 pp, pooled per target; gm WIS by 0.2 pp.
   - R-hat and the coherence gap have no measured seed-noise figure, so their thresholds apply as written.
6. **Verdict.** D1 INCLUDE if none of the four conditions holds after item 5; otherwise D1 EXCLUDE. It is written as one line in `results/E-m2f-69/stop_m2f_freeze.txt`.

The 35-origin picture itself passes all four conditions:

| Condition | 35-origin value | Limit |
|---|---|---|
| Median max R-hat | 1.079 | ≤ 1.10 |
| 2023 median R-hat | 1.065 | ≤ 1.12 |
| ICB 90% coverage, all months, h1–h6 | 0.900, 0.901, 0.923, 0.900, 0.896, 0.891 | [0.85, 0.95] |
| Mean coherence gap, region / England | 0.12% / 0.06% | < 1% |

The region maximum is 0.97%. Sources: `data/processed/stage_e/diagnostics_m2f_r4.csv` and `results/E-ensemble/ensemble_coverage.csv` / `ensemble_coherence.csv`.

## DEV-consistency note on (b) and (c) (written before the run; the texts above are unchanged)

On DEV outside COVID, over the 35 origins, M2f-r4's ICB 90% coverage at h3–h6 is 0.936, 0.942, 0.932 and **0.963** (`ensemble_coverage.csv`). h6 is above 0.95.

CONF is a calm period. If it behaves like DEV's calm periods:
- (b)'s first expectation fails at h6;
- (c)'s coverage clause reverts the live model to raw ETS for **over**-coverage, the less dangerous direction.

Raw ETS's calm-period ICB coverage is inside the band at every horizon (0.891–0.922), but its upper tail fails (PIT top bin 1.90×, `results/E-pit/pit_findings.md`). Step 3 reports the 69-origin outside-COVID figures, which will update this.

Whether (c)'s coverage clause should stay two-sided is Ellie's decision, to be taken before the tag. A change made then is DEV-informed, not CONF-informed.

The other factual statements in (b) and (c) match the committed results:
- the DEV outside-COVID WIS interval is [−7.6, +6.3];
- M2f-r4's outside-COVID ICB 50% coverage at h3–h6 is 0.603, 0.595, 0.585 and 0.646;
- raw ETS's PIT top bin is 1.90×.
