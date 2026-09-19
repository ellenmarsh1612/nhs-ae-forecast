# Stage H: confirmatory results

Mode: **run**. Origins counted: 2024-01-01, 2024-02-01, 2024-03-01 … (19). New origins generated: 21.

## Primary comparison (design §7.5)

Verdict: **within tolerance**

Slice: split conf, origin_set CONF19, level provider, mode asof, g1 as_issued, months all, n_origins 19, model m1_lightgbm_v3_raw+pooled, stat cov90.

| horizon | point | lo | hi | lo_within | hi_within | boot_mean_minus_point | n_rows | n_series | n_units | zero_den | zero_den_within | degenerate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 0.875 | 0.851 | 0.906 | 0.867 | 0.884 | 0.00549 | 8495 | 197 | 19 | 0 | 0 | False |
| 2 | 0.883 | 0.865 | 0.909 | 0.872 | 0.895 | 0.00487 | 8485 | 196 | 19 | 0 | 0 | False |
| 3 | 0.887 | 0.862 | 0.917 | 0.873 | 0.9 | 0.00691 | 8477 | 194 | 19 | 0 | 0 | False |
| 4 | 0.896 | 0.881 | 0.92 | 0.881 | 0.911 | 0.00385 | 8466 | 194 | 19 | 0 | 0 | False |
| 5 | 0.895 | 0.875 | 0.925 | 0.879 | 0.91 | 0.00617 | 8456 | 194 | 19 | 0 | 0 | False |
| 6 | 0.903 | 0.884 | 0.925 | 0.886 | 0.918 | 0.00192 | 8446 | 194 | 19 | 0 | 0 | False |

The DEV range (design §7.5, §7.13):

Slice: split conf, origin_set CONF19, level provider, mode asof, g1 as_issued, months all, n_origins 19, model m1_lightgbm_v3_raw+pooled, stat cov90.

| oyear | horizon | conf | conf_origins | dev_min | dev_max | dev_cells | outside | reason | conf_pooled |
|---|---|---|---|---|---|---|---|---|---|
| 2024 | 1 | 0.863 | 12 | 0.858 | 0.909 | 5 | False |  | 0.875 |
| 2024 | 2 | 0.877 | 12 | 0.879 | 0.937 | 5 | True |  | 0.883 |
| 2024 | 3 | 0.875 | 12 | 0.859 | 0.947 | 5 | False |  | 0.887 |
| 2024 | 4 | 0.892 | 12 | 0.879 | 0.939 | 5 | False |  | 0.896 |
| 2024 | 5 | 0.892 | 12 | 0.872 | 0.946 | 5 | False |  | 0.895 |
| 2024 | 6 | 0.905 | 12 | 0.875 | 0.946 | 5 | False |  | 0.903 |
| 2025 | 1 | 0.896 | 7 | 0.858 | 0.909 | 5 | False |  | 0.875 |
| 2025 | 2 | 0.894 | 7 | 0.879 | 0.937 | 5 | False |  | 0.883 |
| 2025 | 3 | 0.908 | 7 | 0.859 | 0.947 | 5 | False |  | 0.887 |
| 2025 | 4 | 0.903 | 7 | 0.879 | 0.939 | 5 | False |  | 0.896 |
| 2025 | 5 | 0.9 | 7 | 0.872 | 0.946 | 5 | False |  | 0.895 |
| 2025 | 6 | 0.898 | 7 | 0.875 | 0.946 | 5 | False |  | 0.903 |

## Verdicts (every registered path; None is n/a)

### Primary (§7.5)

- `primary.verdict.verdict`: "within tolerance"
- `primary.verdict.outside`: {}
- `primary.alongside.failed_dropped.verdict.verdict`: "within tolerance"
- `primary.alongside.failed_dropped.verdict.outside`: {}

### H1 (§7.3)

- `h1.overall.verdict`: "confirmed"
- `h1.overall.fragile`: false
- `h1.overall.flips`: []
- `h1.overall.by_model.m1_lightgbm_v3_raw.verdict`: "confirmed"
- `h1.overall.by_model.m1_lightgbm_v3_raw.fragile`: false
- `h1.failed_dropped.overall.verdict`: "confirmed"
- `h1.failed_dropped.overall.fragile`: false
- `h1.overall.caveat`: "§9 applied to CONF (amendment of 2026-09-10): H1 and H2 are evaluated on CONF with the caveat that a bootstrap over providers within one winter does not capture between-winter variation (DEV's per-year coverage ranged from 0.51 to 0.96 for ETS)."

### H2, M1 clause (§7.5)

- `h2_m1.verdict.verdict`: "confirmed"
- `h2_m1.verdict.directions`: {"1": "under", "2": "under", "3": "under", "4": "under", "5": "under", "6": "under"}
- `h2_m1.verdict.crossings`: {"1": true, "2": true, "3": true, "4": true, "5": true, "6": false}
- `h2_m1.verdict.fragile`: false
- `h2_m1.conf21.verdict.verdict`: "confirmed"
- `h2_m1.failed_dropped.verdict.verdict`: n/a
- `h2_m1.caveat`: "§9 applied to CONF (amendment of 2026-09-10): H1 and H2 are evaluated on CONF with the caveat that a bootstrap over providers within one winter does not capture between-winter variation (DEV's per-year coverage ranged from 0.51 to 0.96 for ETS)."

### H2, M2 clause (§7.5)

