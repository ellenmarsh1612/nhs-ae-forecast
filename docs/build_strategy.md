# Phase 1 build strategy

> **Early planning document (2026-09-08), kept as a record.** Superseded where it disagrees
> with `docs/confirmatory_results.md`. Known to be wrong now: "All six winters are usable"
> (the sealed window gives **one** winter, five origins, which is the caveat on every winter
> statistic); "500 files" archived (720 versions in `data/raw/manifest.jsonl`); "32 tests
> pass" (the suite is 735 collected tests); and the H4 bound quoted as ±0.5% (the
> development figure is −0.57% and the sealed figure 0.37%).

**Written:** 2026-09-08 · **Basis:** week-1 code reviewed and run; live NHS England pages, the Internet Archive and eight real files checked in-session. Tags: [verified] checked today, [inference] derived, [recall] unverified memory.

## Verdict

The week-1 foundation is sound and the plan is the right shape, but two things found today should change how the next seven weeks are sequenced:

1. **Vintage recovery is far cheaper than the scope assumes, and is now done.** NHS England does not overwrite files in place. Revised files get new URLs and the originals stay live on england.nhs.uk. The Internet Archive holds the *year pages* densely from 2015-16 onward, so the full URL history can be reconstructed from page captures and the files fetched directly from NHS England. `nhs-ae-ingest recover` did exactly that on 2026-09-08: 500 files, 91 vintage dates, 71 of 73 backtest origins fully covered (Appendix A of the pre-registration lists the two gaps). [verified]
2. **Value revisions are tiny, so H4 as written will probably be refuted.** In five original/revised pairs spanning 2019 to 2025, including the July 2020 wholesale republish, at most two providers per metric changed and national totals moved by under 1%. [verified, n=5 pairs] I put roughly 75% on H4 being refuted for numeric revisions. [inference] That is publishable, but it should not be the headline, and the pre-registration should be amended *before* the freeze to say what the as-of test actually measures (late submitters, provider-set changes, mapping changes, and definitional breaks, not just revised numbers).

The binding constraint is the calendar, not the data: 31 October 2026 is 7.5 weeks away at about 2 days a week, roughly 15 working days, for five models, two reconciliation methods, a decision layer, an app, a Pages site and a handover pack. That is not credible without cutting. The critical path to the first live forecast is: vintage recovery → as-of loader and harness → B0 → M1 → decision layer → memo. Everything else (M2, R1/R2, Streamlit, external covariates) is off that path and should be scheduled so that slipping on it cannot move the date.

## What was verified today

| Check | Result |
|---|---|
| `make test` | 32 tests pass on Python 3.13 |
| `discover` on live pages 2017-18 → 2026-27 | Works: 24 links per year (12 CSV + 12 XLS), CSV preferred |
| `discover` on 2015-16 and 2016-17 | 404: those pages use a different slug (`statistical-work-areasae-waiting-times-and-activityae-attendances-and-emergency-admissions-2016-17/`) and are XLS-only |
| Parser on real CSVs (Apr 2019, Apr 2021, Apr 2024, Oct 2024, Feb/Apr 2025) | Zero unmapped columns; missing providers land as NaN as designed |
| Parser on 2016 XLS | Fails: title block, header row is `Code / Region / Name` under a merged `A&E attendances` row, metric names are `Type 1 Departments - Major A&E` etc. |
| `Total emergency admissions` column | Absent from 2024-25 files; `adm_total_emergency` must be derived, not mapped |
| `Parent Org` column | Is the NHS England region, not the ICB, in every file checked. The ICB level needs the separate provider-to-system mapping file, which `discover` currently filters out by the keyword "mapping" |
| Internet Archive, file captures of `Monthly-AE-*.csv` | Only 32, mostly 2023 onward. Useless on its own |
| Internet Archive, year-page captures | Dense: dozens of captures per year page from 2017-18 |
| Revision magnitudes (5 pairs) | ≤2 providers changed per metric; national Δ under 1%; one outlier (Feb 2025, `att_other`, one provider +6,193) |

## Decisions to lock now (load-bearing structure)

These four contracts carry everything else. Get them right in week 2 and the rest is plumbing.

**1. Vintage semantics.** Add `available_from` to the manifest (the date the file became the current version), distinct from `snapshot` (folder key) and `fetched_at`. For live fetches `available_from = snapshot`. For recovered vintages, `available_from` is the stated revision date for revised files, else the first Wayback page capture in which the link appears (upper bound), with the second-Thursday publication rule as a cross-check. `latest_stored_per_period(as_of)` must filter on `available_from`, not `snapshot`. Without this, recovered files stored today look like they became available today.

