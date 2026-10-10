# E-m2f-69: M2f-r4 on all 69 DEV origins, with draws saved, and the D1 condition (WO-A)

**Verdict: D1 EXCLUDE.** The pre-committed condition (`docs/d1_precommitments.md` (a), `93704d0`) was applied mechanically, and one of its four clauses flips.

Winter-h3 ICB gm WIS of M2f-r4 against raw ETS is **+12.4%** on the 69-origin set, against **+23.5%** on the 35-origin set. That is a move of 11.1 pp, beyond the 10 pp limit and beyond its 0.2 pp seed-noise tolerance.

**The move rests on one origin.** 2020-01's h3 target is March 2020, the first lockdown month. Without that origin the figure is +22.8% and nothing flips (see Verification).

The other three clauses hold:

| Clause | 69-origin value | Limit |
|---|---|---|
| Median max R-hat | 1.090 | ≤ 1.10 |
| 2023 median max R-hat | 1.091 | ≤ 1.12 |
| ICB 90% coverage, all months, h1–h6 | 0.889–0.900 | [0.85, 0.95] |
| Mean coherence gap, region / England | 0.13% / 0.06% | < 1% |

Under WO-A, EXCLUDE means: nothing is frozen or tagged; the live model reverts to raw ETS; and WO-B's ETS path becomes primary. DEV only. No token was used, no CONF origin was touched and no embargoed target was scored.

## Provenance

| Step | Commit | Time (2026-09-12, +01:00) |
|---|---|---|
| 2026-09-10 release archived; vintage table rebuilt (the pre-existing rows are unchanged) | `e004a21` | 07:21 |
| Pre-commitments (a), (b), (c), how (a) is applied, and a DEV-consistency note | `93704d0` | 07:25:39 |
| Step-2 runner and draw storage (`m2f_69.py`, `models/m2_draws.py`) | `a43ec0e` | 07:29:06 |
| First fit written (2023-04, the smoke run) | — | 07:31:13 |
| Step-3 rescoring code, committed before any 69-origin figure | `b76a8bf` | 07:36:37 |
| Last fit written | — | 08:48:10 |
| Exceedance fix | `a7055ac` | 08:50:07 |

**The exceedance fix.** The first rescoring attempt stopped in the descriptive exceedance step, before writing any file or printing anything. The cause: raw ETS forecasts exactly zero at 2020-05, an odd origin, so the relative error is undefined there. The fix drops those forecasts for all four models alike and counts them. It touches no D1 statistic.

**Fits.** Model `m2f_r4` (the `b77430e` specification), with the Stage E seeds (fit seed year × 100 + month, predictive seed month) and nutpie, 4 chains × 1,000 tuning + 1,000 draws. Environment: `.venv-m2`, jobs 3, cores 4, nothing else fitting.
- 69 fits, no failures, no divergences, **no fit excluded**.
- Wall-clock per fit is in `diagnostics_69.csv`. Sampling: median 60 s, range 29–2,518 s. Wall-clock including diagnostics and draw storage: median 99 s.
- **Contention.** Between about 07:58 and 08:39 something slowed the machine 25–40×.
  - 2022-09's non-sampling steps took 18 minutes.
  - 2022-10, 2022-11 and 2022-12 sampled for 25–42 minutes each.
  - The only jobs I started in that window were light (tests and a scoring dry run), so the cause is not established.
  - Sampling is deterministic given the seeds, so the draws are unaffected: 2022-10 and 2022-12 reproduce `b77430e` bit for bit.
- The 35 even-month refits reproduce the committed `b77430e` table bit for bit: 249,480 of 249,480 rows, maximum absolute difference 0.

**Draws** are stored in `data/processed/m2f_69/draws/` (gitignored): **960 MB** in total (918 MiB on disk), not thinned.
- `predictive/<origin>.npz`: posterior predictive sample paths as exact int32 counts, `(4000 draws, 36 ICBs, 6 horizons)` per target. Draw `c × 1000 + d` is chain `c`, draw `d`. The file also holds ICB, region and period labels.
- `posterior/<origin>.npz`: float64 posterior draws of every quantity the forecast reads — the scalar parameters, and each walk's final month and posterior-mean path. With the predictive seed these regenerate the paths exactly: checked at 2023-04, maximum difference 0.
- The full latent paths (about 32 GB) are not stored. A fit is bit-reproducible from its seeds, code and data.

**Hashes.**

| File | SHA-256 |
|---|---|
| `forecasts_m2f_r4_69.parquet` | `ab97843e…ad93e4` |
| `diagnostics_m2f_r4_69.csv` | `9d60af11…7126a6` |
| Inputs | in `run.json` |