- `h2_m2.verdict.verdict`: "refuted"
- `h2_m2.verdict.directions`: {"1": "over", "2": "over", "3": "over", "4": "over", "5": "over", "6": "over"}
- `h2_m2.verdict.crossings`: {"1": true, "2": false, "3": false, "4": false, "5": false, "6": false}
- `h2_m2.verdict.fragile`: false
- `h2_m2.evaluable`: true
- `h2_m2.fail_limit`: 4
- `h2_m2.n_failed_counted`: 0
- `h2_m2.n_counted`: 19
- `h2_m2.n_failed_full`: 0
- `h2_m2.n_full`: 21
- `h2_m2.failed_units`: []
- `h2_m2.conf21.verdict.verdict`: "refuted"
- `h2_m2.failed_dropped.verdict.verdict`: n/a
- `h2_m2.phase`: "a phase-1b test at ICB level, under the §9 fallback: M2 was never sampled at provider level, so the clause registered as pooled across providers is tested at ICB level, in Stage H, by an amendment that overrides the freeze-time deferral"
- `h2_m2.limitation`: "M2 sampling diagnostics degrade monotonically with origin date. Across the 69 DEV origins, median max R-hat rises from 1.015 (2018-19) to 1.069 (2023) and median min bulk ESS falls from 199 to 63 (Spearman 0.77 and -0.82). CONF and the live origin both lie after 2023, so the fits carrying the H2 M2 clause are expected to be the worst sampled in the project. **No fit is excluded on diagnostics**; the plan's rule (report everything, fail only on crashes) stands. A seed-stability check pre-specified at the three worst late DEV origins found forecast quantiles stable across seeds within the registered threshold. The H2 M2-clause verdict therefore stands as reported, with the sampling trend stated as a limitation."
- `h2_m2.limitation_notes`: ["the pattern is a trend, not a monotone sequence", "the 2018-19 ESS figure is 224, not 199", "'the worst sampled' holds for the frozen M2's own fits, since M2f-r4's DEV fits already sample worse"]
- `h2_m2.caveat`: "§9 applied to CONF (amendment of 2026-09-10): H1 and H2 are evaluated on CONF with the caveat that a bootstrap over providers within one winter does not capture between-winter variation (DEV's per-year coverage ranged from 0.51 to 0.96 for ETS)."

### H3 (§7.7)

- `h3.headline.verdict`: "fails"
- `h3.headline.fragile`: true
- `h3.headline.flips`: ["2024-12-01T00:00:00"]
- `h3.failed_dropped.headline.verdict`: "fails"
- `h3.failed_dropped.headline.fragile`: true
- `h3.notes`: ["R2 not tested (phase 1b)", "England: interval n/a (one series).", "Region: caution, bootstrap over 7 series."]

### H4 (§7.8)

- `h4.verdict.verdict`: "confirmed"
- `h4.verdict.refuting`: []
- `h4.verdict.fragile`: false
- `h4.verdict.flips`: []
- `h4.verdict.elements`: []
- `h4.verdict.ranking_holds`: {"att_all": true, "att_type1": true, "adm_via_ae": true}
- `h4.failed_dropped.verdict.verdict`: "confirmed"
- `h4.verdict.note`: "exploratory on CONF (amendment '§9 applied to CONF')"

### H4-original (§7.9)

- `h4_original.verdict.verdict`: "does not hold"
- `h4_original.verdict.exceeds`: []
- `h4_original.verdict.ranking_changes`: []
- `h4_original.failed_dropped.verdict.verdict`: "does not hold"

### H4b (§7.10)

- `h4b.overall.verdict`: "not confirmed"
- `h4b.overall.per_target`: {"att_all": "confirmed", "att_type1": "not confirmed", "adm_via_ae": "not confirmed"}
- `h4b.overall.verdict_full`: "not confirmed"
- `h4b.overall.per_target_full`: {"att_all": "confirmed", "att_type1": "not confirmed", "adm_via_ae": "not confirmed"}
- `h4b.overall.label`: "seen"

### H5 (§7.11)

- `h5`: "H5 (cold start): not evaluable on CONF, and never testable on a sealed split after Stage H. M2 exists only at ICB level, the current 36-ICB mapping is applied to the whole history so no ICB series has a cold start, and a provider-level M2 was never built."

### F2 (§7.12)

- `f2.notes`: ["The gap for m2d_corr measures median non-additivity: its aggregates are sums of joint draws, coherent as distributions.", "WIS relative to M1 + pooled; England interval n/a (one series)."]

## H1 per target (design §7.3)

Slice: split conf, origin_set W5, level provider, mode asof, g1 as_issued, months winter, horizons 3, n_origins 5, metric mase.

| model | role | target | rel | rel_lo | rel_hi | verdict | qualifier | fragile | qualifier_fragile |
|---|---|---|---|---|---|---|---|---|---|
| m1_lightgbm | decides | att_all | -0.476 | -0.525 | -0.421 | confirmed | n/a | False | n/a |
| m1_lightgbm | decides | att_type1 | -0.448 | -0.501 | -0.394 | confirmed | n/a | False | n/a |
| m1_lightgbm | decides | adm_via_ae | -0.384 | -0.446 | -0.316 | confirmed | n/a | False | n/a |
| m1_lightgbm | descriptive | pooled | -0.437 | -0.474 | -0.398 | descriptive | n/a | n/a | n/a |
| m1_lightgbm_v3_raw | alongside | att_all | -0.355 | -0.404 | -0.297 | confirmed | n/a | False | n/a |
| m1_lightgbm_v3_raw | alongside | att_type1 | -0.33 | -0.389 | -0.267 | confirmed | n/a | False | n/a |
| m1_lightgbm_v3_raw | alongside | adm_via_ae | -0.452 | -0.506 | -0.391 | confirmed | n/a | False | n/a |
| m1_lightgbm_v3_raw | descriptive | pooled | -0.392 | -0.429 | -0.35 | descriptive | n/a | n/a | n/a |

## H3 per base (design §7.7)

Slice: split conf, origin_set W5, mode asof, g1 as_issued, months winter, horizons 3, n_origins 5, metric wis.

