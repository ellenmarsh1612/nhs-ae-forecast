# results/F-reconciliation-G1

Stage F re-run on DEV with guard G1 (pre-flight item P2; amendment "Guard G1 registered", 2026-09-13), run 2026-09-13 at commit `7ac8f3d`. **Exploratory.** H3's confirmatory test is Stage H on CONF; this re-run changes no registered decision.

Same base forecasts, first-release tables, scoring and H3 rule as `results/F-reconciliation/` (read, never rewritten). What changes: a failed base forecast (all nine quantiles exactly zero while the series' last as-of month at that level is positive) is kept out of the pooled conformal sets, the MinT error covariance and the reconciliation inputs (a failed provider joins its ICB's rest node; a failed aggregate drops out of S), and is issued as produced. Failed forecasts are scored as issued (real WIS, not covered); every table is also given with them dropped.

## Failed forecasts per base model and level

| model | level | under_g1 | forecasts | all_zero | all_zero_last_zero | all_zero_no_history | failed | failed_dev_origins | failed_origins | failed_scored_base | failed_scored_mint |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ETS | provider | True | 328932 | 324 | 6 | 0 | 318 | 318 | 2020-05 | 310 | 310 |
| ETS | icb | True | 51570 | 194 | 0 | 0 | 194 | 194 | 2020-05 | 188 | 188 |
| ETS | region | True | 9828 | 45 | 0 | 0 | 45 | 45 | 2020-05 | 45 | 45 |
| ETS | england | True | 1404 | 7 | 0 | 0 | 7 | 7 | 2020-05 | 7 | 7 |
| STL+ARIMA | provider | True | 328932 | 229 | 113 | 0 | 116 | 116 | 2018-04, 2018-08, 2018-12, 2020-05, 2020-12, 2021-01, 2021-02, 2021-03, 2021-04, 2021-05, 2021-06, 2021-07, 2021-08, 2021-09, 2021-10, 2021-11, 2021-12, 2022-01 | 105 | 105 |
| STL+ARIMA | icb | True | 51570 | 5 | 1 | 0 | 4 | 3 | 2018-01, 2021-02, 2021-03, 2021-04 | 0 | 0 |
| STL+ARIMA | region | True | 9828 | 0 | 0 | 0 | 0 | 0 |  | 0 | 0 |
| STL+ARIMA | england | True | 1404 | 0 | 0 | 0 | 0 | 0 |  | 0 | 0 |
| M1 | provider | True | 328932 | 6 | 6 | 0 | 0 | 0 |  | 0 | 0 |
| M1 | icb | True | 51570 | 0 | 0 | 0 | 0 | 0 |  | 0 | 0 |
| M1 | region | True | 9828 | 0 | 0 | 0 | 0 | 0 |  | 0 | 0 |
| M1 | england | True | 1404 | 0 | 0 | 0 | 0 | 0 |  | 0 | 0 |

## H3 verdicts

| base | original | G1, as issued | G1, failed dropped |
|---|---|---|---|
| ETS | fails | fails | fails |
| STL+ARIMA | fails | fails | fails |
| M1 | fails | fails | fails |

## H3: winter h=3 WIS, reconciled against calibrated base (negative = reconciliation helps)

| base | level | original (no G1) | G1, as issued | G1, failed dropped |
|---|---|---|---|---|
| ETS | england | -100.0% [-100.0%, -100.0%] | -13.4% [-13.4%, -13.4%] | -13.4% [-13.4%, -13.4%] |
| ETS | icb | -53.1% [-94.7%, +8.0%] | +9.0% [+7.1%, +10.7%] | +9.0% [+7.1%, +10.7%] |
| ETS | provider | +3449.1% [+1135.6%, +6692.3%] | +5.4% [+4.5%, +6.3%] | +5.4% [+4.5%, +6.3%] |
| ETS | region | -98.3% [-100.0%, -95.3%] | +4.6% [+2.6%, +6.2%] | +4.6% [+2.6%, +6.2%] |
| M1 | england | -2.9% [-2.9%, -2.9%] | -2.9% [-2.9%, -2.9%] | -2.9% [-2.9%, -2.9%] |
| M1 | icb | +11.1% [+10.2%, +12.0%] | +11.1% [+10.2%, +12.0%] | +11.1% [+10.2%, +12.0%] |
| M1 | provider | +11.6% [+8.8%, +14.8%] | +11.6% [+8.8%, +14.8%] | +11.6% [+8.8%, +14.8%] |
| M1 | region | +2.8% [+1.6%, +4.0%] | +2.8% [+1.6%, +4.0%] | +2.8% [+1.6%, +4.0%] |
| STL+ARIMA | england | -7.5% [-7.5%, -7.5%] | -7.7% [-7.7%, -7.7%] | -7.7% [-7.7%, -7.7%] |
| STL+ARIMA | icb | +0.3% [-1.5%, +1.9%] | +0.0% [-1.7%, +1.6%] | +0.0% [-1.7%, +1.6%] |
| STL+ARIMA | provider | +2.7% [+1.1%, +4.2%] | +2.6% [+1.0%, +4.1%] | +2.6% [+1.0%, +4.1%] |
| STL+ARIMA | region | -2.7% [-4.1%, -1.1%] | -2.9% [-4.3%, -1.3%] | -2.9% [-4.3%, -1.3%] |

