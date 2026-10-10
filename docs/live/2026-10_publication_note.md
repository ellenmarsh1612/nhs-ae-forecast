# Winter A&E outlook for England, December 2026 to March 2027

*First live forecast. Made on 8 October 2026 from NHS England's September 2026 release. DRAFT, not yet published.*

**Bottom line.** Each winter month is forecast to be within about 3% of the same month last
winter, on all three measures. Emergency admissions via A&E are forecast at about 404,000 in
January 2027 (90% range 362,000 to 451,000), against 402,000 in January 2026. The ranges are
wide. When this model has missed in the past, the outturn has more often come in **above** the
range than below it, so plan against the upper end, not the central figure.

## The forecast

England total. Central figure (median), 90% range, and the same month last winter.

**Emergency admissions via A&E**

| Month | Central | 90% range | Same month last winter | Change |
|---|---|---|---|---|
| Dec 2026 | 413,000 | 377,000 – 453,000 | 405,000 | +1.9% |
| Jan 2027 | 404,000 | 362,000 – 451,000 | 402,000 | +0.6% |
| Feb 2027 | 371,000 | 329,000 – 420,000 | 362,000 | +2.6% |
| Mar 2027 | 408,000 | 355,000 – 467,000 | 410,000 | −0.6% |

**A&E attendances, all types**

| Month | Central | 90% range | Same month last winter | Change |
|---|---|---|---|---|
| Dec 2026 | 2.30m | 1.94m – 2.72m | 2.24m | +2.8% |
| Jan 2027 | 2.22m | 1.82m – 2.70m | 2.24m | −0.8% |
| Feb 2027 | 2.09m | 1.68m – 2.61m | 2.04m | +2.3% |
| Mar 2027 | 2.35m | 1.83m – 3.00m | 2.35m | −0.2% |

**Type 1 (major) A&E attendances**

| Month | Central | 90% range | Same month last winter | Change |
|---|---|---|---|---|
| Dec 2026 | 1.45m | 1.26m – 1.67m | 1.41m | +2.9% |
| Jan 2027 | 1.39m | 1.18m – 1.64m | 1.41m | −0.9% |
| Feb 2027 | 1.31m | 1.09m – 1.58m | 1.27m | +2.9% |
| Mar 2027 | 1.47m | 1.19m – 1.80m | 1.45m | +1.1% |

The same forecast for each of England's 36 integrated care boards (ICBs) and 7 regions, with
nine quantiles per month from October 2026 to March 2027, is in
`forecasts/2026-10/ets/quantiles.parquet`. "Last winter" means the figures as published on
8 October 2026; they can still be revised.

## How far to trust it

The model is exponential smoothing (ETS), fitted to each series separately, with no further
calibration step. It was chosen under a rule written down before testing, and it was not
changed after the test.

- **The ranges are usually wide enough.** In back-tests from 2017 to 2023 (COVID months
  excluded, ICB level), the 90% range contained the outturn 89–93% of the time, depending on
  how far ahead. In a sealed test window (January 2024 to September 2025, scored once), it
  contained the outturn 97–98% of the time. That is wider than it needs to be in calm
  periods.
- **But it leans low, and its misses are mostly high.** In the back-tests, 60% of outturns
  came in above the central figure rather than 50%. 6.7% of outturns landed above the 95th
  percentile, against 5% expected. Above the 97.5th percentile, the miss rate was 1.7 times
  what it should be.
- **It is not built for shocks.** Over all months including COVID, 90% coverage fell to
  78–81%. A severe flu season, a long cold spell or industrial action is not in the model.
- **The calibration evidence is at ICB level.** The England and regional ranges come from
  separate fits to the summed series, and are not checked separately here.

## What it is not

- **Not a bed forecast.** The repository also holds an occupancy-breach table, but that
  model failed its own validation (median error 8.7 points against a 5-point tolerance). It
  is labelled illustrative and is not part of this outlook.
- **Not adjusted after the fact.** The sealed test showed the ranges are on the wide side.
  Narrowing them in response would have meant tuning to the test, so they were left as
  fixed.

## Record and next steps

- **What was run:** code commit `3503f3d`, origin 2026-10, data snapshot 2026-10-08, trained
  to September 2026. All automatic pre-publication checks passed. Regional and England
  totals agree with the summed ICB forecasts to within 0.2%. The run details are in
  `forecasts/2026-10/ets/manifest.json`.
- **One deviation:** the September file was downloaded on 9 October, a day after release,
  because the automatic archiver failed. It was archived under the release date, as the
  method requires, and the true download time is recorded. This is pre-registration
  amendment 84.
- **Scoring:** October 2026 will be scored against NHS England's 12 November 2026 release.
  The winter months will be scored as each one is published.

## Sources

- **Forecast table:** England rows of `forecasts/2026-10/ets/quantiles.parquet`, at the 0.05,
  0.5 and 0.95 quantiles.
- **Last winter:** the as-of ICB panel for origin 2026-10, summed over ICBs (UNMAPPED and
  LEGACY excluded).
- **Back-test figures (69 DEV origins, outside COVID):** `docs/preregistration.md` §10 (the D5
  amendment) and `results/E-m2f-69/` (`exceedance_pooled_outside_69.csv`, `README.md`).
- **Sealed-window coverage:** `docs/confirmatory_results.md`, "The live model's own numbers",
  from `results/H-confirmatory/` at tag `conf-run-v1`.
- **Occupancy validation:** `BREACH_STATUS` in `src/nhs_ae/live.py`.