| base | H3 | icb_rel_hi | provider_rel | fragile | flips |
|---|---|---|---|---|---|
| ETS | holds | -0.022 | -0.00488 | True | [Timestamp('2024-10-01 00:00:00')] |
| STL+ARIMA | fails | 0.119 | 0.0602 | False | [] |
| M1 | fails | 0.0196 | 0.0517 | True | [Timestamp('2024-12-01 00:00:00')] |

## H4b, CONF and DEV side by side (design §7.10)

Labelled *seen*. H4b has no registered DEV range, so the DEV side is shown, not flagged (§7.13).

Slice: split conf, origin_set CONF19, n_origins 19.

| target | late_larger | need | verdict |
|---|---|---|---|
| att_all | 16 | 10 | confirmed |
| att_type1 | 0 | 10 | not confirmed |
| adm_via_ae | 0 | 10 | not confirmed |

Slice: split conf, origin_set CONF21, n_origins 21.

| target | late_larger | need | verdict |
|---|---|---|---|
| att_all | 16 | 11 | confirmed |
| att_type1 | 0 | 11 | not confirmed |
| adm_via_ae | 0 | 11 | not confirmed |

Slice: split dev, origin_set DEV, n_origins 69.

| target | late_larger | share | role |
|---|---|---|---|
| att_all | 21 | 0.304 | descriptive |
| att_type1 | 11 | 0.159 | descriptive |
| adm_via_ae | 11 | 0.159 | descriptive |

## CONF against DEV's range (design §7.13)

Each CONF value is flagged outside DEV's range [min, max] (winter-h3 statistics: DEV's seasons, the 2023/24 fragment left out; coverage: DEV's origin-year cells at the same horizon). A flag decides nothing. None means not flagged, with its reason.

### h1

1 of 8 outside DEV's range; 0 not flagged. Outside: m1_lightgbm att_type1 rel.

Slice: split conf, origin_set W5, level provider, mode asof, g1 as_issued, months winter, horizons 3, n_origins 5, stat rel, metric mase.

| model | target | conf | dev_min | dev_max | n_seasons | outside | reason |
|---|---|---|---|---|---|---|---|
| m1_lightgbm | att_all | -0.476 | -0.539 | -0.141 | 5 | False |  |
| m1_lightgbm | att_type1 | -0.448 | -0.425 | -0.0289 | 5 | True |  |
| m1_lightgbm | adm_via_ae | -0.384 | -0.469 | -0.209 | 5 | False |  |
| m1_lightgbm | pooled | -0.437 | -0.469 | -0.15 | 5 | False |  |
| m1_lightgbm_v3_raw | att_all | -0.355 | -0.574 | -0.191 | 5 | False |  |
| m1_lightgbm_v3_raw | att_type1 | -0.33 | -0.524 | -0.14 | 5 | False |  |
| m1_lightgbm_v3_raw | adm_via_ae | -0.452 | -0.485 | -0.195 | 5 | False |  |
| m1_lightgbm_v3_raw | pooled | -0.392 | -0.51 | -0.226 | 5 | False |  |

### h3

5 of 12 outside DEV's range; 0 not flagged. Outside: ETS provider rel, ETS icb rel, ETS region rel, M1 icb rel, M1 england rel.

Slice: split conf, origin_set W5, mode asof, g1 as_issued, months winter, horizons 3, n_origins 5, stat rel, metric wis.

| base | level | conf | dev_min | dev_max | n_seasons | outside | reason |
|---|---|---|---|---|---|---|---|
| ETS | provider | -0.00488 | 0.0114 | 0.151 | 5 | True |  |
| ETS | icb | -0.061 | 0.0084 | 0.245 | 5 | True |  |
| ETS | region | -0.0879 | -0.0335 | 0.248 | 5 | True |  |
| ETS | england | -0.09 | -0.435 | 0.452 | 5 | False |  |
| STL+ARIMA | provider | 0.0602 | -0.0373 | 0.0907 | 5 | False |  |
| STL+ARIMA | icb | 0.0708 | -0.0722 | 0.103 | 5 | False |  |
| STL+ARIMA | region | 0.116 | -0.0905 | 0.227 | 5 | False |  |
| STL+ARIMA | england | 0.0904 | -0.207 | 0.265 | 5 | False |  |
| M1 | provider | 0.0517 | -0.0386 | 0.319 | 5 | False |  |
| M1 | icb | -0.0169 | -0.0136 | 0.297 | 5 | True |  |
| M1 | region | 0.0693 | -0.235 | 0.209 | 5 | False |  |
| M1 | england | -0.321 | -0.264 | 0.0383 | 5 | True |  |

### h4

1 of 15 outside DEV's range; 0 not flagged. Outside: b0_seasonal_naive adm_via_ae rel.

Slice: split conf, origin_set W5, level provider, mode final vs asof, g1 as_issued, months winter, horizons 3, n_origins 5, stat rel, metric wis.

