# H3 on DEV (exploratory), run 2026-09-11 at `059a368`

Winter h=3 WIS of MinT-shrink reconciled forecasts relative to the calibrated base (negative = reconciliation helps); 95% bootstrap interval over series (1,000 resamples, targets pooled within a series). DEV origins 2018-04 to 2023-12, as-of, all months including COVID; the outside-COVID column is exploratory. H3 holds for a base if the ICB interval is entirely below zero and the provider point estimate is at most +2%. The confirmatory test is Stage H on CONF.

| base | level | n_series | rel | ci | rel_att_all | rel_att_type1 | rel_adm_via_ae | rel_outside_covid | H3 |
|---|---|---|---|---|---|---|---|---|---|
| ETS | provider | 232 | +3449.1% | [+1135.6%, +6692.3%] | +2431.0% | +3.5% | +1.5% | +7.4% | fails |
| ETS | icb | 36 | -53.1% | [-94.7%, +8.0%] | -53.2% | +2.7% | +5.1% | +14.7% | fails |
| ETS | region | 7 | -98.3% | [-100.0%, -95.3%] | -98.3% | -5.5% | +6.4% | +17.9% | fails |
| ETS | england | 1 | -100.0% | [-100.0%, -100.0%] | -100.0% | -35.2% | -3.9% | +19.2% | fails |
| STL+ARIMA | provider | 232 | +2.7% | [+1.1%, +4.2%] | +1.6% | +2.7% | +4.0% | +3.1% | fails |
| STL+ARIMA | icb | 36 | +0.3% | [-1.5%, +1.9%] | +1.4% | -2.7% | +5.0% | +1.7% | fails |
| STL+ARIMA | region | 7 | -2.7% | [-4.1%, -1.1%] | +1.1% | -9.2% | -1.4% | +4.3% | fails |
| STL+ARIMA | england | 1 | -7.5% | [-7.5%, -7.5%] | -3.2% | -16.1% | +0.7% | -2.2% | fails |
| M1 | provider | 240 | +11.6% | [+8.8%, +14.8%] | +9.2% | +15.1% | +24.4% | +13.8% | fails |
| M1 | icb | 36 | +11.1% | [+10.2%, +12.0%] | +14.6% | +3.9% | +16.3% | +8.4% | fails |
| M1 | region | 7 | +2.8% | [+1.6%, +4.0%] | +7.2% | -4.5% | +0.4% | -4.4% | fails |
| M1 | england | 1 | -2.9% | [-2.9%, -2.9%] | +0.4% | -8.4% | -5.1% | -13.9% | fails |

## The ETS rows are an artefact

At origin 2020-05 ETS forecasts exactly zero (every quantile) for many series at every level, after the April 2020 collapse. Those forecasts enter the pooled conformal sets. At aggregate levels the pools are tiny (England: at most 12 scores per horizon, so the 95% and 97.5% adjustments are the largest score), and one log-scale score of about 14 (with a zero forecast, the log of the outturn itself) inflates upper quantiles by a factor of up to about e^14, roughly 10^6, until it leaves the 12-origin window (corrected 2026-09-11; first version: 'about 13', 'e^13'). MinT then projects the inflated aggregate quantiles onto the providers. The other bases have no such rows at aggregate level. Calibrated forecasts with a 97.5% quantile above ten times the median:

| base | level | all_zero_base_rows | all_zero_origins | cal_q975_over_10x_median | share | window |
|---|---|---|---|---|---|---|
| ETS | provider | 324 | 2020-05 | 2594 | 1.4% | 2018-04..2023-12 |
| ETS | icb | 194 | 2020-05 | 2702 | 6.0% | 2020-05..2021-10 |
| ETS | region | 45 | 2020-05 | 695 | 8.0% | 2020-05..2021-10 |
| ETS | england | 7 | 2020-05 | 113 | 9.1% | 2020-05..2021-10 |
| STL+ARIMA | provider | 229 | 2017-12, 2018-01, 2018-02, 2018-04 | 3393 | 1.4% | 2018-04..2023-12 |
| STL+ARIMA | icb | 5 | 2018-01, 2020-12, 2021-02, 2021-03 | 0 | 0.0% |  |
| STL+ARIMA | region | 0 |  | 0 | 0.0% |  |
| STL+ARIMA | england | 0 |  | 0 | 0.0% |  |
| M1 | provider | 6 | 2017-11, 2017-12, 2018-04, 2018-06 | 585 | 0.2% | 2018-08..2023-01 |
| M1 | icb | 0 |  | 0 | 0.0% |  |
| M1 | region | 0 |  | 0 | 0.0% |  |
| M1 | england | 0 |  | 0 | 0.0% |  |
