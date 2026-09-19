# Stage A — noise floor

Run 2026-09-10 at commit `c58be85`. Design fixed in the pre-registration
amendment of 2026-09-10 (Stage A design) before any seed was run.

## Seed noise against the tuning search (same slice)

Slice: origins 2018-04..2019-08, as-of, provider level, horizons 1–6, all months,
mean WIS across the three targets — the slice the 16-configuration search used.

| | n | mean WIS | SD | SD as % of mean |
|---|---|---|---|---|
| winning config, seeds 0–19 | 20 | 301.9 | 2.59 | 0.86% |
| search configs, all | 16 | 311.4 | | 2.81% |
| search configs, 12-month calibration | 11 | 306.4 | | 1.30% |
| search configs, 24-month calibration | 5 | 322.5 | | 1.46% |

Reproducibility: seed 0 is the search winner; its WIS here is 300.1924 against 300.1924 recorded in `m1_tuned.json`.

## Noise floor on DEV (winter, horizon 3, provider, as-of; `m1_v3`)

| target | mean WIS | SD % of mean | min–max WIS | 90% cov mean | cov SD (pp) | min. meaningful ΔWIS | min. meaningful Δcov90 |
|---|---|---|---|---|---|---|---|
| adm_via_ae | 144.6 | 0.93% | 141.9–146.9 | 0.777 | 0.51 | 2.62% | 1.44 pp |
| att_all | 605.0 | 1.03% | 591.7–615.4 | 0.854 | 0.36 | 2.91% | 1.03 pp |
| att_type1 | 579.0 | 1.20% | 567.5–592.0 | 0.764 | 0.95 | 3.40% | 2.68 pp |

Minimum meaningful difference = 2√2 × seed SD (95% half-width of the difference between two single-seed runs). Smaller differences are reported as within noise.

## STOP 1 summary

```
STOP 1 — noise floor
  tuning slice: seed SD 0.86% of mean WIS; config SD 2.81% (all 16), 1.30% (12-month calibration), 1.46% (24-month calibration)
  DEV winter h3 adm_via_ae: seed SD 0.93% of WIS, cov90 SD 0.51 pp -> min meaningful ΔWIS 2.62%, Δcov90 1.44 pp
  DEV winter h3 att_all   : seed SD 1.03% of WIS, cov90 SD 0.36 pp -> min meaningful ΔWIS 2.91%, Δcov90 1.03 pp
  DEV winter h3 att_type1 : seed SD 1.20% of WIS, cov90 SD 0.95 pp -> min meaningful ΔWIS 3.40%, Δcov90 2.68 pp
```