| model | target | conf | dev_min | dev_max | n_seasons | outside | reason |
|---|---|---|---|---|---|---|---|
| b0_seasonal_naive | att_all | -0.000205 | -0.00198 | 0.000646 | 5 | False |  |
| b0_seasonal_naive | att_type1 | -3.94e-06 | -0.00368 | 0.00196 | 5 | False |  |
| b0_seasonal_naive | adm_via_ae | -0.00151 | -0.00145 | 0.000806 | 5 | True |  |
| b1_ets | att_all | -0.00027 | -0.0469 | 0.0036 | 5 | False |  |
| b1_ets | att_type1 | 3.01e-05 | -0.00173 | 0.00403 | 5 | False |  |
| b1_ets | adm_via_ae | -0.00251 | -0.0197 | 0.00315 | 5 | False |  |
| b2_stl_arima | att_all | 0.000279 | -0.0355 | 0.00299 | 5 | False |  |
| b2_stl_arima | att_type1 | 0.000147 | -0.0168 | 0.000708 | 5 | False |  |
| b2_stl_arima | adm_via_ae | -0.00284 | -0.0165 | 0.00137 | 5 | False |  |
| m1_lightgbm | att_all | -0.000632 | -0.0152 | 0.000719 | 5 | False |  |
| m1_lightgbm | att_type1 | 4.34e-05 | -0.011 | 0.00223 | 5 | False |  |
| m1_lightgbm | adm_via_ae | -0.00368 | -0.00394 | 0.00661 | 5 | False |  |
| m1_lightgbm_v3_raw | att_all | 0.00153 | -0.0355 | 0.0262 | 5 | False |  |
| m1_lightgbm_v3_raw | att_type1 | 0.00349 | -0.0219 | 0.055 | 5 | False |  |
| m1_lightgbm_v3_raw | adm_via_ae | -0.0135 | -0.0278 | 0.00462 | 5 | False |  |

### h4_original

0 of 12 outside DEV's range; 0 not flagged.

Slice: split conf, origin_set W5, level provider, mode final vs asof, g1 as_issued, months winter, horizons 3, n_origins 5, stat delta_pp, metric wis.

| model | target | conf | dev_min | dev_max | n_seasons | outside | reason |
|---|---|---|---|---|---|---|---|
| b1_ets | att_all | -0.151 | -1.22 | 7.66 | 5 | False |  |
| b1_ets | att_type1 | 0.00197 | -0.144 | 9.63 | 5 | False |  |
| b1_ets | adm_via_ae | -0.0482 | -0.838 | 7.22 | 5 | False |  |
| b2_stl_arima | att_all | -0.187 | -1.07 | 6.31 | 5 | False |  |
| b2_stl_arima | att_type1 | 0.0093 | -0.406 | 7.53 | 5 | False |  |
| b2_stl_arima | adm_via_ae | -0.067 | -0.96 | 5.78 | 5 | False |  |
| m1_lightgbm | att_all | -0.0174 | -1.62 | 11 | 5 | False |  |
| m1_lightgbm | att_type1 | 0.00247 | -2.61 | 10.2 | 5 | False |  |
| m1_lightgbm | adm_via_ae | -0.134 | -0.834 | 7.04 | 5 | False |  |
| m1_lightgbm_v3_raw | att_all | 0.0773 | -1.17 | 9.94 | 5 | False |  |
| m1_lightgbm_v3_raw | att_type1 | 0.218 | -0.136 | 9.53 | 5 | False |  |
| m1_lightgbm_v3_raw | adm_via_ae | -0.658 | -3.56 | 6.15 | 5 | False |  |

### f2_wis

10 of 60 outside DEV's range; 12 not flagged. Outside: ETS + pooled + MinT icb adm_via_ae rel, M1 + pooled + MinT icb att_all rel, M1 + pooled + MinT region att_type1 rel, M1 + pooled + MinT region adm_via_ae rel, M1 + pooled + MinT england att_all rel, M1 + pooled + MinT england att_type1 rel, M2 frozen (m2d_corr) icb att_type1 rel, M2 frozen (m2d_corr) region att_type1 rel, M2 frozen (m2d_corr) region adm_via_ae rel, M2 frozen (m2d_corr) region geometric mean rel.

Slice: split conf, origin_set W5, mode asof, g1 as_issued, months winter, horizons 3, n_origins 5, stat rel, metric wis.

