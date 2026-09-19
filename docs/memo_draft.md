# Winter demand outlook — <ICB name>, Dec 2026–Mar 2027 (DRAFT)

*Corrected 2026-09-19 against the confirmatory run of 2026-09-15: the admissions ranges
are wider than nominal, not narrower, and the development-window coverage figures are
restated from `results/D-calibration/coverage_by_horizon_year.csv` and the D5 amendment.*

*One page, for the winter-planning lead. Figures are ranges, not points. Draft of
2026-09-13, revised for the live forecasting model chosen on 2026-09-12. The numbers are
filled from the 8 October 2026 release (September data), the first release whose forecasts
cover December to March.*

**Bottom line.** <One sentence: expected emergency admissions via A&E against last winter,
with the 90% range.> The admissions ranges come straight from the forecasting model and are
**wider than they need to be**: on the sealed 2024–25 test window they held the outturn
97–98% of the time where 90% is intended. Their misses are lopsided — on the development
window outturns fell above the range 6.7% of the time against 5% expected — so read a
range as cautious overall but slightly more likely to be exceeded than undershot (see
"How much to trust it"). The bed-occupancy figures below are **illustrative only**, because the method that
turns admissions into occupancy failed its pre-registered accuracy check.

**What we forecast.**
| | Dec | Jan | Feb | Mar |
|---|---|---|---|---|
| Emergency admissions via A&E (median, 90% range) | | | | |
| P(G&A occupancy > 92%) — *illustrative, lower bound* | | | | |
| Escalation beds to bring P below 20% — *illustrative* | | | | |

**What is driving it.** <Three bullets: trend against last winter; seasonal profile; anything
trust-specific, such as a merger, reclassification or a missing return.>

**What could change it.** <Scenario levers, one line each with direction and rough size:
early or severe flu, a cold snap, industrial action.>

**How much to trust it.**
- **Admissions, 1 to 6 months ahead.** We tested the method on 2018–2023, using only the data
  as they were first published. Leaving out the COVID months (March 2020 to June 2021), the
  90% range held the ICB's actual admissions 89–93% of the time, depending on how far ahead
  (91% pooled). The misses fall mostly on the high side: actuals landed above the range 6.7%
  of the time, where a well-set range would give 5%. Including the COVID months, the range
  held 78–81% of the time; nothing could have anticipated them. On the sealed 2024–25 window
  the same ranges held 97–98% of the time: wider than intended, in the cautious direction.
- **Admissions, winter.** For winter months three months ahead, the central forecast is
  typically about 3% off for an ICB, and the 90% range is about ±11% wide (2018–2023,
  COVID months excluded).
- **Why the ranges are not adjusted.** A correction step would need recent forecast errors
  from 2024 to 2026, which are being held back for an independent test of the method. This
  forecast is therefore issued as the model gives it, and its lean is stated here instead.
- **Occupancy.** Working out occupancy from forecast admissions missed the published bed
  occupancy by a median of 8.7 percentage points, against a pre-registered tolerance of 5.
  Breach probabilities made this way did worse than always quoting the breach rate seen over
  the same quarters. In an exploratory check that was not pre-registered, a hospital's own
  latest published occupancy predicted it far better, missing by a median of about 2.4
  points.
- **So:** use the admissions forecast for planning, and treat the bed rows as a sketch.
- **Lower bound.** In the 2018 and 2019 tests, the trust-level admissions forecasts behind
  the breach probabilities held their 90% range less than 87% of the time at every horizon
  (91–96% since 2021). Those early misses are the reason the breach probabilities are
  reported as a lower bound: where the trust-level ranges were too narrow, the risk of
  exceeding the line is understated rather than overstated.

**About the 92% line.** Treat it as a planning convention, not a safety limit.
- The familiar 85% figure comes from a stochastic simulation model of hospital bed use
  (Bagust, Place & Posnett, *BMJ* 1999;319:155–8, doi:10.1136/bmj.319.7203.155), not from
  observed harm.
- NICE's 2018 review graded the evidence linking occupancy to outcomes "very low" for all
  outcomes. It recommends planning capacity to minimise the risks of occupancy above 90%
  (NG94, evidence review chapter 39, recommendation 22).
- In England, higher occupancy is associated with worse A&E performance, more steeply above
  90% (Friebel & Juarez, *Health Policy* 2020;124:1182–91, doi:10.1016/j.healthpol.2020.07.008).
- 92% is used here because NHS England's *2023/24 priorities and operational planning
  guidance* set the objective to "reduce adult general and acute (G&A) bed occupancy to 92%
  or below". The 2025/26 guidance gives no occupancy figure.
- P(occupancy > 92%) is an aid to decisions, to be weighed against the cost-loss ratios listed
  under Assumptions, and the evidence behind it is weak. It is not a calibrated risk.

**Assumptions.** Admissions forecast: exponential smoothing (ETS), fitted to each ICB's
monthly series as published by the release date, with the model's own 90% ranges and no
correction step. Region and England figures are fitted separately to summed ICB series and
are not forced to add up; on average their medians differ from the sum of their ICBs'
medians by under 1%, which is checked on every run. Bed stock: KH03 G&A beds available,
latest published quarter. Occupancy mapping (illustrative): occupied bed-days per A&E
admission, per trust, from its last eight published quarters, applied to trust-level
admissions forecasts made by the same ETS method. Cost-loss ratios 0.1, 0.25 and 0.5.

**Next update.** 12 November 2026 (October data), plus one working day.
