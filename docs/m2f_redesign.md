# M2f redesign (phase 1b; separate from the frozen M2)

> **The model described here did not go forward.** D1 came out **exclude** on 2026-09-12
> (`results/E-m2f-69/`): on all 69 development origins M2f-r4's winter-h3 ICB WIS against
> raw ETS moved from +23.5% to +12.4%, past the pre-committed limit, so M2f-r4 was never
> frozen or tagged, was removed from the confirmatory comparison, and runs only as an
> unpublished shadow of the live forecast. Sentences here calling it "the most defensible
> M2 so far" or the candidate for Stage F describe the position before that decision.

Ellie asked (2026-09-10) for M2f to be redesigned as a separate piece of work after M2 is
frozen at M2d with post-fit correlated innovations (`m2d_corr`). Nothing here changes the
frozen M2. Every attempt below is a development fit: none is scored, and the design that
survives will be registered in the pre-registration's amendment log before any backtest.

## The problem

M2f's purpose is coherence by construction: ICB forecast errors that move together as the
data say, so that region and England forecasts built from summed ICB draws are calibrated.
Summed M2d draws (independent ICB walks) cover only 0.70 at region level and 0.40 at England
level (90% intervals). The registered M2f (a national walk G plus ICB walks u) failed on two
identification problems:

1. **G versus the ICB walks.** Any common path can move from G into every u. Fixed by
   centring the ICB walks across ICBs each month.
2. **G versus the shared Fourier seasonality.** G is itself a common time path, so it can carry
   the seasonal pattern as well as the Fourier term. Chains split between the two (R-hat 4.0
   at origin 2021-10).

## Attempt 1 — sparse-jump national walk (Cauchy innovations): failed

Idea: give G Cauchy innovations with a small scale (σ_G ~ Gamma(4, 400), mean 0.01). Seasonality
needs a move every month, which a sparse prior penalises heavily; COVID needs a few large jumps,
which it allows cheaply.

| Origin | Seconds | Max R-hat | Min ESS | Median monthly move of G (Type 1) | Largest moves |
|---|---|---|---|---|---|
| 2018-04 | 5,176 | 2.56 | 5 | 0.030 | 0.16–0.19 |
| 2021-10 | 12,389 | 2.55 | 5 | 0.053 | 0.22–0.34 |

G did not become sparse: its typical monthly move is 3–5%, so it still carries seasonal wiggle.
The Cauchy tails also made trajectories very long (1.4–3.4 hours per fit, against about 2
minutes for M2d). Rejected.

## Attempt 2 — two-stage: seasonality first, then G + ICB walks

Estimate each series' seasonal profile at the origin, before and outside the walk model:
Fourier regression on log counts, pooled over ICBs, with the COVID window excluded. Remove it,
then fit G + centred u on the deseasonalised log counts with no seasonal term in the joint
model. The confound then cannot arise, because seasonality is not a free parameter of the
model that also contains G. Forecasts add the seasonal profile back. Seasonal-estimation
uncertainty is ignored in the first version; a parametric bootstrap over the Fourier
coefficients is the refinement if calibration needs it.

What would show it works: R-hat < 1.01 and ESS > 400 at the two diagnostic origins above,
fits of a few minutes, and region/England coverage of summed draws in 0.87–0.93 on the
35 ladder origins.

### Attempt 2 results (development fits, 2026-09-11)

| Version | 2018-04 R-hat / min ESS | 2021-10 R-hat / min ESS | Seconds per fit |
|---|---|---|---|
| 2a: two-stage seasonality, 36 ICB walks centred after the fact | 2.92 / 5 | 2.75 / 5 | 30–54 |
| **2b: two-stage seasonality, n − 1 zero-sum walks on a Helmert basis** | **1.027 / 96** | **1.069 / 47** | **29–52** |

2a still had a direction the data never saw: the common part of the 36 raw ICB walks, which
centring removes from the likelihood. The sampler wandered along it. 2b builds the ICB walks
inside the zero-sum subspace, so every sampled direction is informed by data. Its remaining
weak spot is the all-types dispersion (the noise-versus-walk trade-off M2d also has). 2b is
registered as M2f-r2 (amendment of 2026-09-11) and backtested on the 35 ladder origins.

## Attempt 3 — national factor inside the COVID window only (fallback, not needed)

