# Stage G — occupancy validation

Run 2026-09-10 at commit `c58be85`; design and tolerance in the
pre-registration amendments of 2026-09-09 (tolerance) and 2026-09-10 (Stage G design).

## Registered check (out of sample, DEV quarters Apr–Jun 2018 to Oct–Dec 2023)

Reconstructed occupancy = c_j × realised A&E admissions / days / the quarter's G&A beds,
with c_j fitted only on KH03 quarters published before the quarter began.

| variant | COVID window | trust-quarters | median \|error\| (pp) | within 10 pp | median error (pp) | passes |
|---|---|---|---|---|---|---|
| national | no | 2274 | 18.9 | 29% | 4.6 | no |
| national | yes | 800 | 17.4 | 31% | 8.8 | no |
| trust | no | 2274 | 8.7 | 57% | 37.3 | no |
| trust | yes | 800 | 10.6 | 48% | 256.4 | no |
| trust+nctr | no | 600 | 7.1 | 49% | -0.5 | no |
| trust_same_rows | no | 600 | 8.1 | 60% | -1.7 | no |

Tolerance (registered 2026-09-09): median |error| ≤ 5 pp and ≥ 80% of trust-quarters within 10 pp. The test applies to the trust-specific variant outside the COVID window.

**Verdict: FAILS** — median 8.7 pp, 57% within 10 pp. Under the registered rule the decision layer is **illustrative only**, the memo's bed numbers carry that label, and Stage D's selection falls back to WIS.

By year (trust-specific, outside the COVID window; 'mean_err_pp' is the median signed error):

| year | trust_quarters | median_abs_pp | share_within_10pp | mean_err_pp |
|---|---|---|---|---|
| 2018 | 424 | 9.95 | 0.5 | 8.81 |
| 2019 | 557 | 7.08 | 0.65 | 5.22 |
| 2021 | 258 | 10.1 | 0.5 | 4.09 |
| 2022 | 520 | 9.69 | 0.52 | -8.04 |
| 2023 | 515 | 7.4 | 0.61 | -1.28 |

## Exploratory (not pre-registered): what does predict occupancy?

| index | trust_quarters | median_abs_pp | share_within_10pp |
|---|---|---|---|
| registered reconstruction, all trust-quarters | 2.27e+03 | 8.71 | 0.565 |
| registered reconstruction, acute + unchanged footprint | 2.14e+03 | 8.49 | 0.58 |
| naive: latest published occupancy (same rows) | 2.14e+03 | 2.38 | 0.955 |
| naive: same quarter last year (same rows) | 1.66e+03 | 2.38 | 0.957 |

Occupancy is far more predictable from its own recent level than from A&E admissions: hospitals
run close to capacity and the rest of their admissions flex around emergency demand, so an
admissions forecast carries little of the occupancy signal at quarterly resolution [inference].
This is a candidate redesign for the decision layer (occupancy persistence plus an admissions
surprise term), to be registered before it is tested.