| model | level | target | conf | dev_min | dev_max | n_seasons | outside | reason |
|---|---|---|---|---|---|---|---|---|
| ETS + pooled | icb | att_all | 0.0256 | -0.236 | 0.469 | 5 | False |  |
| ETS + pooled | icb | att_type1 | 0.00798 | -0.279 | 0.327 | 5 | False |  |
| ETS + pooled | icb | adm_via_ae | -0.123 | -0.174 | 0.116 | 5 | False |  |
| ETS + pooled | icb | geometric mean | -0.0321 | -0.188 | 0.257 | 5 | False |  |
| ETS + pooled | region | att_all | 0.161 | -0.343 | 1.12 | 5 | False |  |
| ETS + pooled | region | att_type1 | 0.285 | -0.393 | 0.538 | 5 | False |  |
| ETS + pooled | region | adm_via_ae | -0.0738 | -0.274 | 0.0126 | 5 | False |  |
| ETS + pooled | region | geometric mean | 0.114 | -0.316 | 0.334 | 5 | False |  |
| ETS + pooled | england | att_all | -0.152 | -0.594 | 0.54 | 5 | False |  |
| ETS + pooled | england | att_type1 | -0.348 | -0.565 | 1.88 | 5 | False |  |
| ETS + pooled | england | adm_via_ae | -0.479 | -0.75 | 0.473 | 5 | False |  |
| ETS + pooled | england | geometric mean | -0.34 | -0.646 | 0.55 | 5 | False |  |
| ETS + pooled + MinT | icb | att_all | -0.00537 | -0.118 | 0.612 | 5 | False |  |
| ETS + pooled + MinT | icb | att_type1 | -0.126 | -0.235 | 0.463 | 5 | False |  |
| ETS + pooled + MinT | icb | adm_via_ae | -0.124 | -0.038 | 0.254 | 5 | True |  |
| ETS + pooled + MinT | icb | geometric mean | -0.0868 | -0.134 | 0.436 | 5 | False |  |
| ETS + pooled + MinT | region | att_all | 0.121 | -0.17 | 1.25 | 5 | False |  |
| ETS + pooled + MinT | region | att_type1 | -0.0196 | -0.319 | 0.673 | 5 | False |  |
| ETS + pooled + MinT | region | adm_via_ae | -0.00225 | -0.171 | 0.16 | 5 | False |  |
| ETS + pooled + MinT | region | geometric mean | 0.0312 | -0.211 | 0.635 | 5 | False |  |
| ETS + pooled + MinT | england | att_all | -0.212 | -0.458 | 0.646 | 5 | False |  |
| ETS + pooled + MinT | england | att_type1 | -0.472 | -0.475 | 0.277 | 5 | False |  |
| ETS + pooled + MinT | england | adm_via_ae | -0.399 | -0.604 | 0.366 | 5 | False |  |
| ETS + pooled + MinT | england | geometric mean | -0.37 | -0.517 | 0.421 | 5 | False |  |
| M1 + pooled | icb | att_all | 0 | 0 | 0 | 5 | n/a | the reference itself: rel 0 by construction on both sides |
| M1 + pooled | icb | att_type1 | 0 | 0 | 0 | 5 | n/a | the reference itself: rel 0 by construction on both sides |
| M1 + pooled | icb | adm_via_ae | 0 | 0 | 0 | 5 | n/a | the reference itself: rel 0 by construction on both sides |
| M1 + pooled | icb | geometric mean | 0 | 0 | 0 | 5 | n/a | the reference itself: rel 0 by construction on both sides |
| M1 + pooled | region | att_all | 0 | 0 | 0 | 5 | n/a | the reference itself: rel 0 by construction on both sides |
| M1 + pooled | region | att_type1 | 0 | 0 | 0 | 5 | n/a | the reference itself: rel 0 by construction on both sides |
| M1 + pooled | region | adm_via_ae | 0 | 0 | 0 | 5 | n/a | the reference itself: rel 0 by construction on both sides |
| M1 + pooled | region | geometric mean | 0 | 0 | 0 | 5 | n/a | the reference itself: rel 0 by construction on both sides |
| M1 + pooled | england | att_all | 0 | 0 | 0 | 5 | n/a | the reference itself: rel 0 by construction on both sides |
| M1 + pooled | england | att_type1 | 0 | 0 | 0 | 5 | n/a | the reference itself: rel 0 by construction on both sides |
| M1 + pooled | england | adm_via_ae | 0 | 0 | 0 | 5 | n/a | the reference itself: rel 0 by construction on both sides |
| M1 + pooled | england | geometric mean | 0 | 0 | 0 | 5 | n/a | the reference itself: rel 0 by construction on both sides |
| M1 + pooled + MinT | icb | att_all | -0.117 | -0.0515 | 0.358 | 5 | True |  |
| M1 + pooled + MinT | icb | att_type1 | 0.13 | -0.154 | 0.201 | 5 | False |  |
| M1 + pooled + MinT | icb | adm_via_ae | 0.0836 | 0.0573 | 0.258 | 5 | False |  |
| M1 + pooled + MinT | icb | geometric mean | 0.0265 | 0.0148 | 0.271 | 5 | False |  |
| M1 + pooled + MinT | region | att_all | -0.0526 | -0.17 | 0.387 | 5 | False |  |
| M1 + pooled + MinT | region | att_type1 | 0.303 | -0.384 | 0.15 | 5 | True |  |
| M1 + pooled + MinT | region | adm_via_ae | 0.213 | -0.0959 | 0.112 | 5 | True |  |
| M1 + pooled + MinT | region | geometric mean | 0.144 | -0.214 | 0.168 | 5 | False |  |
| M1 + pooled + MinT | england | att_all | -0.33 | -0.32 | 0.0352 | 5 | True |  |
| M1 + pooled + MinT | england | att_type1 | -0.315 | -0.31 | 0.0253 | 5 | True |  |
| M1 + pooled + MinT | england | adm_via_ae | -0.284 | -0.58 | 0.205 | 5 | False |  |
| M1 + pooled + MinT | england | geometric mean | -0.31 | -0.361 | 0.0814 | 5 | False |  |
| M2 frozen (m2d_corr) | icb | att_all | 0.207 | -0.295 | 0.254 | 5 | False |  |
| M2 frozen (m2d_corr) | icb | att_type1 | 0.245 | -0.243 | 0.162 | 5 | True |  |
| M2 frozen (m2d_corr) | icb | adm_via_ae | 0.268 | -0.253 | 0.456 | 5 | False |  |
| M2 frozen (m2d_corr) | icb | geometric mean | 0.24 | -0.241 | 0.285 | 5 | False |  |
| M2 frozen (m2d_corr) | region | att_all | 0.293 | -0.435 | 0.693 | 5 | False |  |
| M2 frozen (m2d_corr) | region | att_type1 | 0.575 | -0.381 | 0.269 | 5 | True |  |
| M2 frozen (m2d_corr) | region | adm_via_ae | 0.474 | -0.298 | 0.279 | 5 | True |  |
| M2 frozen (m2d_corr) | region | geometric mean | 0.443 | -0.337 | 0.384 | 5 | True |  |
| M2 frozen (m2d_corr) | england | att_all | -0.124 | -0.427 | 0.26 | 5 | False |  |
| M2 frozen (m2d_corr) | england | att_type1 | -0.161 | -0.33 | 0.359 | 5 | False |  |
| M2 frozen (m2d_corr) | england | adm_via_ae | -0.137 | -0.272 | 0.391 | 5 | False |  |
| M2 frozen (m2d_corr) | england | geometric mean | -0.141 | -0.343 | 0.189 | 5 | False |  |

### coverage_primary

1 of 12 outside DEV's range; 0 not flagged. Outside: 2024 2.

Slice: split conf, origin_set CONF19, level provider, mode asof, g1 as_issued, months all, n_origins 19, model m1_lightgbm_v3_raw+pooled, stat cov90.