**2. As-of loader.** One function, `load_asof(origin, mode) -> DataFrame[period, org_code, parent_org, target, value]`, used by every model and both evaluation modes. Structural point that simplifies recovery: a month's file is revised at the next May or November and then effectively frozen, so as-of and final differ only for periods published in the ~12 months before each origin. Recovery therefore needs every *original* from 2018-09 onward and the revised versions as they stood, not every version of every file.

**3. Forecast table contract.** Long table: `origin, mode, model, level, org_code, target, horizon, period, quantile, value`, plus a `sample` variant (`sample_id` instead of `quantile`) for R2 and M2. Every model writes this; the harness, reconciliation, decision layer and scorecard read only this.

**4. Hierarchy per origin.** Region from `parent_org` in the vintage current at origin. ICB from the mapping file for that release. Until the mapping file is ingested, evaluate provider → region → England and say so; do not fake ICB.

## Re-scope recommendation (your call, stated once)

Keep: B0, B1, B2, M1 with conformal intervals, R1 MinT on M1, decision layer, memo, monthly Action, Pages scorecard, handover, H1, H4 (reframed), H2 for M1's clause.

Move to a "phase 1b" milestone after 31 October: M2 at provider level (build it at ICB level only in phase 1, which §9 of the pre-registration already allows), R2 sample-path reconciliation, H3, H5, M3, Streamlit, UKHSA and Open-Meteo covariates. Rationale for the covariates: they are two data-engineering days each for an uncertain gain at monthly horizons 3 to 6, and they create as-of leakage risk of their own. Calendar and regime features are deterministic at origin and cost nothing.

If you keep the full scope, the honest forecast is that the 31 October forecast ships from a notebook rather than the Action, and Streamlit does not ship.

## Week plan (revised)

| Week | Deliverable | Done when |
|---|---|---|
| 1 (rest) | ~~`nhs-ae-ingest recover`~~ done 2026-09-08, with `coverage`, `available_from` in the manifest, legacy year-page slugs, XLS un-ignored (archive is 104 MB). Appendix A filled. | ✔ |
| 2 | ~~Legacy parser, as-of loader, harness, metrics, B0~~ done 2026-09-08 (`nhs-ae-backtest run`). B1, B2 and the revision audit (`nhs-ae-backtest audit`) done the same day. Left for week 2: the pre-registration amendments and freeze. As-of loader. Harness (rolling origins 2019-09 → 2025-09, both modes, identical code path). Metrics: WIS, pinball, coverage, MASE, PIT. B0/B1/B2. **Revision audit**: per period × metric, providers changed, national Δ, late-submitter count, as a table in the scorecard. Amend and freeze `prereg-v1`. | B0 scored in both modes at every origin; audit table committed; tag pushed |
| 3 | ~~M1 LightGBM quantile, direct multi-horizon, conformal on 12-month window~~ built 2026-09-09 with calendar and regime flags as features; hyperparameters are fixed defaults (tuning on pre-2019 origins not done, recorded in the amendments). Remaining: Type 3/UTC and field-testing flags, post-merger flag from ODS lineage, hierarchy S matrix. | ✔ M1 scored both modes 2026-09-09: H1 confirmed (MASE −28 to −35% vs B0), H2's M1 clause confirmed (coverage 0.76–0.83), H4 confirmed (final within 0.6% of as-of, same ranking). M1 does not beat ETS; see `docs/results.md`. |
| 4 | R1 MinT on B1/B2/M1. Decision layer: LoS lognormal, KH03 bed stock, P(occupancy > 92%), escalation beds at cost-loss grid. | Beds table for last winter's origins backtested against KH03 occupancy where available |
| 5 | M2 PyMC at ICB level (42 series × ~130 months, NB likelihood, shared Fourier seasonality). Time-box: two days. If it samples cleanly, try provider level; if not, stop. | Either provider-level M2 or a documented ICB-only fallback |
| 6 | Forecast job in the Action, Pages scorecard (as-of vs final side by side, calibration plots, audit table), memo draft from real numbers. | Action runs end to end on `workflow_dispatch` |
| 7 | Monitoring and drift triggers set from backtest distribution; handover pack; dry run of the live forecast from the October origin. | An analyst can run §2 of `handover.md` unaided |
| 8 | Write-up; live forecast Dec 2026–Mar 2027 published by 31 Oct. | Memo and scorecard public |