## Slices and exclusion counts

| Set | Origins |
|---|---|
| "69" | All DEV origins, 2018-04 to 2023-12 |
| "35" | The even-month ladder: the same code on the `b77430e`-identical subset, so every 69-origin figure has its counterpart |

- **WIS.** Winter-h3 (target months December to March, h = 3), ICB level, as-of, raw ETS = `stage_e/comparator_b1.parquet` (the file behind +23.5%). Paired bootstrap over ICBs, 1,000 resamples, seed 0.
  - This gives 20 origins at 69 (10 at 35). Two origins are truncated (Appendix A):
    - 2021-10 has no as-of 2021-09, so its h3 falls in November and it is not in the slice;
    - 2018-11's h3 falls in December 2018, the same target as 2018-10's, so that month enters the 69-origin slice twice, identically for both models.
  - The harness dropped the embargoed rows of origins 2023-11 and 2023-12.
- **Coverage.** Pooled over ICBs and targets, by horizon, all months and outside COVID. The window follows `stage_d.assessable`.
- **PIT and exceedance.** E-pit's method: four models on common rows, outturns M2 would treat as near-zero removed, seeded tie placement. Outside COVID this gives 31,104 common rows at 69 origins and 15,552 at 35 origins. The 35-origin figures reproduce E-pit exactly.
  - **Exceedance only:** 217 forecasts dropped, all raw ETS at 2020-05 with a zero median, removed for every model.

## Results, each against its 35-origin counterpart

**WIS of M2f-r4 against raw ETS, winter h3, ICB, gm** (`wis_vs_raw_ets.csv`):

| Window | 35 origins | 69 origins |
|---|---|---|
| All months | +23.5% [+16.6, +30.1] (10) | **+12.4% [+9.3, +15.4] (20)** |
| Outside COVID | −0.1% [−7.6, +6.3] (8) | **+5.4% [−1.0, +10.5] (15)** |
| Inside COVID | +88.6% [+73.4, +105.9] (2) | **+18.3% [+14.9, +22.2] (5)** |

**The flip rests on one origin, 2020-01** (found by the verification below).
- Its h3 target is March 2020, the first lockdown month. The outturn fell about 32% below both models' medians.
- It carries about a third of each model's summed winter-h3 WIS, and there M2f-r4's WIS is 0.85–0.94 of ETS's.
- Without it the 69-origin gm is **+22.8%**, a move of −0.7 pp: no flip.
- Dropping any single one of 2021-12, 2022-01, 2022-10 or 2023-10 also undoes the flip, counting the 0.2 pp seed allowance. Every other single-origin drop leaves it in place.
- The other two added COVID-window origins, 2020-11 and 2021-01, push the other way.
- The even-month ladder can never contain a January or March h3 target, so the two sets differ in target-month mix as well as in size.

Outside COVID the 69-origin figure is 5.5 pp worse than at 35 origins. Per-origin gm ranges from −27% to +109% (description only, not in any file).

**ICB coverage** (`coverage.csv`):

| | h1 | h2 | h3 | h4 | h5 | h6 |
|---|---|---|---|---|---|---|
| 90%, all months, 35 | 0.900 | 0.901 | 0.923 | 0.900 | 0.896 | 0.891 |
| 90%, all months, 69 | 0.891 | 0.895 | 0.900 | 0.894 | 0.889 | 0.897 |
| 90%, outside COVID, 35 | 0.893 | 0.905 | 0.936 | 0.942 | 0.932 | **0.963** |
| 90%, outside COVID, 69 | 0.888 | 0.899 | 0.924 | 0.933 | 0.942 | **0.962** |
| 50%, outside COVID, 69 | 0.503 | 0.513 | 0.596 | 0.599 | 0.615 | 0.660 |

- The h6 over-coverage outside COVID flagged in the pre-commitments holds at 69 origins.
- At England level, 90% coverage outside COVID at h6 is 0.984 at both 35 and 69 origins.

**Coherence gap** (`coherence.csv`), mean over rows:

| Set | Region | England |
|---|---|---|
| 69 origins | 0.126% (maximum 0.97%) | 0.059% |
| 35 origins | 0.124% | 0.058% |

The gap includes 360 aggregate forecasts whose target periods fall in the embargoed window, from origins 2023-08 to 2023-12. The gap uses forecast medians only, no outturn, and the 35-origin figure used the same convention.