| oyear | horizon | conf | conf_origins | dev_min | dev_max | dev_cells | outside | reason | conf_pooled |
|---|---|---|---|---|---|---|---|---|---|
| 2024 | 1 | 0.863 | 12 | 0.858 | 0.909 | 5 | False |  | 0.875 |
| 2024 | 2 | 0.877 | 12 | 0.879 | 0.937 | 5 | True |  | 0.883 |
| 2024 | 3 | 0.875 | 12 | 0.859 | 0.947 | 5 | False |  | 0.887 |
| 2024 | 4 | 0.892 | 12 | 0.879 | 0.939 | 5 | False |  | 0.896 |
| 2024 | 5 | 0.892 | 12 | 0.872 | 0.946 | 5 | False |  | 0.895 |
| 2024 | 6 | 0.905 | 12 | 0.875 | 0.946 | 5 | False |  | 0.903 |
| 2025 | 1 | 0.896 | 7 | 0.858 | 0.909 | 5 | False |  | 0.875 |
| 2025 | 2 | 0.894 | 7 | 0.879 | 0.937 | 5 | False |  | 0.883 |
| 2025 | 3 | 0.908 | 7 | 0.859 | 0.947 | 5 | False |  | 0.887 |
| 2025 | 4 | 0.903 | 7 | 0.879 | 0.939 | 5 | False |  | 0.896 |
| 2025 | 5 | 0.9 | 7 | 0.872 | 0.946 | 5 | False |  | 0.895 |
| 2025 | 6 | 0.898 | 7 | 0.875 | 0.946 | 5 | False |  | 0.903 |

### coverage_h2_m1

0 of 12 outside DEV's range; 0 not flagged.

Slice: split conf, origin_set CONF19, level provider, mode asof, g1 as_issued, months all, n_origins 19, model m1_lightgbm, stat cov90.

| oyear | horizon | conf | conf_origins | dev_min | dev_max | dev_cells | outside | reason | conf_pooled |
|---|---|---|---|---|---|---|---|---|---|
| 2024 | 1 | 0.83 | 12 | 0.822 | 0.919 | 5 | False |  | 0.846 |
| 2024 | 2 | 0.835 | 12 | 0.782 | 0.899 | 5 | False |  | 0.846 |
| 2024 | 3 | 0.829 | 12 | 0.793 | 0.905 | 5 | False |  | 0.843 |
| 2024 | 4 | 0.824 | 12 | 0.735 | 0.899 | 5 | False |  | 0.833 |
| 2024 | 5 | 0.813 | 12 | 0.764 | 0.905 | 5 | False |  | 0.819 |
| 2024 | 6 | 0.808 | 12 | 0.735 | 0.899 | 5 | False |  | 0.814 |
| 2025 | 1 | 0.874 | 7 | 0.822 | 0.919 | 5 | False |  | 0.846 |
| 2025 | 2 | 0.866 | 7 | 0.782 | 0.899 | 5 | False |  | 0.846 |
| 2025 | 3 | 0.867 | 7 | 0.793 | 0.905 | 5 | False |  | 0.843 |
| 2025 | 4 | 0.848 | 7 | 0.735 | 0.899 | 5 | False |  | 0.833 |
| 2025 | 5 | 0.83 | 7 | 0.764 | 0.905 | 5 | False |  | 0.819 |
| 2025 | 6 | 0.825 | 7 | 0.735 | 0.899 | 5 | False |  | 0.814 |

### coverage_h2_m2

6 of 12 outside DEV's range; 0 not flagged. Outside: 2024 2, 2025 2, 2025 3, 2025 4, 2025 5, 2025 6.

Slice: split conf, origin_set CONF19, level icb, mode asof, g1 as_issued, months all, n_origins 19, model m2d_corr, stat cov90.

| oyear | horizon | conf | conf_origins | dev_min | dev_max | dev_cells | outside | reason | conf_pooled |
|---|---|---|---|---|---|---|---|---|---|
| 2024 | 1 | 0.981 | 12 | 0.903 | 0.981 | 5 | False |  | 0.97 |
| 2024 | 2 | 0.99 | 12 | 0.905 | 0.985 | 5 | True |  | 0.993 |
| 2024 | 3 | 0.985 | 12 | 0.941 | 0.988 | 5 | False |  | 0.989 |
| 2024 | 4 | 0.988 | 12 | 0.86 | 0.991 | 5 | False |  | 0.992 |
| 2024 | 5 | 0.986 | 12 | 0.934 | 0.993 | 5 | False |  | 0.99 |
| 2024 | 6 | 0.99 | 12 | 0.917 | 0.995 | 5 | False |  | 0.992 |
| 2025 | 1 | 0.95 | 7 | 0.903 | 0.981 | 5 | False |  | 0.97 |
| 2025 | 2 | 0.997 | 7 | 0.905 | 0.985 | 5 | True |  | 0.993 |
| 2025 | 3 | 0.996 | 7 | 0.941 | 0.988 | 5 | True |  | 0.989 |
| 2025 | 4 | 0.999 | 7 | 0.86 | 0.991 | 5 | True |  | 0.992 |
| 2025 | 5 | 0.997 | 7 | 0.934 | 0.993 | 5 | True |  | 0.99 |
| 2025 | 6 | 0.996 | 7 | 0.917 | 0.995 | 5 | True |  | 0.992 |

### coverage_headline_raw_b1

8 of 12 outside DEV's range; 0 not flagged. Outside: 2024 1, 2024 2, 2024 5, 2024 6, 2025 1, 2025 4, 2025 5, 2025 6.

Slice: split conf, origin_set CONF19, level provider, mode asof, g1 as_issued, months all, n_origins 19, model b1_ets, stat cov90.