G is fixed at zero outside 2020-03 to 2021-06, which identifies a national COVID shock and
nothing else. Outside the window, coherence comes from post-fit correlated innovations, as in
`m2d_corr`. This is a hybrid of M2f and the frozen M2, to be used if attempt 2 fails.

## M2f-r2 backtest (35 DEV ladder origins, as-of; 2026-09-11)

| Summed ICB draws | Region 90% / 50% coverage | England 90% / 50% coverage | Region / England winter-h3 WIS |
|---|---|---|---|
| Frozen M2 (`m2d_corr`) | 0.80 / 0.47 | 0.74 / 0.44 | 4,817 / 31,921 |
| **M2f-r2** | **0.92** / 0.68 | **0.92** / 0.69 | 5,349 / 36,058 |

By horizon, M2f-r2's England 90% coverage is 0.97, 0.92, 0.93, 0.89, 0.92, 0.91 (h1 to h6).
At ICB level: winter-h3 WIS +27.2% against ETS (`m2d_corr`: +12.7%), worst assessable cell
9.5 pp. Sampling: median R-hat 1.083 (90th percentile 1.148, worst 1.287), median ESS 42, no
divergences, 66 s per fit. The worst parameter is the dispersion κ in every fit (all-types
27/35, Type 1 8/35).

**Reading.**
- **Coherence by construction works for its purpose.** Region and England 90% intervals land
  at 0.92, inside the 0.87–0.93 band, where post-fit correlation reached 0.74–0.80.
- **It costs sharpness.** 50% coverage of 0.68–0.69 means intervals too wide in the middle,
  aggregate WIS is 11–13% worse than `m2d_corr`, and ICB-level WIS is worse too (fixed
  three-harmonic seasonality is a blunter instrument than M2d's jointly estimated one).
- **Likely cause** [inference]: the national walk moves about 4.6% a month, partly deterministic
  calendar structure that three harmonics miss (short Februaries, Easter), which then enters
  the forecast as random-walk noise. It also competes with κ for the same variance, which is
  what the sampler struggles with.

**Next refinement, if pursued** (to be registered before it is tested): full month-of-year
effects in stage 1 (eleven dummies instead of three harmonics), plus a days-in-month offset. That
takes deterministic calendar structure out of the national walk, which should narrow the
aggregate intervals towards 50% coverage near 0.5 and ease the κ trade-off. This remains a
phase-1b model; the frozen M2 is unaffected.

## M2f-r3: calendar-aware stage 1 (month-of-year effects + days-in-month offset; 2026-09-11)

Registered before any fit (amendment of 2026-09-11). Prior gate 108/108 at all three origins.
Backtest on the 35 ladder origins:

| | ICB winter-h3 WIS vs ETS | Region 90% / 50% | England 90% / 50% | England winter-h3 WIS |
|---|---|---|---|---|
| Frozen M2 (`m2d_corr`) | +12.7% | 0.80 / 0.47 | 0.74 / 0.44 | 31,921 |
| M2f-r2 | +27.2% | 0.92 / 0.68 | 0.92 / 0.69 | 36,058 |
| **M2f-r3** | **+3.8%** | 0.78 / 0.48 | 0.79 / 0.49 | **29,620** |

Sampling: median R-hat 1.080 (worst 1.178), median ESS 45, no divergences, 69 s per fit; κ is
still the worst-mixing parameter (all-types 30/35).

**Against the registered expectations.** Aggregate 50% coverage moved from 0.68 to 0.48–0.49,
as expected, and WIS fell below M2f-r2's everywhere (it is the lowest of all M2 variants at ICB,
region and England level). But 90% coverage fell to 0.78–0.79, outside 0.87–0.93: that
expectation is **not met**.

**Exploratory split by the COVID window** (not registered):

| 90% / 50% coverage, summed draws | Frozen M2 | M2f-r2 | M2f-r3 |
|---|---|---|---|
| England, outside COVID | 0.85 / 0.52 | 1.00 / 0.84 | 0.97 / 0.63 |
| Region, outside COVID | 0.91 / 0.56 | 1.00 / 0.82 | 0.96 / 0.61 |
| England, inside COVID | 0.49 / 0.24 | 0.73 / 0.32 | 0.31 / 0.14 |
| Region, inside COVID | 0.53 / 0.24 | 0.73 / 0.33 | 0.34 / 0.13 |

