# F2: built-in coherence against post-hoc reconciliation, run 2026-09-11 at `059a368`

35 DEV ladder origins, as-of. *Coherence gap:* |aggregate median − sum of its children's medians| / aggregate median (ICB: children are providers; region: ICBs; England: regions). For reconciled forecasts the ICB gap is the rest node (providers the base model cannot forecast, which stay in the hierarchy but are not reported); the region and England gaps come from re-sorting crossed quantiles after projection. M2's aggregates are sums of joint draws, so they are coherent as distributions; their medians are not additive, and the gap shown for M2 measures that. *WIS:* winter h=3 mean WIS per target, and the geometric mean over targets of the WIS ratio to M1 + pooled at the same level (ETS + pooled is not used as the reference: its aggregates blow up in 2020–21, see `h3_results.md`). `_out`/`_in`: outside/inside the COVID window (exploratory). M2f-r4 is the phase-1b model from branch `m2f-redesign` (commit b77430e); `m2d_corr` is the frozen M2.

| model | level | coh_gap_mean | coh_gap_max | wis_rel_m1 | wis_att_all | wis_att_type1 | wis_adm_via_ae | cov90 | cov50 | cov90_h1 | cov90_h2 | cov90_h3 | cov90_h4 | cov90_h5 | cov90_h6 | cov90_out | cov50_out | cov90_in | cov50_in |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ETS + pooled | icb | 3.98% | 81.99% | +790.7% | 1,178,549 | 1,247 | 283 | 0.89 | 0.56 | 0.92 | 0.90 | 0.91 | 0.89 | 0.88 | 0.86 | 0.93 | 0.60 | 0.80 | 0.45 |
| ETS + pooled | region | 0.58% | 15.44% | +1764.7% | 63,982,440 | 6,534 | 1,092 | 0.89 | 0.57 | 0.92 | 0.89 | 0.92 | 0.88 | 0.87 | 0.84 | 0.92 | 0.62 | 0.80 | 0.45 |
| ETS + pooled | england | 0.30% | 2.15% | +3432.1% | 3,528,083,679 | 72,883 | 7,756 | 0.90 | 0.60 | 0.91 | 0.93 | 0.93 | 0.89 | 0.87 | 0.84 | 0.93 | 0.63 | 0.82 | 0.50 |
| ETS + pooled + MinT | icb | 3.84% | 82.24% | +600.4% | 580,612 | 1,186 | 293 | 0.88 | 0.52 | 0.92 | 0.90 | 0.90 | 0.87 | 0.85 | 0.84 | 0.93 | 0.59 | 0.75 | 0.35 |
| ETS + pooled + MinT | region | 0.54% | 67.43% | +382.4% | 1,180,446 | 5,494 | 1,219 | 0.92 | 0.58 | 0.96 | 0.94 | 0.95 | 0.90 | 0.90 | 0.87 | 0.99 | 0.67 | 0.76 | 0.35 |
| ETS + pooled + MinT | england | 0.50% | 27.15% | -21.6% | 81,881 | 37,005 | 7,716 | 0.93 | 0.63 | 0.97 | 0.95 | 0.95 | 0.91 | 0.90 | 0.88 | 1.00 | 0.74 | 0.75 | 0.36 |
| M1 + pooled | icb | 2.98% | 84.59% | +0.0% | 1,887 | 1,063 | 293 | 0.91 | 0.55 | 0.94 | 0.91 | 0.92 | 0.89 | 0.90 | 0.88 | 0.94 | 0.63 | 0.81 | 0.35 |
| M1 + pooled | region | 3.58% | 46.93% | +0.0% | 9,714 | 5,302 | 1,367 | 0.87 | 0.51 | 0.90 | 0.87 | 0.89 | 0.85 | 0.86 | 0.82 | 0.91 | 0.59 | 0.75 | 0.32 |
| M1 + pooled | england | 3.61% | 15.29% | +0.0% | 91,997 | 52,013 | 12,340 | 0.86 | 0.54 | 0.83 | 0.87 | 0.89 | 0.89 | 0.87 | 0.81 | 0.90 | 0.69 | 0.77 | 0.23 |
| M1 + pooled + MinT | icb | 0.49% | 34.73% | +23.1% | 2,478 | 1,239 | 357 | 0.90 | 0.46 | 0.93 | 0.91 | 0.90 | 0.88 | 0.90 | 0.88 | 0.93 | 0.54 | 0.82 | 0.27 |
| M1 + pooled + MinT | region | 0.03% | 2.40% | +13.9% | 12,088 | 5,765 | 1,492 | 0.94 | 0.55 | 0.97 | 0.95 | 0.95 | 0.93 | 0.93 | 0.90 | 0.99 | 0.65 | 0.82 | 0.29 |
| M1 + pooled + MinT | england | 0.02% | 1.94% | -14.4% | 90,507 | 42,036 | 9,736 | 0.94 | 0.57 | 0.97 | 0.94 | 0.97 | 0.93 | 0.93 | 0.89 | 1.00 | 0.69 | 0.82 | 0.30 |
| M2f-r4 (phase 1b) | icb |  |  | +4.7% | 1,899 | 1,053 | 338 | 0.90 | 0.59 | 0.90 | 0.90 | 0.92 | 0.90 | 0.90 | 0.89 | 0.93 | 0.58 | 0.84 | 0.63 |
| M2f-r4 (phase 1b) | region | 0.12% | 0.97% | -2.4% | 9,062 | 5,084 | 1,420 | 0.88 | 0.56 | 0.88 | 0.87 | 0.92 | 0.89 | 0.87 | 0.88 | 0.90 | 0.52 | 0.83 | 0.64 |
| M2f-r4 (phase 1b) | england | 0.06% | 0.34% | -26.7% | 61,816 | 34,676 | 8,875 | 0.88 | 0.56 | 0.87 | 0.87 | 0.95 | 0.87 | 0.84 | 0.90 | 0.90 | 0.52 | 0.83 | 0.65 |
| M2 frozen (m2d_corr) | icb |  |  | -4.5% | 1,812 | 991 | 285 | 0.86 | 0.55 | 0.92 | 0.84 | 0.88 | 0.84 | 0.85 | 0.84 | 0.96 | 0.65 | 0.61 | 0.29 |
| M2 frozen (m2d_corr) | region | 0.18% | 0.86% | -13.4% | 8,518 | 4,817 | 1,116 | 0.80 | 0.47 | 0.80 | 0.77 | 0.84 | 0.80 | 0.82 | 0.80 | 0.91 | 0.56 | 0.53 | 0.24 |
| M2 frozen (m2d_corr) | england | 0.07% | 0.34% | -37.4% | 56,109 | 32,948 | 6,707 | 0.74 | 0.44 | 0.65 | 0.67 | 0.78 | 0.79 | 0.83 | 0.76 | 0.85 | 0.52 | 0.49 | 0.24 |