## Calibrated forecasts with a 97.5% quantile above ten times the median

| base | level | cal_q975_over_10x_median original | cal_q975_over_10x_median G1 |
|---|---|---|---|
| ETS | provider | 2594 | 2230 |
| ETS | icb | 2702 | 38 |
| ETS | region | 695 | 9 |
| ETS | england | 113 | 27 |
| STL+ARIMA | provider | 3393 | 3389 |
| STL+ARIMA | icb | 0 | 0 |
| STL+ARIMA | region | 0 | 0 |
| STL+ARIMA | england | 0 | 0 |
| M1 | provider | 585 | 585 |
| M1 | icb | 0 | 0 |
| M1 | region | 0 | 0 |
| M1 | england | 0 | 0 |

## What G1 leaves

G1 as registered catches a forecast only when all nine quantiles are zero. A forecast whose median is zero but whose upper quantiles are not still enters the pools, and its inner intervals (50%, 80%) score about the log of the outturn, as a failed forecast would. DEV origins; `winter_h3`: flagged forecasts that fall in a winter-h3 cell, the cells H3 scores; `base_median_zero_not_failed`: base forecasts with a zero median, some positive quantile and a positive last observed month.

| base | level | cal_q975_over_10x_median | winter_h3 | window | base_median_zero_not_failed | their_origins |
|---|---|---|---|---|---|---|
| ETS | provider | 2230 | 90 | 2018-04..2023-12 | 290 | 2018-04, 2018-05, 2018-07, 2018-08, 2018-10, 2018-11 |
| ETS | icb | 38 | 0 | 2020-05..2020-05 | 32 | 2019-03, 2020-05 |
| ETS | region | 9 | 0 | 2020-05..2020-05 | 8 | 2020-05 |
| ETS | england | 27 | 4 | 2020-05..2021-07 | 2 | 2020-05 |
| STL+ARIMA | provider | 3389 | 192 | 2018-04..2023-12 | 860 | 2018-04, 2018-05, 2018-06, 2018-07, 2018-08, 2018-09 |
| STL+ARIMA | icb | 0 | 0 |  | 27 | 2020-10, 2020-11, 2020-12, 2021-01, 2021-02, 2021-03 |
| STL+ARIMA | region | 0 | 0 |  | 0 |  |
| STL+ARIMA | england | 0 | 0 |  | 0 |  |
| M1 | provider | 585 | 64 | 2018-08..2023-01 | 14 | 2020-05, 2020-09, 2020-10, 2020-11, 2020-12, 2021-01 |
| M1 | icb | 0 | 0 |  | 0 |  |
| M1 | region | 0 | 0 |  | 0 |  |
| M1 | england | 0 | 0 |  | 0 |  |

D4 = (a) registered G1 alone, with no cap and no minimum pool, so that no calibration method is invented after seeing DEV results; this run changes nothing about that.

## F2 (35 ladder origins), failed forecasts as issued