| oyear | horizon | conf | conf_origins | dev_min | dev_max | dev_cells | outside | reason | conf_pooled |
|---|---|---|---|---|---|---|---|---|---|
| 2024 | 1 | 0.953 | 12 | 0.775 | 0.925 | 5 | True |  | 0.951 |
| 2024 | 2 | 0.951 | 12 | 0.766 | 0.949 | 5 | True |  | 0.95 |
| 2024 | 3 | 0.952 | 12 | 0.789 | 0.961 | 5 | False |  | 0.954 |
| 2024 | 4 | 0.958 | 12 | 0.759 | 0.964 | 5 | False |  | 0.961 |
| 2024 | 5 | 0.967 | 12 | 0.77 | 0.961 | 5 | True |  | 0.967 |
| 2024 | 6 | 0.969 | 12 | 0.79 | 0.963 | 5 | True |  | 0.968 |
| 2025 | 1 | 0.947 | 7 | 0.775 | 0.925 | 5 | True |  | 0.951 |
| 2025 | 2 | 0.949 | 7 | 0.766 | 0.949 | 5 | False |  | 0.95 |
| 2025 | 3 | 0.959 | 7 | 0.789 | 0.961 | 5 | False |  | 0.954 |
| 2025 | 4 | 0.966 | 7 | 0.759 | 0.964 | 5 | True |  | 0.961 |
| 2025 | 5 | 0.966 | 7 | 0.77 | 0.961 | 5 | True |  | 0.967 |
| 2025 | 6 | 0.966 | 7 | 0.79 | 0.963 | 5 | True |  | 0.968 |

### coverage_headline_raw_b2

12 of 12 outside DEV's range; 0 not flagged. Outside: 2024 1, 2024 2, 2024 3, 2024 4, 2024 5, 2024 6, 2025 1, 2025 2, 2025 3, 2025 4, 2025 5, 2025 6.

Slice: split conf, origin_set CONF19, level provider, mode asof, g1 as_issued, months all, n_origins 19, model b2_stl_arima, stat cov90.

| oyear | horizon | conf | conf_origins | dev_min | dev_max | dev_cells | outside | reason | conf_pooled |
|---|---|---|---|---|---|---|---|---|---|
| 2024 | 1 | 0.881 | 12 | 0.541 | 0.853 | 5 | True |  | 0.892 |
| 2024 | 2 | 0.92 | 12 | 0.567 | 0.898 | 5 | True |  | 0.93 |
| 2024 | 3 | 0.94 | 12 | 0.613 | 0.923 | 5 | True |  | 0.944 |
| 2024 | 4 | 0.947 | 12 | 0.606 | 0.93 | 5 | True |  | 0.95 |
| 2024 | 5 | 0.952 | 12 | 0.616 | 0.93 | 5 | True |  | 0.954 |
| 2024 | 6 | 0.958 | 12 | 0.652 | 0.934 | 5 | True |  | 0.957 |
| 2025 | 1 | 0.912 | 7 | 0.541 | 0.853 | 5 | True |  | 0.892 |
| 2025 | 2 | 0.945 | 7 | 0.567 | 0.898 | 5 | True |  | 0.93 |
| 2025 | 3 | 0.951 | 7 | 0.613 | 0.923 | 5 | True |  | 0.944 |
| 2025 | 4 | 0.954 | 7 | 0.606 | 0.93 | 5 | True |  | 0.95 |
| 2025 | 5 | 0.957 | 7 | 0.616 | 0.93 | 5 | True |  | 0.954 |
| 2025 | 6 | 0.956 | 7 | 0.652 | 0.934 | 5 | True |  | 0.957 |

### coverage_headline_raw_m1_v3_raw

7 of 12 outside DEV's range; 0 not flagged. Outside: 2024 6, 2025 1, 2025 2, 2025 3, 2025 4, 2025 5, 2025 6.

Slice: split conf, origin_set CONF19, level provider, mode asof, g1 as_issued, months all, n_origins 19, model m1_lightgbm_v3_raw, stat cov90.

| oyear | horizon | conf | conf_origins | dev_min | dev_max | dev_cells | outside | reason | conf_pooled |
|---|---|---|---|---|---|---|---|---|---|
| 2024 | 1 | 0.73 | 12 | 0.62 | 0.75 | 5 | False |  | 0.749 |
| 2024 | 2 | 0.701 | 12 | 0.562 | 0.741 | 5 | False |  | 0.72 |
| 2024 | 3 | 0.678 | 12 | 0.585 | 0.745 | 5 | False |  | 0.719 |
| 2024 | 4 | 0.684 | 12 | 0.556 | 0.701 | 5 | False |  | 0.708 |
| 2024 | 5 | 0.678 | 12 | 0.577 | 0.684 | 5 | False |  | 0.693 |
| 2024 | 6 | 0.671 | 12 | 0.573 | 0.656 | 5 | True |  | 0.683 |
| 2025 | 1 | 0.784 | 7 | 0.62 | 0.75 | 5 | True |  | 0.749 |
| 2025 | 2 | 0.751 | 7 | 0.562 | 0.741 | 5 | True |  | 0.72 |
| 2025 | 3 | 0.789 | 7 | 0.585 | 0.745 | 5 | True |  | 0.719 |
| 2025 | 4 | 0.749 | 7 | 0.556 | 0.701 | 5 | True |  | 0.708 |
| 2025 | 5 | 0.719 | 7 | 0.577 | 0.684 | 5 | True |  | 0.693 |
| 2025 | 6 | 0.703 | 7 | 0.573 | 0.656 | 5 | True |  | 0.683 |

### coverage_headline_pooled_b1

5 of 12 outside DEV's range; 0 not flagged. Outside: 2024 2, 2024 3, 2024 4, 2025 1, 2025 2.