## Code fixes found (do in weeks 1–2)

- `src/nhs_ae/config.py:40` year-page URL: special-case the 2015-16 and 2016-17 slugs.
- `src/nhs_ae/ingest/parse.py:98` header detection: also accept a `code | region | name` row; merge a two-row header (group row + subheader) before mapping.
- `src/nhs_ae/config.py:83` header rules: add the pre-2019 XLS vocabulary (`Type 1 Departments - Major A&E`, `Type 2 Departments - Single Specialty`, `Type 3 Departments - Other A&E/Minor Injury Unit`, and the older admissions wording). Confirm exact strings against a 2016, 2017 and 2018 file when implementing. [recall, needs checking]
- `src/nhs_ae/config.py:77` `adm_total_emergency`: derive as the sum of the four admission columns when absent; make `validate_long` check the identity where both exist.
- `src/nhs_ae/ingest/discover.py:100` keyword filter: stop dropping "mapping" links; route them to a separate mapping ingest.
- `src/nhs_ae/ingest/download.py:119` `latest_stored_per_period`: filter on `available_from`.
- `.gitignore`: remove the XLS exclusions.

## Premortem

1. **PyMC eats weeks 5–6.** Time-box, ICB-level first, fallback already pre-registered.
2. **H4 comes back null and the pitch deflates.** The audit now exists and says value revisions are small (national totals move 0.06–0.15% on average) while late submissions are the larger as-of effect. Reframe before freeze: the deliverable is the measured leakage plus the infrastructure that measured it, and the audit table is a primary descriptive output alongside H4.
3. **ICB mapping missing.** Ship region-level hierarchy first; add ICB when the mapping file is ingested.
4. **Wayback throttling.** CDX queries took minutes today. Cache every capture and CDX response locally; run recovery once and commit the manifest.
5. **Live forecast not automated by 31 Oct.** The deliverable is the forecast and memo, not the Action. Keep a notebook path that produces both from `load_asof(today)`.

## Review points received 2026-09-09 and their status

1. Wayback coverage: already tested and resolved on day one; originals are live on the NHS server, 71/73 origins covered, Appendix A filled before the freeze. All six winters are usable.
2. Headline: H4 leads, beds are the "so what". README and scope rewritten. The transferable result is the *measured smallness* of revision leakage, not its presence.
3. §8 validation against published KH03 occupancy: added as a dated amendment with a tolerance (median |error| ≤ 5pp, 80% of trust-quarters within 10pp) before any decision-layer work.
4. H1 at 15%: confirmed for default M1 (−28 to −35% MASE vs B0), but M1 trails ETS on two targets. Write-up narrative: ML cleared the naive bar, not the classical one; revision leakage explains neither.

## What would change this strategy

- If 2020-21 or 2021-22 revisions turn out large (the COVID and booked-appointment period was not checked today), H4 regains its headline status and the covariate work becomes more important.
- If late-submitter fill-ins are common in some years (only one seen today, Oct 2024), the as-of effect may be material even though value revisions are not.
- If the pre-2019 XLS layout varies month to month, budget another day for the parser or restrict as-of origins to 2020-09 onward and record it in Appendix A.

## First three actions

1. ~~Write and run `recover.py`; fill Appendix A.~~ Done 2026-09-08.
2. ~~Legacy-layout parser.~~ Done 2026-09-08. 8 of 500 archived files remain unreadable (7 workbooks xlrd cannot open, each with a parsed CSV of the same month and vintage; 1 mislinked growth-rates file), listed in `data/processed/parse_failures.csv`. The as-of loader must skip those versions rather than fall through to revised data.
3. ~~As-of loader, harness, B0, B1, B2.~~ Done 2026-09-08 and run over all 73 origins. Provider level, winter, horizon 3, as-of mode: ETS cuts WIS by 46–54% and MASE by 28–42% relative to B0; STL+ARIMA by 34–46% and 15–32% (95% bootstrap intervals exclude zero for all). 90% coverage across horizons: B0 0.80, ETS 0.83, STL+ARIMA 0.79. On the corrected archive the final-versus-as-of WIS gap is within ±0.5% for every model and target, every bootstrap interval spans zero, and the model ranking is identical in both modes: H4 is heading for a null result. Files in `data/processed/backtest/`. Next: amend the pre-registration (H4 reframing, audit table, phase 1b split) and freeze `prereg-v1`.

## Out of scope for this document

Model architecture detail, feature lists beyond calendar and regimes, and anything in phase 2.