| model | level | coh_gap_mean | wis_rel_m1 | cov90 | cov50 | cov90_out | n |
|---|---|---|---|---|---|---|---|
| ETS + pooled | icb | 3.98% | +8.0% | 0.89 | 0.55 | 0.93 | 21708 |
| ETS + pooled | region | 0.58% | +2.1% | 0.89 | 0.56 | 0.92 | 4221 |
| ETS + pooled | england | 0.30% | -2.8% | 0.90 | 0.58 | 0.93 | 603 |
| ETS + pooled + MinT | icb | 3.46% | +14.0% | 0.89 | 0.56 | 0.93 | 21708 |
| ETS + pooled + MinT | region | 0.23% | +5.1% | 0.93 | 0.62 | 0.99 | 4221 |
| ETS + pooled + MinT | england | 0.23% | -23.2% | 0.94 | 0.68 | 1.00 | 603 |
| M1 + pooled | icb | 2.98% | +0.0% | 0.91 | 0.55 | 0.94 | 21708 |
| M1 + pooled | region | 3.58% | +0.0% | 0.87 | 0.51 | 0.91 | 4221 |
| M1 + pooled | england | 3.61% | +0.0% | 0.86 | 0.54 | 0.90 | 525 |
| M1 + pooled + MinT | icb | 0.49% | +23.1% | 0.90 | 0.46 | 0.93 | 21708 |
| M1 + pooled + MinT | region | 0.03% | +13.9% | 0.94 | 0.55 | 0.99 | 4221 |
| M1 + pooled + MinT | england | 0.02% | -14.4% | 0.94 | 0.57 | 1.00 | 525 |
| M2f-r4 (phase 1b) | icb |  | +4.7% | 0.90 | 0.59 | 0.93 | 21708 |
| M2f-r4 (phase 1b) | region | 0.12% | -2.4% | 0.88 | 0.56 | 0.90 | 4221 |
| M2f-r4 (phase 1b) | england | 0.06% | -26.7% | 0.88 | 0.56 | 0.90 | 603 |
| M2 frozen (m2d_corr) | icb |  | -4.5% | 0.86 | 0.55 | 0.96 | 21708 |
| M2 frozen (m2d_corr) | region | 0.18% | -13.4% | 0.80 | 0.47 | 0.91 | 4221 |
| M2 frozen (m2d_corr) | england | 0.07% | -37.4% | 0.74 | 0.44 | 0.85 | 603 |

## F2, failed forecasts dropped

| model | level | coh_gap_mean | wis_rel_m1 | cov90 | cov50 | cov90_out | n |
|---|---|---|---|---|---|---|---|
| ETS + pooled | icb | 3.98% | +8.0% | 0.89 | 0.55 | 0.93 | 21708 |
| ETS + pooled | region | 0.58% | +2.1% | 0.89 | 0.56 | 0.92 | 4221 |
| ETS + pooled | england | 0.30% | -2.8% | 0.90 | 0.58 | 0.93 | 603 |
| ETS + pooled + MinT | icb | 3.46% | +14.0% | 0.89 | 0.56 | 0.93 | 21708 |
| ETS + pooled + MinT | region | 0.23% | +5.1% | 0.93 | 0.62 | 0.99 | 4221 |
| ETS + pooled + MinT | england | 0.23% | -23.2% | 0.94 | 0.68 | 1.00 | 603 |
| M1 + pooled | icb | 2.98% | +0.0% | 0.91 | 0.55 | 0.94 | 21708 |
| M1 + pooled | region | 3.58% | +0.0% | 0.87 | 0.51 | 0.91 | 4221 |
| M1 + pooled | england | 3.61% | +0.0% | 0.86 | 0.54 | 0.90 | 525 |
| M1 + pooled + MinT | icb | 0.49% | +23.1% | 0.90 | 0.46 | 0.93 | 21708 |
| M1 + pooled + MinT | region | 0.03% | +13.9% | 0.94 | 0.55 | 0.99 | 4221 |
| M1 + pooled + MinT | england | 0.02% | -14.4% | 0.94 | 0.57 | 1.00 | 525 |
| M2f-r4 (phase 1b) | icb |  | +4.7% | 0.90 | 0.59 | 0.93 | 21708 |
| M2f-r4 (phase 1b) | region | 0.12% | -2.4% | 0.88 | 0.56 | 0.90 | 4221 |
| M2f-r4 (phase 1b) | england | 0.06% | -26.7% | 0.88 | 0.56 | 0.90 | 603 |
| M2 frozen (m2d_corr) | icb |  | -4.5% | 0.86 | 0.55 | 0.96 | 21708 |
| M2 frozen (m2d_corr) | region | 0.18% | -13.4% | 0.80 | 0.47 | 0.91 | 4221 |
| M2 frozen (m2d_corr) | england | 0.07% | -37.4% | 0.74 | 0.44 | 0.85 | 603 |

## Files

- `h3_results.csv`, `coherence_vs_calibration.csv`: as in `results/F-reconciliation/`, with a `variant` column
- `failed_counts.csv`, `calibration_blowups.csv`, `residual_blowups.csv`
- `fig_f2_coverage_as_issued.png`, `fig_f2_coverage_failed_dropped.png`
- `stop7.txt`