M2f-r3's pooled 0.78 is intervals too wide in calm periods (0.96–0.97) plus far too narrow ones
through the collapse (0.31–0.34). That is M2d's ICB-level pattern again, now in the national walk,
whose volatility is estimated over a history that includes COVID. In calm periods, the regime the
live forecast operates in, the frozen M2's aggregates are the closest to calibrated.

**What this establishes.**
- The calendar-aware first stage is a genuine accuracy gain: ICB-level WIS goes from +27% to
  +3.8% against ETS, better than any M2 rung including the frozen one. It is a candidate for
  any future M2 version.
- The national walk's tails are the remaining problem. The natural next test is M2d2's idea
  applied to the national walk only: a separate volatility inside the COVID window. That targets
  calm-period over-width; under-coverage through the collapse is largely unavoidable for forecasts
  made before it.

## M2f-r4: COVID-window volatility for the national walk only (2026-09-11)

Registered before any fit (amendment of 2026-09-11). Prior gate 108/108 at all three origins.
Sampling: median R-hat 1.079 (worst 1.217), median ESS 47, no divergences.

**Against the registered expectations (all months, 35 ladder origins):**

| Expectation | Result | Verdict |
|---|---|---|
| Aggregate 90% coverage back inside 0.87–0.93 | England 0.88 (h1–h6: 0.87 0.87 0.95 0.87 0.84 0.90), region 0.88 (0.87–0.92); 50% coverage 0.56 | **met** |
| Calm-period over-width reduced | outside COVID 90% / 50%: England 0.90 / 0.52, region 0.90 / 0.52 (M2f-r3: 0.97 / 0.63, 0.96 / 0.61) | **met** |
| Winter-h3 WIS no worse than M2f-r3 by more than 3.0% | aggregates +15–19% (England 35,122 against 29,620); ICB +23.5% against ETS (M2f-r3 +3.8%) | **not met** |

**Exploratory split by the COVID window** (winter-h3 WIS; coverage in the table above):

| | ICB vs ETS, outside / inside | Region, outside / inside | England, outside / inside |
|---|---|---|---|
| Frozen M2 (`m2d_corr`) | +13.4% / +10.6% | 4,256 / 7,062 | 28,149 / 47,009 |
| M2f-r3 | +0.4% / +13.0% | 3,697 / 7,795 | 23,627 / 53,592 |
| **M2f-r4** | **−0.1%** / +88.6% | 3,871 / 10,457 | 25,676 / 72,909 |

*Correction (2026-09-11).* The inside-COVID ICB figures are replaced by the committed
recomputation (`results/E-ensemble/covid_split_verification.md` and `.csv`, commit `9e2b0cc`).
- **The original inside figures cannot be reproduced.** They were +12.4%, +14.9% and +91.7%.
  None of five alternative computations reproduces them (`results/E-ensemble/inside_variants.py`),
  and because no artefact was committed with them, the cause cannot be recovered. With the 95%
  intervals, M2f-r4's inside figure is +88.6% [+73.4, +105.9].
- **The outside figures are unchanged, because they reproduce** to within 0.07 pp. The
  recomputed values are +13.4%, +0.5% and −0.1% [−7.6, +6.3].
- **The inside slice has only two winter-h3 origins,** 2020-10 and 2020-12.
- **The region and England WIS columns were not part of that verification** and still have no
  artefact behind them.

**Reading.**
- **In calm periods M2f-r4 is the most defensible M2 so far.** It is level with ETS at ICB level.
  Its region and England intervals are calibrated at both 90% (0.90) and 50% (0.52), which no
  other variant achieves. Its aggregate WIS is 5–9% above M2f-r3's, which buys that
  calibration: M2f-r3 over-covers.
- **Inside the COVID window it pays heavily in WIS.** Forecasts made during the crisis assume the
  crisis volatility persists, so they are very wide: good coverage (0.83 at 90%, up from 0.31), poor
  WIS. This is M2d2's failure mode, now confined to the national walk.
- **Operational note.** Nothing flags a future shock, so in live use M2f-r4 always forecasts with
  its calm-period national volatility: the regime in which it is calibrated. Like every model
  here, it has no mechanism to anticipate a new shock.
- **Status.** M2f-r4 is the candidate hierarchical model for phase 1b and for Stage F's F2
  comparison (coherence by construction against post-hoc reconciliation). The frozen M2 is
  unchanged.