Slice: split conf, origin_set CONF19, level provider, mode asof, g1 as_issued, months all, n_origins 19, model b1_ets+pooled, stat cov90.

| oyear | horizon | conf | conf_origins | dev_min | dev_max | dev_cells | outside | reason | conf_pooled |
|---|---|---|---|---|---|---|---|---|---|
| 2024 | 1 | 0.911 | 12 | 0.908 | 0.973 | 5 | False |  | 0.904 |
| 2024 | 2 | 0.892 | 12 | 0.919 | 0.98 | 5 | True |  | 0.898 |
| 2024 | 3 | 0.889 | 12 | 0.914 | 0.983 | 5 | True |  | 0.904 |
| 2024 | 4 | 0.9 | 12 | 0.918 | 0.981 | 5 | True |  | 0.913 |
| 2024 | 5 | 0.921 | 12 | 0.888 | 0.982 | 5 | False |  | 0.922 |
| 2024 | 6 | 0.942 | 12 | 0.894 | 0.978 | 5 | False |  | 0.935 |
| 2025 | 1 | 0.892 | 7 | 0.908 | 0.973 | 5 | True |  | 0.904 |
| 2025 | 2 | 0.909 | 7 | 0.919 | 0.98 | 5 | True |  | 0.898 |
| 2025 | 3 | 0.93 | 7 | 0.914 | 0.983 | 5 | False |  | 0.904 |
| 2025 | 4 | 0.934 | 7 | 0.918 | 0.981 | 5 | False |  | 0.913 |
| 2025 | 5 | 0.925 | 7 | 0.888 | 0.982 | 5 | False |  | 0.922 |
| 2025 | 6 | 0.922 | 7 | 0.894 | 0.978 | 5 | False |  | 0.935 |

### coverage_headline_pooled_b2

1 of 12 outside DEV's range; 0 not flagged. Outside: 2024 1.

Slice: split conf, origin_set CONF19, level provider, mode asof, g1 as_issued, months all, n_origins 19, model b2_stl_arima+pooled, stat cov90.

| oyear | horizon | conf | conf_origins | dev_min | dev_max | dev_cells | outside | reason | conf_pooled |
|---|---|---|---|---|---|---|---|---|---|
| 2024 | 1 | 0.893 | 12 | 0.896 | 0.953 | 5 | True |  | 0.9 |
| 2024 | 2 | 0.92 | 12 | 0.89 | 0.969 | 5 | False |  | 0.929 |
| 2024 | 3 | 0.94 | 12 | 0.905 | 0.97 | 5 | False |  | 0.942 |
| 2024 | 4 | 0.947 | 12 | 0.89 | 0.97 | 5 | False |  | 0.947 |
| 2024 | 5 | 0.952 | 12 | 0.858 | 0.971 | 5 | False |  | 0.951 |
| 2024 | 6 | 0.958 | 12 | 0.847 | 0.971 | 5 | False |  | 0.954 |
| 2025 | 1 | 0.912 | 7 | 0.896 | 0.953 | 5 | False |  | 0.9 |
| 2025 | 2 | 0.943 | 7 | 0.89 | 0.969 | 5 | False |  | 0.929 |
| 2025 | 3 | 0.946 | 7 | 0.905 | 0.97 | 5 | False |  | 0.942 |
| 2025 | 4 | 0.947 | 7 | 0.89 | 0.97 | 5 | False |  | 0.947 |
| 2025 | 5 | 0.95 | 7 | 0.858 | 0.971 | 5 | False |  | 0.951 |
| 2025 | 6 | 0.947 | 7 | 0.847 | 0.971 | 5 | False |  | 0.954 |

### coverage_headline_pooled_m1_v3_raw

1 of 12 outside DEV's range; 0 not flagged. Outside: 2024 2.

Slice: split conf, origin_set CONF19, level provider, mode asof, g1 as_issued, months all, n_origins 19, model m1_lightgbm_v3_raw+pooled, stat cov90.

| oyear | horizon | conf | conf_origins | dev_min | dev_max | dev_cells | outside | reason | conf_pooled |
|---|---|---|---|---|---|---|---|---|---|
| 2024 | 1 | 0.863 | 12 | 0.858 | 0.909 | 5 | False |  | 0.875 |
| 2024 | 2 | 0.877 | 12 | 0.879 | 0.937 | 5 | True |  | 0.883 |
| 2024 | 3 | 0.875 | 12 | 0.859 | 0.947 | 5 | False |  | 0.887 |
| 2024 | 4 | 0.892 | 12 | 0.879 | 0.939 | 5 | False |  | 0.896 |
| 2024 | 5 | 0.892 | 12 | 0.872 | 0.946 | 5 | False |  | 0.895 |
| 2024 | 6 | 0.905 | 12 | 0.875 | 0.946 | 5 | False |  | 0.903 |
| 2025 | 1 | 0.896 | 7 | 0.858 | 0.909 | 5 | False |  | 0.875 |
| 2025 | 2 | 0.894 | 7 | 0.879 | 0.937 | 5 | False |  | 0.883 |
| 2025 | 3 | 0.908 | 7 | 0.859 | 0.947 | 5 | False |  | 0.887 |
| 2025 | 4 | 0.903 | 7 | 0.879 | 0.939 | 5 | False |  | 0.896 |
| 2025 | 5 | 0.9 | 7 | 0.872 | 0.946 | 5 | False |  | 0.895 |
| 2025 | 6 | 0.898 | 7 | 0.875 | 0.946 | 5 | False |  | 0.903 |

H5: H5 (cold start): not evaluable on CONF, and never testable on a sealed split after Stage H. M2 exists only at ICB level, the current 36-ICB mapping is applied to the whole history so no ICB series has a cold start, and a provider-level M2 was never built.