**PIT, outside COVID, pooled** (`pit_*_69.csv`, `pit_*_35.csv`):
- M2f-r4 is still too wide in the middle: 50% coverage 0.577 (0.576 at 35), and the central bins' ratio 1.06 / 1.25.
- Its lower tail is heavier at 69 origins: bin 0 ratio 0.96 (0.79 at 35).
- Raw ETS's top bin is **1.74×** (1.90× at 35).

**Exceedance, outside COVID** (`exceedance_*`). Share of outturns above the median, with 95% intervals clustered on ICB / on origin:

| Model | 35 origins | 69 origins |
|---|---|---|
| M2f-r4 | 0.575 | 0.548 [0.532, 0.563] / [0.489, 0.606] |

- M2f-r4's drift is +1.30 pp per horizon: [+0.85, +1.75] clustered on ICB, [−0.40, +3.00] clustered on origin.
- As at 35 origins, only M1 + pooled's drift survives clustering on origin: [+0.16, +3.83].
- By origin-year (M2f-r4): 2018 0.705, 2019 0.561, 2020 0.117, 2021 0.206, 2022 0.537, 2023 0.633. **2023 is not special** at 69 origins: 0.725 at 35 origins, and 2018 is as high. The bias is episodic.

**Sampling by origin-year** (`sampling_by_year.csv`), median max R-hat:

| Model, set | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 |
|---|---|---|---|---|---|---|
| M2f-r4, 69 | 1.086 | 1.109 | 1.073 | 1.094 | 1.118 | 1.091 |
| `m2d_corr`, 69 | 1.015 | 1.015 | 1.026 | 1.047 | 1.052 | 1.069 |

- M2f-r4 has no trend with origin date, but is worse than `m2d_corr` in every year. Its median min ESS is 42 (47 at 35 origins).
- The odd-month fits sample worse than the even ones: the median R-hat rises from 1.079 at 35 origins to 1.090 at 69.
- Seven fits have max R-hat above 1.15 or min bulk ESS below 20 (2 of the 35 even ones), and all seven have `kappa_all` as their worst parameter: 2019-03, 2019-05, 2020-04, 2022-02, 2022-03, 2023-05 and 2023-07. These are description only; the D1 rule has no per-fit limit.

## Verification (three independent agents, each trying to refute the verdict)

All three support EXCLUDE as the correct mechanical outcome. None found a computational error: every D1 figure was recomputed with independent code to better than 0.001 pp.

| Lens | What it did | Result |
|---|---|---|
| Rule fidelity | Checked the code against the committed text, line by line; checked the commit order (`93704d0` before the runner and the first fit) | No mismatch |
| Independent recomputation | Recomputed with its own WIS code; checked R-hat against the saved posterior draws and quantiles against the saved predictive draws | Match |
| Seal and provenance | Checked 69 DEV origins only; the maximum scored period is 2023-12; raw ETS is the same file as behind +23.5% (SHA `96ee7657…`); DEV truth is unchanged by the ingest; the `run.json` hashes match | Pass |

Points that qualify, but do not change, the verdict:
1. **The flip rests on origin 2020-01** (see Results).
2. **Seed noise is unlikely to reverse it.** From the seed-stability slices, the seed SD of the 69-origin gm is estimated at about 0.25–0.3 pp [inference], so the 0.94 pp margin is about 3 SD. Seed noise at 2020-01 itself was never measured.
3. **Condition (1) is a near miss:** median R-hat 1.0902 against 1.10, with 30 of 69 fits above 1.10.
4. **Two odd origins were already known.** 2022-07 and 2023-08 were fitted on 2026-09-11 (seed stability), before the pre-commitments, and the 69-origin fits are bit-identical to those. Neither has a winter h3 target.
5. **One code change came after the fits.** The D1 code is unchanged from `b76a8bf`, and `a7055ac` changed only the exceedance step. The first rescoring attempt computed D1 in memory but printed and wrote nothing before it failed.

## What EXCLUDE does and does not say

- **What the rule tests.** It pre-specified that D1 = include stands only if the 69-origin picture reproduces the 35-origin one. It did not.
  - The all-months figure moved because of a single origin, 2020-01, whose March 2020 target the even ladder could never contain. As evidence about the model, the flip is weak.
  - Neither figure proved stable: the 35-origin inside-COVID figure rested on two origins, and the outside-COVID figure also moved.
- **Which way it moved.** The all-months figure moved in M2f-r4's favour. The outside-COVID figure, the one relevant to a calm CONF, moved against it: from parity to +5.4% worse than ETS, with an interval that just includes zero.
- **What it does not say.** The verdict is not a finding that M2f-r4 is worse than ETS. Its coherence (0.13% and 0.06%) and its aggregate calibration are unchanged.
