# NHS A&E demand forecasting: project dossier (as of 2026-09-11)

> **Written 2026-09-11; superseded on every point the confirmatory run touched.** This
> dossier predates the run of 2026-09-15 by four days, and its own header says it was never
> independently fact-checked. Known to be wrong now: it says `conf-plan-v1` does not exist
> and the unseal log is empty (both tags exist; the log holds one line); that there is no
> forecast code and no `forecasts/` directory (`src/nhs_ae/live.py` and `forecasts/2026-09/`
> exist); that H5 is undecided (it is not evaluable, recorded before the tag); that H2's M2
> clause would fail by under-covering (it is refuted by **over**-covering, 0.97–0.99);
> "46 / 46" amendments (there are 83); "500 files" archived (720 versions); "117 availability
> dates" (121); and the NCtR occupancy figures at §467 (7.14 pp / 61.4% against the
> artefact's 7.1 pp / 49%). Read `docs/confirmatory_results.md` for the settled position and
> `site/REPORT.md` for the full list of corrections. It also cites the work order
> `CLAUDE_CODE_BRIEF.md`, which lives outside the repository and is not published with
> it, so those references cannot be followed here.

**Date:** Friday 11 September 2026. **Deadline:** live forecast for Dec 2026 to Mar 2027 published by 31 October 2026, a Saturday (docs/scope.md L26; ../CLAUDE_CODE_BRIEF.md L498).

| Item | Value |
|---|---|
| Reference branch | `merge-check`, HEAD `caa077b` (2026-09-11 10:06 +0100, "Stage F run (STOP 7)"): stages A0, A, D, G, E (to STOP 6), F |
| Main checkout | `nhs-ae-forecast`, branch `brief-stages` at `16d47dd` (= `m2-frozen-v1`) |
| Phase-1b branch | `m2f-redesign`, HEAD `b77430e` (2026-09-11 09:09 +0100): M2f-r2 to r4, **not merged** |
| Remote | `main` = `origin/main` = `48d9b0c` (2026-09-09); work-order branches are local only; tag push status unverified |
| Tags | `prereg-v1` → `4d9f2c0` (root commit, 2026-09-09 09:33:41 +0100); `backtest-v1` → `15ae475` (2026-09-09 11:49:38); `m2-frozen-v1` → `16d47dd` (2026-09-11 06:50:51); `conf-plan-v1` does not exist |
| Work order | `../CLAUDE_CODE_BRIEF.md` (the directory above the repo) |

Source: `git log -1` and `git tag -l` on both branches (checked 2026-09-11); `git for-each-ref`, `git worktree list` and `git branch -a -v` as recorded by the governance reader.

**Labels** (docs/results.md L3–17; docs/preregistration.md L187):
- *confirmatory under prereg-v1*: the default-M1 tests of H1, H2 (M1 clause) and H4, run once at `backtest-v1` on the old window (73 origins, 2019-09 to 2025-09). That window contains the 21 origins now sealed as CONF, so for Stage H these are re-tests, not confirmatory results.
- *seen before the freeze*: the B0–B2 results and the revision audit, computed on 2026-09-08 and disclosed at the freeze.
- *exploratory*: M1 tuned, v2 and v3, and everything the work order produced on DEV (docs/results.md L173).
- *registered design*: wording of the pre-registration or of an amendment row; not a result.

This dossier adds three marks of its own: *derived* (a number a reader computed from the named file, with the method given), *[inference]* (reasoning that was not checked) and *pending* (not yet done).

**Conventions.** Paths are relative to `merge-check` unless prefixed `m2f-redesign:`; `Lnnn` means a line at `caa077b`. A slice is given as split; months (winter = Dec–Mar targets, or all); horizon; level; mode; origins.

**Status of this file.** This dossier summarises and points to sources. It does not replace docs/preregistration.md or docs/results.md; where they disagree with it, they govern.

**How it was made, and what has been verified.** Ten reader agents extracted facts from the named sources and one writer agent composed this file. The independent fact-check pass (four checkers and a completeness critic) did not run, because it hit the usage limit twice. On 2026-09-11 Claude checked the following against the sources:
- the backtest-v1 numbers in §1 and Table 5.1a (bootstrap_tests.csv);
- H2's coverage by horizon and H4's largest gap;
- Stage D's selection table (stop4.txt);
- the frozen M2's ICB coverage by horizon (ladder_results.csv);
- the Stage F tables (Claude's own run);
- the Appendix A off-by-one (§3.2): the loader truncates 2018-11 and 2021-10 on DEV, and 2025-08 and 2025-09 on CONF, whose 2025-07 to 2025-09 originals first appear on 2025-11-13;
- the sequencing trap (§1 item 11);
- §5's phase rule for M2;
- Stage G's 2026-09-10 coefficient fit on quarters up to 2026-04;
- the identical M2d and `m2d_corr` fits (98 s against 49 min per fit, so contention);
- the calendar arithmetic.

Every one of these checks held. Three of the dossier's corrections to docs/results.md were confirmed and applied on 2026-09-11 (§5.7), together with a missing §10 row. Everything else is as the agents wrote it from the named sources and has **not** been independently verified. Check a number against its source before quoting it.

---

## 1. Executive summary

**Verdict.** The governance machinery works, and the pre-brief backtest delivered its registered tests. Almost every work-order stage on DEV has since returned a negative or mixed result, and nothing on the delivery path to 31 October exists. The binding constraint is a decision, not compute: Ellie has not chosen the live model, and that choice decides whether Stage H must run before the 8 October data release.

1. **Established, old window only.** Three registered tests passed (confirmatory under prereg-v1). Because the old window includes CONF, all are re-tests for Stage H (docs/preregistration.md L185, L187).
   - H1: M1's winter-h3 provider MASE against B0 is −34.7% [−40.9, −28.3] for admissions, −29.1% [−33.7, −25.1] for all types and −27.8% [−30.8, −25.2] for Type 1 (results/backtest-v1/bootstrap_tests.csv).
   - H2, M1 clause: M1's 90% coverage runs from 0.83 at h1 to 0.76 at h6 (results/backtest-v1/coverage_by_horizon.csv).
   - H4: all 12 final-versus-as-of intervals span zero, and the largest gap is −0.57%. H4-original is refuted, as predicted.
2. **ETS is the model to beat.** Every M1 variant trails ETS on winter-h3 WIS for admissions and Type 1. For v3, the gaps are +16.6% [+11.4, +21.9] and +12.6% [+8.1, +16.8] (results/m1-v3/bootstrap_v3_vs_others.csv; exploratory).
3. **No calibration method meets the acceptance criterion.** M1 + pooled conformal won only on the fallback rule: worst cell 4.7 pp, 21/30 cells in band (results/D-calibration/stop4.txt; exploratory).
4. **The bed layer failed.** Occupancy reconstruction has a median error of 8.7 pp, with 57% of trust-quarters within 10 pp; the tolerance was 5 pp and 80% (results/G-decision/occupancy_validation.md). Breach probabilities have a Brier score of 0.26–0.31, against 0.249 for the base rate (docs/results.md L237–240). The layer is illustrative only.
5. **M2 was frozen by override.** The retention rule rejected every rung above M2a (docs/preregistration.md L204). The frozen `m2d_corr` is 12.7% worse than raw ETS at ICB level, 0/35 fits meet the sampling targets, and England 90% coverage is 0.74 (results/E-m2/stop6.txt; exploratory).
6. **H3 fails on DEV** for all three bases. MinT worsens M1: ICB +11.1% [+10.2, +12.0] (results/F-reconciliation/h3_results.md; exploratory).
7. **Phase-1b candidate.** M2f-r4 is the only coherent contender near nominal coverage at every level outside COVID. It missed its registered WIS expectation, and it is not merged (m2f-redesign:docs/m2f_redesign.md L147–153).
8. **Data: solid, with one error.** The archive holds 500 files over 134 months, and revisions are tiny: national totals move 0.06–0.15% on average (results/backtest-v1/revision_audit.csv; derived). Appendix A names the wrong truncated origins (section 3.2; verified 2026-09-11).
9. **The delivery path is empty.** There is no forecast code and no `forecasts/` directory. The Action only ingests, and the A&E archive ends at the 2026-08-13 snapshot. Stage H has not run: a **draft plan** exists (docs/confirmatory_plan.md v0.3, written 2026-09-11, untagged), but there is no `conf-plan-v1` and the unseal log is 0 bytes. The 69-origin M2 re-run and Stage I are both pending.
10. **Time.** 50 days remain to the deadline. The 8 October release leaves 17 weekdays to Friday 30 October (derived).
11. **Sequencing trap [inference].** At the live origin 2026-10, pooled conformal calibrates on origins 2025-05 to 2026-09. Five of those are CONF origins, and every horizon touches sealed targets. The CLI refuses them without the `conf-plan-v1` token (docs/preregistration.md L216; src/nhs_ae/evaluate/cli.py L89–93). A conformalised live model therefore needs Stage H first.
12. **Decisions for Ellie** (section 9.4): the live model; the STOP 7 and STOP 8 records; whether M2f-r4 enters CONF; the Stage H hypothesis set; calibration guards; waivers for the Definition of Done; the I1 framing.

**Single next move:** Ellie chooses the live model and fixes the order of Stage H and the live run.

---

## 2. The project and its governance

**Verdict.** The design is sound and mostly honoured. Sections 1–9 of the pre-registration have not changed since the freeze, the seal is enforced in the scoring code, and most amendments predate their results. The weak points:
- an incomplete amendment log (section 8);
- a seal with gaps outside the scoring path;
- STOP decisions that were never recorded;
- a headline framing the evidence no longer supports.

### 2.1 Aim, targets, hierarchy, deadline

- **Aim:** a measured answer to whether backtesting on revised statistics overstates skill ("it does not, by at most 0.6%"). It rests on probabilistic provider-level monthly forecasts evaluated as-of, turned into a winter bed decision, and shipped with monitoring and a handover pack (docs/scope.md L3–8; README.md L3–9).
- **Targets** (registered design; docs/preregistration.md L22–29), at provider level, monthly, horizons 1–6:
  - all-types attendances = att_type1 + att_type2 + att_other, excluding booked appointments;
  - Type 1 attendances;
  - emergency admissions via A&E, summed over the three types.
- **Hierarchy.** Registered as provider → ICB (42) → region (7) → England (L33–35). Amended to the current 36 ICBs under §9, with 42 kept as a sensitivity check (L192). Stage F uses mapped providers → 36 ICBs → 7 regions → England (L213).
- **Backtest design** (registered; L57–64, L172): rolling origins with an expanding window. As-of mode is primary; final mode is the leakage diagnostic. The outturn is the latest revised value. Origin M is the second Thursday of month M, training data end at M−1, and horizon h targets month M−1+h.
- **Deadline.** Dec 2026–Mar 2027 forecast by 31 October (docs/scope.md L26). Memo numbers come from the 8 October release (docs/memo_draft.md L4–5).

### 2.2 The pre-registration

- **Freeze.** Frozen 2026-09-09 (`prereg-v1` on `4d9f2c0`). The prior look is disclosed: B0–B2 were run on every origin in both modes, and the revision audit was done on 2026-09-08 (docs/preregistration.md L3–11).
- **Sections 1–9 untouched.** `git diff prereg-v1 HEAD` shows +52/−0 lines, all in §10 and Appendix A (governance reader). §10 has grown from 7 rows to 46 (L172–217).
- **§9 change-of-course rules** (L159–164):
  - fewer than 4 usable as-of winters makes H4 exploratory;
  - M2 R-hat above 1.05 means reporting at ICB level only;
  - a broken mapping means using the current mapping and flagging it.
- **§8 decision layer** (L148–155): fixed national lognormal LoS, KH03 beds, breach at occupancy above 92%, cost-loss 0.1/0.25/0.5. The Stage G row (L217) replaced it with a trust-specific bed-days-per-admission model.

### 2.3 Work order and STOP gates

The brief sets nine STOP gates, forbids batching stages, and lets the pre-registration win conflicts (../CLAUDE_CODE_BRIEF.md L5–12).

| STOP | After | Artefact | Decision recorded in §10? |
|---|---|---|---|
| 1 | A | results/A-noise-floor/noise_floor.md | No row (C skip L188 and MMD rule L190 predate the result) |
| 2, 3 | B, C | none | Stages skipped (L188) |
| 4 | D | results/D-calibration/stop4.txt | Selection by registered rule (L216); no decision row |
| 5 | M2c | results/E-m2/stop5.txt | Partly (centring, L198); "M2 in the 31 Oct forecast?" still "Pending" (docs/results.md L263–264) |
| 6 | Ladder | results/E-m2/stop6.txt | Yes: freeze (L212), tag `m2-frozen-v1` |
| 7 | F | results/F-reconciliation/stop7.txt | No |
| 8 | G | results/G-decision/stop8.txt | Illustrative-only follows from L178; "does the memo ship" not recorded |
| 9 | Before unseal | none | Not reached |

**Batching.** Stage A's floor run was narrowed "with Stage D running at the same time" (L191). The A, D and G results were committed together in `300e1e7`. Stage E rungs were registered (`376ea5d`, `fbe9f93`) before the A/D/G results existed.

### 2.4 Amendment discipline

Every deviation gets a dated §10 row, written when the decision is made. Rows that describe results must be flagged (../CLAUDE_CODE_BRIEF.md L53–58). Most rows carry a qualifier such as "before any Stage D result". Brief conflicts were raised as rows (L187, L189, L190, L198, L200). Section 8 lists the gaps.

### 2.5 Splits and the seal

| Split | Origins | Count | Role |
|---|---|---|---|
| DEV | 2018-04 to 2023-12 | 69 | Development, search and selection; targets in 2024-01 to 2026-02 embargoed |
| CONF | 2024-01 to 2025-09 | 21 | Sealed; target embargo 2024-01 to 2026-02; scored once in Stage H |
| PROSPECTIVE | from 2026-10 | live | Docstring only; `SPLITS` holds dev and conf |
| Unassigned | 2025-10 to 2026-09 | 12 (derived) | Defined nowhere |

Source: src/nhs_ae/evaluate/splits.py L6–8, L38–43; tests/test_splits.py L41–44; docs/preregistration.md L184.

- **Mechanism.** `score_rows` calls `assert_not_sealed` and raises unless the token equals the `conf-plan-v1` commit. The harness drops embargoed targets and refuses CONF origins, and the CLI checks before fitting (splits.py L84–120; metrics.py L57–66; harness.py L106–133; cli.py L88–92, L211–215).
- **Unseal log.** The brief says to log every unseal call and to have exactly one entry at the end (brief L43–45). The code logs once per process per token (splits.py L46, L111–120), so a Stage H split across processes would write several lines.
- **Gaps in the seal** (governance and data readers).
  - Enforcement applies only to frames that have origin or period columns (metrics.py L65).
  - `summary --include-sealed` prints pre-seal CONF scores without a token (cli.py L163, L241–242). *Removed by P11 (2026-09-14): `summary` always drops sealed rows, and `run` no longer takes `--unseal-token` and refuses any sealed origin.*
  - Stage G uses hard-coded dates, and los_coefficients.csv holds a 2026-09-10 fit that uses sealed-window KH03 quarters (stage_g.py L103–106).
  - calibrate/, decide/ and reconcile/ never call the guard. *P11 (2026-09-14): `calibrate/online.py` now does, in `first_release` and `calibrate`, as does `stage_f._median_errors`.*
  - The token check does not verify that the confirmatory plan exists (splits.py L105–110).
- **CONF is sealed going forward, not unseen.** B0–B2 and all M1 variants were scored on CONF before the seal, and aggregates were read (for example, M1's coverage of 0.92 for 2025). CONF is a first test only for specifications created after 2026-09-10 (L185). In the old winter-h3 slice, 7 of 24 target months now sit in the sealed embargo (derived by the pre-brief reader).
- **§9 applied to CONF.** At h=3, CONF's winter slice has five origins (targets March 2024 and December 2024 to March 2025), so H4 is exploratory there. H1 and H2 carry a one-winter caveat (L186). The brief's "two winters" (L502–503) is superseded by this count.

### 2.6 Reporting conventions

The brief requires an interval with its resampling unit, an explicit slice, coverage by horizon and origin-year, and a README with a SHA for each stage (brief L60–71). The three-label scheme departs from the brief's "label everything exploratory" (L49–51); the reason is recorded at L187. Known deviations:
- Stage F has no origin-year coverage (coherence_vs_calibration.csv).
- The F2 WIS figures have no intervals (docs/results.md L417–422).
- The Stage E rule applies a provider-level MMD to ICB-level WIS.
- results/E-m2/README.md still describes M2a–M2c, and results/README.md omits F.

### 2.7 Stage-by-stage status

| Stage | Status | Evidence |
|---|---|---|
| A0 housekeeping | Done 2026-09-10 | `ac97817`; splits.py; docs/results.md L3–17 |
| A noise floor | Done (exploratory) | results/A-noise-floor/ (`c58be85`) |
| B structural search | Skipped by amendment | L188 (decision by Ellie) |
| C per-quantile tuning | Skipped by amendment | L188 |
| D calibration | Done; criterion unmet; fallback selection | results/D-calibration/ (`47da87d`) |
| G decision layer | Done; failed check, so illustrative | results/G-decision/ (`c58be85`); L178 |
| E M2 ladder | Done to STOP 6; `m2d_corr` frozen | results/E-m2/; L194–212 |
| E phase 1b (M2f-r2 to r4) | Done on a separate branch; not merged | `m2f-redesign` `b77430e` |
| F reconciliation | Done (exploratory); STOP 7 unrecorded | results/F-reconciliation/ (run `059a368`, committed `caa077b`) |
| H confirmatory run | Pending: draft plan only | docs/confirmatory_plan.md v0.3 (2026-09-11, untagged); no `conf-plan-v1`; results/unseal_log.jsonl 0 bytes |
| I write-up | Pending: memo draft only | docs/memo_draft.md |

### 2.8 Framing

The evidence now leans against the brief's framing.
- The scope, the README and docs/build_strategy.md L83 lead with H4 (revision leakage of at most 0.6%).
- The brief's I1 leads with overconfidence and "showed what it costs in beds" (brief L457–461). The bed half is unsupported (section 5.4).
- "~140 trusts" (brief L461) conflicts with "~180 providers" (docs/scope.md L102), with 251 mapped providers at 2018-04 (L215), and with the 232–240 provider series scored in Stage F.

---

## 3. Data and infrastructure

**Verdict.** The data layer is solid and the revisions are tiny, but two problems matter:
- Appendix A names the wrong truncated origins, because the coverage check and the loader date origins differently (verified 2026-09-11 from `data/processed/stage_d/forecasts_b1.parquet` and the archive's snapshot dates; the correction is item P10 of the draft plan).
- No code produces, calibrates or publishes the live forecast.

### 3.1 Sources

| Source | Coverage | Notes | Path |
|---|---|---|---|
| A&E monthly (NHS England), all vintages | 134 periods 2015-06 to 2026-07; 117 availability dates to 2026-08-13 | 500 files, 0 fetch failures; 1,068,583 parsed rows; 116 snapshots; 328 provider codes; 8 benign parse failures | data/raw/manifest.jsonl; data/processed/ae_monthly_all_vintages.parquet; parse_failures.csv |
| Provider → ICB mapping | System-Mapping-Apr-26.xls (valid from 2026-04-01) | 202 providers, 36 ICBs, 7 regions; 92 backfill rows; 35 of 328 codes unmapped (≤ 0.022% of admissions) | data/reference/provider_icb_map.csv, provider_icb_backfill.csv |
| KH03 G&A beds | 65 quarters, 2010-11 Q1 to 2026-27 Q1 | 27,842 rows; latest England occupancy 0.908532 (published 2026-08-20) | data/processed/kh03.parquet |
| Discharge sitrep (NCtR) | 53 months, 2022-04 to 2026-08 | 8,678 rows; latest England nctr_avg 22,741.71 | data/processed/discharge.parquet |
| §3 covariates (holidays, population, IMD, regime flags, UKHSA, weather) | none implemented | Only the UKHSA/weather deferral (L182) and the missing Type 3 flag (L199) are recorded | src/nhs_ae/features/`__init__.py`; L47–53 |

Source: data reader. The docs say "91 vintage dates" (L224; docs/build_strategy.md L9) and "263" Wayback captures (L266). The manifest has 117 dates and 264 captures.

### 3.2 Vintage recovery and Appendix A

- **Appendix A as registered** (seen before the freeze; L221–249; results/backtest-v1/vintage_coverage.csv):
  - 71 of 73 origins covered; exceptions 2021-11 (missing 2021-09) and 2025-09 (missing 2025-07);
  - an extension dated 2026-09-10: 24 of 26 covered for 2017-07 to 2019-08, with exceptions 2017-07 and 2018-12. The extension has no §10 row.
- **Mismatch.** `nhs-ae-ingest coverage` dates origins to the 1st of the month (src/nhs_ae/ingest/cli.py L126, encoded in tests/test_recover.py L163–167). The loader uses the second Thursday and trains to M−1 (src/nhs_ae/evaluate/asof.py L69–75, L151–158).

| Origin | Split | Appendix A | Loader's rule (replayed by the data reader) | Evidence |
|---|---|---|---|---|
| 2017-07 | burn-in | 2017-04 absent | covered | manifest (version dated 2017-07-13) |
| 2018-11 | DEV | not listed | 2018-10 missing | stage_d/forecasts_b1.parquet (h1 targets 2018-10) |
| 2018-12 | DEV | 2018-10 absent | covered | manifest (revision dated 2018-12-13) |
| 2021-10 | DEV | not listed | 2021-09 missing | backtest/forecasts.parquet; only_in_final 207 |
| 2021-11 | DEV | 2021-09 missing | covered | only_in_final 0 |
| 2025-08 | CONF | not listed | 2025-07 missing | only_in_final 201 |
| 2025-09 | CONF | 2025-07 missing | 2025-07 and 2025-08 missing | only_in_final 402 |

Source: docs/preregistration.md L223–249; data/processed/ae_monthly_all_vintages.parquet; results/backtest-v1/training_leakage.csv (only_in_final, att_all). The loader gives 70 of 73 origins covered, not 71 (derived). The governance and pre-brief readers reached the same off-by-one reading independently.

- **Lost originals.** The original releases for July, August and September 2025 are missing; the earliest archived versions are revisions dated 2025-11-13 (manifest).
- **H4 pairing [inference].** At truncated origins, as-of and final mode put the same horizon on different target months (origin 2021-10), contrary to the asof.py docstring (L19–21). This is unchecked.
- **Open question 2.** The brief's premise (brief L506–507) is wrong: Appendix A was populated on 2026-09-08. No §10 row closes the question.

### 3.3 Revision audit

**Revision audit.** Seen before the freeze. Slice: first vs latest version; 134 periods; provider rows. Shares and means derived.

| Measure | Months with value change | Change or late submitter | Mean providers changed | Mean abs. national change | Max (2022-05) |
|---|---|---|---|---|---|
| att_all | 77.6% | 79.1% | 2.75 | 0.153% | 2.05% |
| att_type1 | 60.4% | 67.2% | 1.60 | 0.064% | 2.57% |
| adm_via_ae | 56.0% | 62.7% | 1.33 | 0.068% | 2.29% |

Source: results/backtest-v1/revision_audit.csv. There are 0.57 late submitters per month. Appendix A's "63–79%" (L254) counts late submitters as changes.

- **Training leakage.** Seen before the freeze. Slice: 73 origins, trailing 12 months (results/backtest-v1/training_leakage.csv).
  - Share of provider-months changed: 0.628% (att_all), 0.418% (type1) and 0.306% (adm).
  - Final-only provider-months: mean 16.04, median 1, maximum 402.
  - 810 of the 1,171 final-only provider-months (69.2%) come from the three origins with lost originals (derived). That matters for H4b.
  - The audit covers origins from 2019-09 only.

### 3.4 As-of methodology

- **As-of rule.** As-of mode takes the latest version with `available_from` on or before the second Thursday. A missing latest month truncates training and shifts horizons. Final mode uses the latest versions; truth is the final series; there is no zero imputation (asof.py L5–26, L144–162; L172, L233–236).
- **Hierarchy.** It is not rebuilt as-of: current mapping throughout, a flagged departure (features/hierarchy.py; L174, L192).
- **M1's COVID flag** uses the retrospective 2020-03 to 2021-06 window (models/gbm.py L49, L88). This is hindsight, acknowledged only in passing (L205).
- **Live-ingest trap.** Without `--snapshot`, `available_from` is the run date. If the 8 October release were ingested late, origin 2026-10 would lose September and March 2027 would move to h=7 (ingest/cli.py L60, L156; asof.py L151–158).

### 3.5 Code, tests, automation

- **Code.** src/nhs_ae has 8,706 lines:
  - ingest: discover, download with a SHA-256 manifest, Wayback recovery, parse, ICB mapping, KH03, discharge;
  - evaluate: as-of loaders, audit, harness, metrics, splits, CLI, and the Stage A/D/E/F/G runners;
  - models: B0, ETS, STL+ARIMA, M1 LightGBM + CQR variants, EnbPI, M2 in PyMC/nutpie;
  - calibrate/online.py, reconcile/mint.py and decide/occupancy.py.
  app/ and monitor/ are docstring stubs (wc -l and module docstrings; data reader).
- **Tests.** 213 tests in 16 files across two environments. .venv-m2 collects 128, with 3 modules failing for lack of openpyxl; the main .venv collects 200. Only collection was run. README.md L39 still says "82".
- **Automation.** One workflow, `.github/workflows/monthly_ingest.yml`. It installs `.[xls]`, ingests, runs `pytest -q`, and commits data/raw only; the forecast job is a placeholder (L50–51).
  - The test step very likely fails, because without scipy the models, harness and calibrate modules do not import (simulated import; data reader).
  - There are no bot commits.
  - handover.md L10 wrongly says the workflow commits processed parquet files.
- **Shared state.** `data/processed` in both worktrees is a symlink to `nhs-ae-forecast/data/processed` (1.0 GB). `nhs-ae-backtest run` without `--out` overwrites the backtest-v1 files (cli.py L30, L80–111).

### 3.6 Live-forecast readiness

| Component | State | Source |
|---|---|---|
| Forecast entry point | Absent; handover says "(week 7)" | cli.py L204–246; docs/handover.md L18 |
| `forecasts/`, Pages, app, monitor | Absent or stubs | repo tree; src/nhs_ae/app, monitor |
| Action forecast job | Placeholder | monthly_ingest.yml L50–51 |
| Data for origin 2026-10 | Archive one release behind (latest snapshot 2026-08-13) | data/raw/ |
| Calibration at 2026-10 | Window overlaps the seal; online.py has no guard | L216; calibrate/online.py L43 |
| M2 live fit | `run_rung` returns the cached 35-origin table | stage_e.py L99–101 |
| ICB output via the CLI | `--levels` lacks icb | cli.py L218 |
| Memo, handover | Placeholders and TODOs | docs/memo_draft.md; docs/handover.md L32, L36, L49, L79 |
| Operational model | Contradictory: ETS (docs/results.md L151–152, L162–164) vs M1 + pooled (L201, L407; docs/memo_draft.md L54) | as cited |

---

## 4. Hypotheses scoreboard

| Hypothesis | Registered rule (short) | Evidence so far (slice; label) | Status | Stage H on CONF |
|---|---|---|---|---|
| **H1** | M1 provider MASE, winter h3, ≥ 15% below B0; refuted if the 95% CI includes ≤ 15% (L104–107) | −34.7%, −29.1%, −27.8% (adm, all, T1); every interval clears −15% (old window incl. CONF; winter; h3; provider; as-of; paired over providers; confirmatory under prereg-v1) | Confirmed | Re-test on 21 origins (5 winter at h3). Which M1 enters is not fixed: L176 says `m1`, L190 calls `m1_v3` "of record" |
| **H2, M1 clause** | Conformalised M1 predicted to miss 90% ± 5 pp at h ≥ 4; refuted if it meets the band everywhere (L111–114) | 0.827 → 0.761 at h1–h6 (old window; all months; pooled targets; provider; as-of; confirmatory under prereg-v1) | Confirmed; misses at every horizon | Re-test. In-model CQR or Stage D pooled? Not fixed |
| **H2, M2 clause** | M2 90% coverage within ± 5 pp at every horizon, pooled across *providers*; phase 1 only with provider-level sampling at R-hat ≤ 1.05 (L74, L109–114) | ICB only: `m2d_corr` 0.92, 0.84, 0.88, 0.84, 0.85, 0.84 (DEV 35 origins; all months; ICB; as-of; exploratory). 12/35 fits have R-hat > 1.05 (derived) | Not evaluated; level and phase unresolved; would fail at h2, h4, h6 on DEV [inference] | First test (L212), once the plan fixes level and phase |
| **H3** | R1/R2 improve ICB WIS (CI excludes 0) with provider WIS worsening ≤ 2%; ICB level and R2 in phase 1b (L116–119, L182) | ICB: ETS −53.1% (artefact), STL+ARIMA +0.3% [−1.5, +1.9], M1 +11.1% [+10.2, +12.0] (DEV; winter; h3; as-of; exploratory) | Fails on DEV for all bases; R2 untested | L213 (`merge-check` only) makes it confirmatory; L182 not revoked |
| **H4** | Final-mode winter-h3 provider WIS within 2% of as-of for every model, same ranking (L121–132) | All 12 CIs span 0; largest −0.57% [−1.58, +0.07] (old window; winter; h3; provider; M1 confirmatory, B0–B2 seen before the freeze) | Confirmed | Exploratory under §9 (L186); check the pairing at truncated origins first |
| **H4-original** | Ranking change, or a > 5 pp difference in improvement over B0 between modes; predicted refuted (L124–126) | Refuted as predicted (docs/results.md L68–70; same slice) | Refuted; no status after the split | Not in brief L440; status needed |
| **H4b** | Late-only months outweigh value changes at > half of origins; descriptive (L134–139) | 69.2% of final-only months come from lost originals (derived; seen before the freeze) | Decomposition never run (docs/results.md L157) | Not in brief L440; must separate lost files from late submitters |
| **H5** | Post-merger series: M2 beats M1 on WIS over 6 months; phase 1b (L141–144) | None; needs provider-level M2, which does not exist (L212) | Not evaluated | L184 and brief L440 put it on CONF, contrary to L182; decision needed |

---

## 5. Results by stage

### 5.1 backtest-v1 and the M1 line

**Verdict.** The registered tests came out as registered. ETS matched or beat every M1 variant, tuning found nothing, v2 collapsed coverage, and v3 became the LightGBM of record. Everything except the tuning search used the old window, which includes CONF.

**Table 5.1a. MASE relative to B0.** Slice: old window (73 origins, 2019-09 to 2025-09, incl. 21 CONF); winter; h3; provider; as-of; paired bootstrap over providers. The M1 column is the registered H1 test (confirmatory under prereg-v1); ETS and STL+ARIMA were seen before the freeze.

| Target | M1 | ETS | STL+ARIMA |
|---|---|---|---|
| Admissions | −34.7% [−40.9, −28.3] | −42.2% [−46.9, −36.8] | −31.7% [−39.7, −24.4] |
| All types | −29.1% [−33.7, −25.1] | −28.7% [−33.2, −24.3] | −15.5% [−20.7, −10.7] |
| Type 1 | −27.8% [−30.8, −25.2] | −29.8% [−33.1, −26.7] | −15.0% [−19.3, −11.2] |

Source: results/backtest-v1/bootstrap_tests.csv (test=vs_b0). STL+ARIMA would fail the H1 bar on attendances; results.md does not say so.

**Table 5.1b. H4: final-mode WIS relative to as-of.** Slice: as in 5.1a, paired.

| Target | B0 | ETS | STL+ARIMA | M1 |
|---|---|---|---|---|
| Admissions | −0.14% [−0.44, +0.03] | −0.39% [−1.17, +0.20] | −0.38% [−1.08, +0.07] | +0.08% [−0.18, +0.41] |
| All types | −0.01% [−0.09, +0.07] | −0.57% [−1.58, +0.07] | −0.42% [−1.23, +0.17] | −0.16% [−0.36, +0.02] |
| Type 1 | +0.02% [−0.07, +0.15] | +0.13% [−0.17, +0.36] | −0.06% [−0.30, +0.16] | −0.11% [−0.46, +0.15] |

Source: results/backtest-v1/bootstrap_tests.csv (test=final_vs_asof). The ranking check uses unpaired means over different row sets: M1 has 4,590 all-types rows and ETS 4,361 (backtest_summary.csv). On paired rows, M1 against ETS is +1.8% [−1.8, +5.3] (docs/results.md L38).

**Table 5.1c. 90% coverage by horizon.** Slice: old window; all months; pooled over targets; provider; as-of.

| Model | h1 | h2 | h3 | h4 | h5 | h6 |
|---|---|---|---|---|---|---|
| B0 | 0.8558 | 0.8364 | 0.8137 | 0.7936 | 0.7684 | 0.7457 |
| ETS | 0.8502 | 0.8397 | 0.8393 | 0.8378 | 0.8385 | 0.8450 |
| STL+ARIMA | 0.7599 | 0.7900 | 0.8038 | 0.8083 | 0.8136 | 0.8195 |
| M1 default | 0.8269 | 0.8104 | 0.8024 | 0.7910 | 0.7779 | 0.7613 |
| M1 tuned | 0.8309 | 0.8180 | 0.8091 | 0.7962 | 0.7836 | 0.7687 |
| M1 v2 | 0.6953 | 0.6380 | 0.6123 | 0.5911 | 0.5858 | 0.5702 |
| M1 v3 | 0.8371 | 0.8151 | 0.7997 | 0.7801 | 0.7612 | 0.7465 |

Source: results/m1-v3/coverage_by_horizon_all_models.csv; the first four rows match results/backtest-v1/coverage_by_horizon.csv. Every M1 variant also under-covers its 50% interval: 0.30–0.35 (default), 0.20–0.26 (v2) and 0.27–0.37 (v3) (same file). results.md never mentions this.

**Table 5.1d. WIS relative to ETS.** Exploratory, except that the default row comes from the registered run. Slice: old window; winter; h3; provider; as-of; paired.

| Variant | Admissions | All types | Type 1 |
|---|---|---|---|
| Default M1 | +20.8% [+15.0, +26.6] | +1.8% [−1.8, +5.3] | +7.3% [+2.5, +11.8] |
| Tuned | +20.1% [+14.5, +25.6] | +3.0% [−0.5, +6.4] | +8.5% [+3.6, +13.0] |
| v2 | +11.0% [+6.1, +15.3] | −2.4% [−6.0, +1.0] | +17.9% [+12.6, +22.7] |
| v3 | +16.6% [+11.4, +21.9] | +3.6% [+0.5, +6.6] | +12.6% [+8.1, +16.8] |

Source: default row from docs/results.md L38–39 only (no committed CSV); others from results/m1-tuning/bootstrap_tuned_vs_others.csv, results/m1-v2/bootstrap_v2_vs_others.csv, results/m1-v3/bootstrap_v3_vs_others.csv.

- **Tuning** (exploratory). 16 configurations on DEV origins 2018-04 to 2019-08 (all months; h1–h6; provider; as-of).
  - The winner scored WIS 300.19, just 0.03 below the runner-up.
  - The 9.18% spread is mostly the calibration window: 12-month configurations averaged 306.37, 24-month ones 322.53 (results/m1-tuning/m1_search.csv; derived).
  - Tuned against default: −0.5% [−1.2, +0.0], +1.0% [+0.6, +1.4] and +1.1% [+0.7, +1.6] (bootstrap_tuned_vs_others.csv; old window; winter; h3).
- **v2 and v3.** v2 (L176) fixed the h1 deficit (all-types h1 WIS ratio to ETS 0.98; results/m1-v2/wis_ratio_to_ets_by_horizon.csv) but collapsed coverage. v3 (L177) restored it. The switch rests on a single-origin ablation with no artefact (docs/results.md L118–124).
- **Live horizons.** At h4–h6, v3's WIS ratio to ETS is worse than default M1's on all three targets. For admissions it is 1.131, 1.151 and 1.181, against 1.107, 1.108 and 1.124 (results/m1-v3/wis_ratio_to_ets_by_horizon_all_m1.csv; all months; as-of). The live Dec–Mar targets sit at h3–h6 [inference].
- **What it changed.** ETS became the operational candidate (docs/results.md L149–153). v3 became the M1 for Stages A, D and F (L190, L213, L216). The re-split and the CONF disclosure followed (L184–185).
- **Untraceable figures.** No committed table backs:
  - default M1 vs ETS;
  - the 0.65 (2020) and 0.92 (2025) origin-year coverage (L55);
  - the ablation;
  - H4 for tuned, v2 and v3.
  Recomputing them would touch CONF.
- **Errata** (pre-brief reader).
  - ETS h6 coverage is printed as 0.85; the value 0.8450 rounds to 0.84 (L49).
  - "Within 0.5%" (prereg L130, L181) conflicts with −0.57%.
  - v3 does not "roughly tie" ETS on all types: +3.6% [+0.5, +6.6] (L146).
  - At h1, B0 is closer to nominal than ETS (L163).

### 5.2 Stage A: noise floor

**Verdict.** Seed noise is about 1% of WIS. Most of the 9% tuning spread comes from the calibration window, not the tree hyperparameters. Exploratory.

**Table 5.2a. Seed and configuration spread.** Slice: tuning origins 2018-04 to 2019-08; all months; h1–h6; provider; as-of; mean WIS over targets.

| Set | n | Mean WIS | SD as % of mean |
|---|---|---|---|
| Winning config, seeds 0–19 | 20 | 301.9 | 0.86% |
| All search configs | 16 | 311.4 | 2.81% |
| 12-month calibration configs | 11 | 306.4 | 1.30% |
| 24-month calibration configs | 5 | 322.5 | 1.46% |

Source: results/A-noise-floor/noise_floor.md L11–16. Seed 0 reproduces the winner's 300.1924 exactly (L18).

**Table 5.2b. Noise floor; MMD = 2√2 × seed SD.** Slice: DEV, 21 origins with winter h3 targets (2018-10 to 2023-10); winter; h3; provider; as-of; `m1_v3`; 20 seeds.

| Target | Mean WIS | Seed SD % | Mean cov90 | MMD ΔWIS | MMD Δcov90 |
|---|---|---|---|---|---|
| Admissions | 144.6 | 0.93% | 0.777 | 2.62% | 1.44 pp |
| All types | 605.0 | 1.03% | 0.854 | 2.91% | 1.03 pp |
| Type 1 | 579.0 | 1.20% | 0.764 | 3.40% | 2.68 pp |

Source: results/A-noise-floor/noise_floor.md L22–26; noise_table.csv.

- **Design.** Registered before any result (L190). The floor run was narrowed before any floor result existed (L191), but noise_table.csv still holds `slice=all` rows that L191 says were dropped.
- **Downstream use.** Stages D and E use cross-target means, 1.717 pp and 2.977% (shown as 1.7 pp and 3.0%). The registered rule says "per target and metric" (stage_g.py L393–399; stage_e.py L238–244).
- **For Stage I.** The I4 sentence "moved WIS by less than seed-to-seed noise" (brief L481–483) is false as worded. Within-window configuration SDs of 1.30–1.46% exceed the 0.86% seed SD (derived).

### 5.3 Stage D: calibration

**Verdict.** All ten candidates failed the acceptance criterion. M1 + pooled conformal was chosen by the fallback rule, not because it is calibrated. Pooling cells over targets hides admissions under-coverage. Exploratory; the design (L216) was registered before any result (`93a9630`).

**Table 5.3a. Acceptance criterion.** Slice: DEV; as-of; provider; origin-year × horizon cells pooled over targets; origin and target outside 2020-03 to 2021-06; 30 assessed cells; band 0.87–0.93.

| Candidate | In band | Worst cell (pp) | Min / max cell |
|---|---|---|---|
| **M1 + pooled (selected)** | 21/30 | 4.7 | 0.8584 / 0.9475 |
| M1 + DtACI | 17/30 | 5.9 | 0.8593 / 0.9594 |
| ETS + pooled | 14/30 | 8.3 | 0.8877 / 0.9828 |
| ETS + DtACI | 21/30 | 8.3 | 0.8646 / 0.9832 |
| M1 + per-series | 12/30 | 8.3 | 0.8851 / 0.9833 |
| ETS + per-series | 10/30 | 8.9 | 0.8879 / 0.9892 |
| M1 EnbPI | 6/30 | 11.6 | 0.7845 / 0.9032 |
| ETS raw | 5/30 | 14.1 | 0.7586 / 0.9639 |
| M1 v3 status quo (in-model CQR) | 1/30 | 16.8 | 0.7320 / 0.8725 |
| M1 raw | 0/30 | 34.4 | 0.5562 / 0.7502 |

Source: results/D-calibration/stop4.txt L95–105; pareto.csv.

**Table 5.3b. Winter-h3 WIS relative to raw ETS.** Slice: DEV; winter; h3; provider; as-of; COVID included; geometric mean over targets (gm).

| Candidate | gm | Candidate | gm |
|---|---|---|---|
| M1 + pooled | +10.9% | M1 + per-series | +33.6% |
| ETS + pooled | +10.2% | ETS + per-series | +25.5% |
| M1 + DtACI | +1142.5% | M1 EnbPI | +18.8% |
| ETS + DtACI | +5546.4% | M1 v3 status quo | +22.0% |
| ETS raw | 0 | M1 raw | +13.9% |

Source: results/D-calibration/stop4.txt L95–105. Per target, the selected method is +11.6% [+6.4, +16.8] for admissions, +10.6% [+6.9, +14.1] for all types and +10.6% [+5.0, +16.2] for Type 1 (wis_winter_h3.csv; paired over providers). Outside COVID (not registered), M1 + pooled is +7.0% and ETS + pooled +3.8% (wis_outside_covid.md).

**Table 5.3c. Selected method by origin-year × horizon.** Slice as in 5.3a. `*` marks a cell outside the band; parentheses mark a cell not assessed.

| Year | h1 | h2 | h3 | h4 | h5 | h6 |
|---|---|---|---|---|---|---|
| 2018 | 0.90 | 0.88 | 0.90 | 0.88 | 0.90 | 0.90 |
| 2019 | 0.86* | 0.88 | 0.86* | 0.88 | 0.87 | 0.88 |
| 2020 | (0.84) | (0.74) | | | | |
| 2021 | 0.91 | 0.94* | 0.95* | 0.94* | 0.93* | 0.92 |
| 2022 | 0.90 | 0.91 | 0.93 | 0.94* | 0.95* | 0.95* |
| 2023 | 0.90 | 0.92 | 0.92 | 0.91 | 0.90 | 0.91 |

Source: results/D-calibration/stop4.txt L5–12 (rounded to 2 dp).

**Table 5.3d. Selected method, 90% coverage per target.** Slice: DEV; all months; outside COVID; assessed cells; provider; as-of; n-weighted.

| Target | h1 | h2 | h3 | h4 | h5 | h6 |
|---|---|---|---|---|---|---|
| Pooled | 0.890 | 0.902 | 0.905 | 0.907 | 0.910 | 0.911 |
| Admissions | 0.872 | 0.875 | 0.879 | 0.880 | 0.882 | 0.886 |
| All types | 0.919 | 0.928 | 0.933 | 0.938 | 0.937 | 0.936 |
| Type 1 | 0.866 | 0.891 | 0.891 | 0.888 | 0.901 | 0.901 |

Source: recomputed for this dossier from results/D-calibration/coverage_by_horizon_year.csv (`m1_lightgbm_v3_raw+pooled`, region `assessable`, `assessed` True). Admissions has 12 of 30 cells below 0.87, the lowest 0.841 at 2023 h5.

*Disagreement resolved.* The readers gave admissions h1 as 0.869 or 0.872. Both reproduce: 0.869 includes the two non-assessed 2020 cells. With those cells included, the pooled row becomes 0.888–0.911, the figure docs/results.md L210 quotes. Either way, admissions coverage is 0.87–0.89, not the memo's "89–91%".

- **Tie-break.** Only M1 + DtACI falls within the 1.7 pp tie margin, and it loses on WIS (decision_loss.md L23). The choice holds at either extreme per-target MMD (derived). The top two candidates differ in WIS by less than the noise floor, so the choice rests on coverage.
- **DtACI.** At α ≤ 0 the rule reads the largest pooled score (online.py L177–178). The 97.5% bounds then reach 1,371,167,704 (ETS + DtACI, all types, winter h3). Blow-ups also occur before COVID: for 2018 origins, M1 + DtACI's mean WIS is 8.35 times pooled's (derived from data/processed/stage_d/scores.parquet). The "1.4 billion" and "1.09" figures in docs/results.md L216–217 refer to the ETS variants and have no committed artefact.
- **Correction.** docs/results.md L212 says every method over-covers for 2021–22. In fact M1 raw (0.56–0.68), the status quo (0.81–0.87) and EnbPI (0.80–0.90) under-cover (stop4.txt).
- **What it changed.** M1 + pooled became the selection. The G4 lower-bound label was triggered (L217; docs/memo_draft.md L16, L37).

### 5.4 Stage G: decision layer and memo draft

**Verdict.** The decision layer fails its registered check in every year and is illustrative only. Its breach probabilities have no skill. The memo is an unfilled draft. Exploratory.

**Model** (L217; src/nhs_ae/decide/occupancy.py L3–25). log(O·D/A) = log c_j + ε, where c_j is occupied bed-days per A&E admission.
- c_j is fitted per trust on its last 8 KH03 quarters, excluding COVID quarters and any quarter before a footprint break of more than 30%, then shrunk by empirical Bayes.
- The tolerance was registered on 2026-09-09, before any work on this layer: median absolute error ≤ 5 pp and ≥ 80% within 10 pp (L178).

**Table 5.4a. Registered occupancy check.** Slice: DEV KH03 quarters Apr–Jun 2018 to Oct–Dec 2023, outside COVID; trust-quarter.

| Variant | Trust-quarters | Median abs. error | Within 10 pp | Passes |
|---|---|---|---|---|
| National (fixed-LoS proxy) | 2,274 | 18.9 pp | 29% | no |
| Trust-specific (registered) | 2,274 | 8.7 pp | 57% | no |

Source: results/G-decision/occupancy_validation.md L13–22; stop8.txt L2.
- **By year.** 7.08–10.1 pp, with 50–65% within 10 pp; every year fails (L26–32).
- **Inside COVID.** 10.6 pp and 48% (L16).
- **NCtR variant.** Adds nothing on matched rows: 7.14 pp and 61.4%, against 7.31 pp and 62.0% (derived).

- **Persistence** (exploratory; not registered).
  - On acute trusts with an unchanged footprint, the reconstruction scores 8.49 pp and 0.58.
  - Latest published occupancy scores 2.38 pp and 0.955 on the same rows (occupancy_validation.md L36–41).
  - A persistence-based redesign is proposed but not registered (L43–47).
- **Breach probabilities.** Slice: DEV winter quarters, COVID excluded; origin two months before the quarter; trust; as-of; admissions.
  - M1 candidates score Brier 0.261–0.303 on 1,065 trust-quarters; ETS candidates 0.293–0.310 on 1,057. The base rate scores 0.2489 and 0.2491 (results/D-calibration/decision_loss.csv; derived). docs/results.md L237 wrongly gives 1,065 for all candidates.
  - A constant base-rate forecast also wins on mean cost-loss expense: 0.272–0.273, against 0.274–0.298 (derived).
- **Effect on Stage D.** None. No candidate met the criterion, so occupancy_validation.md L22's "falls back to WIS" never applied (stop8.txt L4).
- **Illustration** (origin 2023-10; December 2023; M1 + pooled; illustrative).
  - RP6: P(breach) 0.00, median occupancy 24.9%.
  - R1F: P 0.48, 91.6%, 24 escalation beds.
  - RBN: P 0.99, 131.9%, 436 beds.
  - 74 of 390 trust-months exceed 100% occupancy (stop8.txt L6–9; breach_probabilities.csv; derived).
- **Coefficients.**
  - Shrinkage moves estimates by at most 0.065 log units.
  - c_j reaches 9,298 bed-days per admission (RDR).
  - 25 of 154 trusts use bed counts more than two years old (los_coefficients.csv; derived).
- **Defect.** The "median error (pp)" column is actually the mean: 37.3, against a true median of 2.06 (stage_g.py L97 vs L325; derived).

**Memo** (docs/memo_draft.md, dated 2026-09-10, `87fef49`; pending). All cells and narrative placeholders are empty (L1–23). Citation status, verbatim:

| # | Memo text | Status marker in the memo |
|---|---|---|
| 1 | "(Bagust, Place & Posnett, *BMJ* 1999;319:155–8, doi:10.1136/bmj.319.7203.155)" (L42–44) | none |
| 2 | "(NG94, evidence review chapter 39)" (L45–47) | none; L217 requires verification before quoting |
| 3 | "(Friebel & Juarez, *Health Policy* 2020;124:1182–91, doi:10.1016/j.healthpol.2020.07.008)" (L48–49) | none; the brief says "Friebel et al." (L397) |
| 4 | "92% is used here because it is the NHS operational planning figure" (L50) | "[needs citation — search terms: NHS England operational planning guidance general and acute bed occupancy 92%]" |

Only commit `87fef49`'s message claims the sources were verified. Corrections needed:
- The "89–91%" figure (L26–28) is the all-target coverage.
- "About 6%" and "±14%" (L30–31) have no source table.
- "No better than" the base rate (L33) should say worse.
- "At the shortest horizon" (L37) omits 2019 h3.
- The LightGBM assumption (L54) contradicts results.md's ETS.

### 5.5 Stage E: the M2 ladder and the freeze

**Verdict.** M2 was frozen at `m2d_corr` by Ellie's decision. The registered retention rule had rejected every rung above M2a, M2d included; M2d went forward by an override recorded after its scores were seen (L204; results/E-m2/ladder_final.txt L96–102). The frozen model trails raw ETS, with every per-target lower bound above zero. Exploratory.

**Design (E0, L194).**
- Fitting: PyMC with nutpie, 4 chains × 1,000 + 1,000 draws.
- Evaluation: ICB level (36 ICBs), 35 even-month DEV origins, h1–h6.
- Reference: raw ETS at ICB level (stage_e.py L185–190).
- Retention rule: keep a rung only if gm winter-h3 WIS improves by more than 3.0% **and** the worst assessable cell improves.
- Only 10 assessable cells exist: 2019 h1–h3, 2022 h1–h6 and 2023 h1 (results/E-m2/coverage_by_horizon_year.csv).

**Table 5.5a. Rungs and verdicts.** WIS slice: DEV; 35 origins; winter; h3; ICB; as-of; gm over targets against raw ETS. The verdict column quotes the rule's own output, which combines that WIS change with the worst assessable coverage cell.

| Rung | One-line specification | gm WIS vs ETS | Retention verdict |
|---|---|---|---|
| M2a | Non-centred ICB intercept and slope; shared 3-harmonic Fourier; COVID and booked flags | +63.7% | Base |
| m2a_c | M2a centred, with data rule and direct all-types modelling | +60.0% | Base for M2d |
| M2b | + hierarchical Fourier | +64.6% | Rejected (+0.5%, −0.2 pp) |
| M2c_on_a | + dispersion by ICB and winter | +73.4% | Rejected (+5.9%, −0.3 pp) |
| M2d | Centred Student-t(4) random-walk level; no flags | +12.8% | Rejected (−29.5%, +1.2 pp); **carried by override** |
| M2d2 | + COVID-regime walk volatility | +48.1% | Rejected (+31.3%, −2.5 pp) |
| M2e_on_d | + ICB winter admission-rate term | +12.2% | Rejected (−0.5%, +0.0 pp) |
| **m2d_corr** | M2d fit + correlated t(4) ICB innovations after fitting | **+12.7%** | Frozen 2026-09-11 |
| M1 + pooled at ICB | Comparator | +18.1% | — |

Source: results/E-m2/ladder_results.csv; stop5.txt; stop6.txt; ladder_final.txt. Per target, `m2d_corr` is +11.7% [+5.8, +17.1] for all types, +10.6% [+4.4, +16.3] for Type 1 and +15.8% [+6.6, +25.7] for admissions. M2c_on_b was never built. M2f was not identified (L209–210). The ETS + pooled ICB comparator (+929.6%) is unusable because of a blow-up.

**Table 5.5b. 90% coverage by horizon.** Slice: DEV; 35 origins; all months; ICB; as-of.

| Rung | h1 | h2 | h3 | h4 | h5 | h6 |
|---|---|---|---|---|---|---|
| M2a | 0.82 | 0.80 | 0.79 | 0.79 | 0.77 | 0.78 |
| M2d = m2d_corr = M2e_on_d | 0.92 | 0.84 | 0.88 | 0.84 | 0.85 | 0.84 |
| M2d2 | 0.92 | 0.90 | 0.90 | 0.87 | 0.88 | 0.86 |
| M1 + pooled at ICB | 0.93 | 0.90 | 0.92 | 0.89 | 0.90 | 0.87 |

Source: results/E-m2/stop6.txt; ladder_results.csv. The worst assessable cells are M2a 7.8 pp (3/10), M2d and `m2d_corr` 9.1 pp (0/10), and M2d2 6.6 pp (2/10) (coverage_by_horizon_year.csv).

**Table 5.5c. Sampling.** 35 fits per rung; targets are R-hat < 1.01 and ESS > 400.

| Rung | Max R-hat (median) | Min ESS | Divergences | Fits on target | Min/fit |
|---|---|---|---|---|---|
| m2a | 1.077 (1.032) | 56 | 0 | 0/35 | 1.1 |
| m2a_c | 1.015 (1.006) | 249 | 0 | 33/35 | 0.8 |
| m2d | 1.122 (1.041) | 26 | 0 | 0/35 | 1.6 |
| m2d2 | 1.041 (1.018) | 154 | 0 | 0/35 | 2.5 |
| m2e_on_d | 1.098 (1.037) | 38 | 7 | 0/35 | 1.8 |
| m2d_corr | same fits as m2d | 26 | 0 | 0/35 | 48.9 |

Source: results/E-m2/M2*_diagnostics.md; stop6.txt. The per-origin diagnostics are identical for m2d and m2d_corr (data/processed/stage_e/diagnostics_*.csv).

**Table 5.5d. Aggregates from summed ICB draws.** Slice: DEV; 35 origins; all months; as-of.

| Model | England 90% / 50% | Region 90% / 50% |
|---|---|---|
| M2d, independent innovations | 0.40 / 0.16 | 0.70 / 0.35 |
| m2d_corr, correlated innovations | 0.74 / 0.44 | 0.80 / 0.47 |

Source: results/E-m2/m2f_aggregates.csv; stop6.txt L25–29.

- **Centring.** A two-origin probe showed centred effects mixing far better, with ESS 3,620 against 154 (parameterisation_probe.md). Ellie chose centring (L198). It fixed M2a's sampling but not the random-walk rungs.
- **Frozen spec** (L212; tag → `16d47dd`; no code change since run commit `aa56237`):
  - three negative-binomial series per ICB: Type 1, all types, and admissions with Type 1 as exposure;
  - centred t(4) walks with σ_rw ~ Gamma(4,100) and κ ~ Gamma(4,200);
  - no flags;
  - near-zero ICB-months treated as missing.
- **Known weaknesses registered at the freeze.** Sampling, calm-year over-coverage and aggregate under-coverage. Trailing ETS is not on the list.
- **Stage H carry-over (pending).** The 69-origin re-run has not happened: caches hold 35 origins. The recorded 48.9 minutes per fit, against 1.6 for the identical M2d fits (9.95 h against 0.34 h of wall-clock, derived), is contention. Verified 2026-09-11: per-origin R-hat and ESS are identical in diagnostics_m2d.csv and diagnostics_m2d_corr.csv.
- **Cautions.**
  - m2a_c is not a pure reparameterisation (m2.py L68): its all-types WIS moved from +60.7% to +49.8%.
  - The override's rationale ("written for under-covering models") does not fit a base whose worst cell was already over-coverage (0.978).
  - The M2a bias and M2d2 COVID-split figures in docs/results.md L255–257 and L312–317 have no artefact.

### 5.6 M2f redesign on `m2f-redesign` (phase 1b)

**Verdict.** The redesign yielded an identified, coherent model, but no variant met all its expectations, and 0/35 fits meet the sampling targets for each of r2, r3 and r4. The record is on an unmerged branch only. Exploratory; post-freeze.

**Table 5.6a. Identification** (development fits, not scored).

| Attempt | Change | R-hat / min ESS (2018-04; 2021-10) | Verdict |
|---|---|---|---|
| 1 | Sparse Cauchy national walk | 2.56 / 5; 2.55 / 5 (1.4–3.4 h per fit) | Failed |
| 2a | Seasonality fixed first; ICB walks centred afterwards | 2.92 / 5; 2.75 / 5 | Failed |
| 2b = M2f-r2 | Seasonality fixed first; zero-sum Helmert walks | 1.027 / 96; 1.069 / 47 | Registered, though short of the doc's own R-hat < 1.01, ESS > 400 bar |

Source: m2f-redesign:docs/m2f_redesign.md L28–35, L47–49, L55–56. Attempt 3 was never fitted (L64–68).

**Table 5.6b. ICB winter-h3 WIS vs raw ETS.** Slice: DEV; 35 origins; winter; h3; ICB; as-of; paired over ICBs.

| Model | gm | All types | Type 1 | Admissions |
|---|---|---|---|---|
| m2d_corr (frozen) | +12.7% | +11.7% | +10.6% | +15.8% |
| M2f-r2 | +27.2% | +17.9% | +24.6% | +40.2% |
| M2f-r3 | +3.8% | +3.6% [−1.3, +8.3] | +2.2% [−3.1, +6.9] | +5.5% [−1.9, +14.1] |
| M2f-r4 | +23.5% | +17.1% [+10.2, +23.6] | +17.5% [+9.8, +24.2] | +37.0% [+25.5, +49.4] |

Source: m2f-redesign:results/E-m2/ladder_results.csv; m2f_r4_icb.txt L39; M2f-r2 from `536f696`.

**Table 5.6c. Aggregate coverage from summed draws (90% / 50%).** Slice: DEV; 35 origins; all months; as-of.

| Model | Region | England |
|---|---|---|
| m2d_corr | 0.80 / 0.47 | 0.74 / 0.44 |
| M2f-r2 | 0.92 / 0.68 | 0.92 / 0.69 |
| M2f-r3 | 0.78 / 0.48 | 0.79 / 0.49 |
| M2f-r4 | 0.88 / 0.56 | 0.88 / 0.56 |

Source: m2f-redesign:results/E-m2/m2f_aggregates.csv (r2 from `536f696`). M2f-r4's England coverage by horizon is 0.87, 0.87, 0.95, 0.87, 0.84 and 0.90, so h3 and h5 fall outside 0.87–0.93.

**Table 5.6d. The same, outside the COVID window (90% / 50%).** Exploratory.

| Model | Region | England |
|---|---|---|
| m2d_corr | 0.91 / 0.56 | 0.85 / 0.52 |
| M2f-r2 | 1.00 / 0.82 | 1.00 / 0.84 |
| M2f-r3 | 0.96 / 0.61 | 0.97 / 0.63 |
| M2f-r4 | 0.90 / 0.52 | 0.90 / 0.52 |

Source: m2f-redesign:results/E-m2/m2f_r4_covid_split.csv; r2 from m2f_redesign.md L121–126. Inside the window, M2f-r4 covers 0.83 at 90% and 0.64–0.65 at 50%. M2f-r3 covers 0.31–0.34 and `m2d_corr` 0.49–0.53 (same file).

**Table 5.6e. Registered expectations.**

| Model | Expectation | Result | Verdict |
|---|---|---|---|
| r3 | 50% coverage moves towards 0.50 | 0.48–0.49 | Met |
| r3 | 90% coverage stays in 0.87–0.93 | 0.78–0.79 | **Not met** |
| r3 | Aggregate WIS below r2's | England 29,620 vs 36,058 | Met |
| r3 | κ mixes better | κ_all worst in 30/35 fits (27/35 before) | No verdict recorded |
| r4 | Aggregate 90% back in the band | 0.88 | Met (pooled) |
| r4 | Calm-period over-width reduced | 0.90 / 0.52 | Met |
| r4 | WIS no more than 3.0% worse than r3's | England +18.6%, region +14.9% (derived) | **Not met** |

Source: m2f-redesign:docs/preregistration.md L213–215; m2f_redesign.md L114–117, L147–153.

- **Sampling.** Median R-hat is 1.083 for r2, 1.080 for r3 and 1.079 for r4, with κ the worst parameter in almost every fit (M2F_R{2,3,4}_diagnostics.md).
- **Why r4 fails on WIS.** Very wide forecasts made inside COVID: ICB WIS against ETS is −0.1% [−7.6, +6.3] outside the window (8 origins) and **+88.6%** [+73.4, +105.9] inside (2 origins). *Corrected 2026-09-11:* the inside figure was first given as +91.7%, which cannot be reproduced. The split now has an artefact, `results/E-ensemble/covid_split_verification.md` (commit `9e2b0cc`), and `m2f_redesign.md` carries the same correction.
- **Status.** M2f-r4 is a candidate, neither frozen nor merged (L174–176). Each variant was registered before it was fitted (`fd0b59f`→`536f696`, `cea58c7`→`e96e172`, `613913a`→`b77430e`).
- **Gaps.**
  - The r2–r4 rows are not on `merge-check`.
  - docs/results.md on both branches stops at attempt 1 (L362–363).
  - F2 read r4's forecasts from a gitignored shared cache.
  - The HEAD result files have lost r2's rows.

### 5.7 Stage F: reconciliation and F2

**Verdict.** H3 fails on DEV for all three bases, and the ETS rows reflect a calibration blow-up. F2 supports the registered prediction that MinT buys coherence, not calibration. Exploratory. The design was registered before any Stage F result (L213–215; `bc6ca3c`, `0addd3d`).

**Design.**
- Bases: ETS, STL+ARIMA and M1 (`m1_v3_raw`), each pooled-conformal calibrated at its own level.
- Reconciliation: MinT-shrink applied one quantile at a time, then sorted and floored at zero, with a Schäfer–Strimmer W built from 36 origins.
- Unforecast providers: one "rest" node per ICB.
- H3 passes only if the ICB 95% interval lies entirely below zero and the provider point estimate is at most +2% (h3_results.md L3).

**Table 5.7a. H3, reconciled vs calibrated base.** Slice: DEV 2018-04 to 2023-12; winter; h3; as-of; paired over series.

| Base | Provider | ICB | H3 |
|---|---|---|---|
| ETS | +3449.1% [+1135.6, +6692.3] (232) | −53.1% [−94.7, +8.0] (36) | fails |
| STL+ARIMA | +2.7% [+1.1, +4.2] (232) | +0.3% [−1.5, +1.9] (36) | fails |
| M1 | +11.6% [+8.8, +14.8] (240) | +11.1% [+10.2, +12.0] (36) | fails |

Source: results/F-reconciliation/h3_results.md L7–18. The number of series is in brackets.
- **Region and England.** At region level: ETS −98.3%, STL+ARIMA −2.7% [−4.1, −1.1], M1 +2.8% [+1.6, +4.0]. The region-level H3 also fails for all three (derived).
- **Outside COVID** (a slice without the blow-up), MinT worsens ETS at every level, by +7.4% to +19.2% (h3_results.csv).

- **ETS artefact.**
  1. At origin 2020-05, ETS forecasts zero for 324 provider, 194 ICB, 45 region and 7 England rows.
  2. England's calibration pool holds at most 12 scores, so the upper adjustment equals the largest score.
  3. As a result, 6.0–9.1% of calibrated aggregate forecasts have a q97.5 above ten times the median, through 2021-10 (calibration_blowups.csv; h3_results.md L22).
  4. MinT then inflates 1,859 provider quantiles more than tenfold (docs/results.md L401–402; reproduced).

  The prose at docs/results.md L397–399 understated the scale. It said "about 9×10^10", but the largest England q97.5 is 4.78×10^12; 9.73×10^10 is the largest q95 (derived from data/processed/stage_f/). The implied log-scale score is about 14, not 13. *Corrected on 2026-09-11 in docs/results.md, h3_results.md and the report code.*
- **Bug.** A missing England forecast for M1 skipped the whole origin-horizon. It affected 153 of 1,242 origin-target-horizons and was fixed with a row-count guard in `d70d0a2`, before any tables were read (derived).

**Table 5.7b. F2: WIS relative to M1 + pooled.** Slice: 35 DEV ladder origins; winter; h3; as-of; no intervals.

| Model | ICB | Region | England |
|---|---|---|---|
| ETS + pooled | +790.7% | +1764.7% | +3432.1% |
| ETS + pooled + MinT | +600.4% | +382.4% | −21.6% |
| M1 + pooled + MinT | +23.1% | +13.9% | −14.4% |
| M2f-r4 | +4.7% | −2.4% | −26.7% |
| m2d_corr | −4.5% | −13.4% | −37.4% |

**Table 5.7c. F2: 90% coverage.** Slice: 35 DEV ladder origins; all months; h1–h6; as-of.

| Model | ICB | Region | England |
|---|---|---|---|
| ETS + pooled | 0.89 | 0.89 | 0.90 |
| ETS + pooled + MinT | 0.88 | 0.92 | 0.93 |
| M1 + pooled | 0.91 | 0.87 | 0.86 |
| M1 + pooled + MinT | 0.90 | 0.94 | 0.94 |
| M2f-r4 | 0.90 | 0.88 | 0.88 |
| m2d_corr | 0.86 | 0.80 | 0.74 |

**Table 5.7d. F2: 90% coverage outside COVID.** Slice: as in 5.7c, with origin and target outside 2020-03 to 2021-06.

| Model | ICB | Region | England |
|---|---|---|---|
| ETS + pooled | 0.93 | 0.92 | 0.93 |
| ETS + pooled + MinT | 0.93 | 0.99 | 1.00 |
| M1 + pooled | 0.94 | 0.91 | 0.90 |
| M1 + pooled + MinT | 0.93 | 0.99 | 1.00 |
| M2f-r4 | 0.93 | 0.90 | 0.90 |
| m2d_corr | 0.96 | 0.91 | 0.85 |

**Table 5.7e. F2: mean relative gap between an aggregate's median and the sum of its children's medians.** Slice: 35 DEV ladder origins; h1–h6; as-of.

| Model | ICB | Region | England |
|---|---|---|---|
| ETS + pooled | 3.98% | 0.58% | 0.30% |
| ETS + pooled + MinT | 3.84% | 0.54% | 0.50% |
| M1 + pooled | 2.98% | 3.58% | 3.61% |
| M1 + pooled + MinT | 0.49% | 0.03% | 0.02% |
| M2f-r4 | n/a | 0.12% | 0.06% |
| m2d_corr | n/a | 0.18% | 0.07% |

Source for 5.7b–e: results/F-reconciliation/coherence_vs_calibration.md L5–24 and .csv. The M1 England rows number 525, against 603 for the other models. docs/results.md L417 called this a "median gap", but it is a mean (*relabelled on 2026-09-11*).

- **Reference changed after results.** `059a368` switched the F2 WIS reference from ETS + pooled to M1 + pooled after the blow-up appeared. docs/results.md L377–378 discloses this. *A late §10 row was added on 2026-09-11, after this dossier flagged the gap.*
- **Implications** (docs/results.md L441–448). MinT stays out of the live path, M2f-r4 is preferred once phase 1b allows, and guards against 12-score pools and zero forecasts should precede the unseal. None of these is a recorded STOP 7 decision.
- **Citations.** MinT and the shrinkage estimator appear only as "[recall: … citations to verify before the write-up]" (src/nhs_ae/reconcile/mint.py L7–9). They are not in docs/memo_draft.md.

---

## 6. What did not work

This section is required by brief I2 (L463–465). "The H4 refutation" there means H4-original; the reframed H4 was confirmed.

1. **H4-original refuted, as predicted.** Revision leakage changed no ranking. The largest final-vs-as-of gap was −0.57% (results/backtest-v1/bootstrap_tests.csv).
2. **M1 never beat ETS** on admissions or Type 1 WIS: +11.0% to +20.8% and +7.3% to +17.9% (Table 5.1d).
3. **v2 coverage collapse.** 90% coverage fell to 0.70 at h1 and 0.57 at h6 (results/m1-v3/coverage_by_horizon_all_models.csv).
4. **Null tuning.** Tuned vs default moved WIS by −0.5% to +1.1%, and the winner led the runner-up by 0.03 WIS (results/m1-tuning/).
5. **M1's 50% intervals cover only 0.30–0.35** (results/backtest-v1/coverage_by_horizon.csv).
6. **No calibration method met the criterion.** The best worst cell was 4.7 pp (results/D-calibration/stop4.txt).
7. **DtACI blew up**: +1142.5% and +5546.4% WIS, with bounds up to 1.37 billion (results/D-calibration/pareto.csv; derived).
8. **Occupancy reconstruction failed**: 8.7 pp and 57%, against 5 pp and 80%, in every year (results/G-decision/occupancy_validation.md).
9. **Breach probabilities have no skill.** Brier scores of 0.261–0.310 against a base rate of 0.249 (results/D-calibration/decision_loss.csv).
10. **Rejected M2 rungs.** The rule rejected M2b, M2c, M2d, M2d2 and M2e. M2d survived by override (results/E-m2/ladder_final.txt L96–102).
11. **M2 sampling.** 0/35 fits met the targets for every random-walk rung, and the frozen model is +12.7% against ETS (results/E-m2/stop6.txt).
12. **M2 aggregates under-cover**: England 0.40 with independent innovations, 0.74 correlated (results/E-m2/m2f_aggregates.csv).
13. **M2f identification failures.** R-hat 3.2–3.5, then 4.03 (L209–210). Redesign attempts 1 and 2a reached 2.55–2.92 (m2f-redesign:docs/m2f_redesign.md).
14. **M2f-r3 and M2f-r4 missed registered expectations.** r3's coverage was 0.78–0.79; r4's WIS was +18.6% and +14.9% over r3 (Table 5.6e).
15. **H3 failed for all bases.** MinT worsened M1 by +11.1% at ICB and over-covered aggregates at 0.99–1.00 (results/F-reconciliation/).
16. **ETS calibration artefact.** Zero forecasts at 2020-05 and 12-score pools inflated up to 9.1% of England forecasts (calibration_blowups.csv).
17. **Appendix A off by one**: the loader truncates 2018-11, 2021-10, 2025-08 and 2025-09 (section 3.2).
18. **CI test step very likely fails** without scipy (section 3.5).
19. **Stage F row-count bug.** 153 of 1,242 M1 origin-target-horizons were skipped; caught before tables were read (`d70d0a2`).

---

## 7. Models and methods of record

**Verdict.** There is a selected calibration, a frozen M2 and a phase-1b candidate, but no live model of record.

| Model | Spec pointer | Strengths | Known weaknesses |
|---|---|---|---|
| ETS (B1), benchmark | L175 | Lowest winter-h3 WIS in D; best MASE vs B0 for admissions; named operational candidate (docs/results.md L150–153) | Raw worst cell 14.1 pp; calibrated version prone to zero-forecast blow-ups |
| M1 v3 raw + pooled conformal (Stage D selection) | L177, L216; models/gbm.py; calibrate/online.py (`POOLED_WINDOW = 12`) | Smallest worst cell (4.7 pp); pooled coverage 0.89–0.91 outside COVID | WIS +10.9% vs ETS; admissions 0.87–0.89 with 12/30 cells below 0.87; live window overlaps CONF |
| m2d_corr (frozen, `m2-frozen-v1` → `16d47dd`) | L212; models/m2.py; evaluate/stage_e.py | Sharpest in F2; coherent (0.07–0.18%); no calibration step, so no clash with the seal | +12.7% vs ETS; 0/35 fits on target; over-covers when calm, under-covers aggregates (England 0.74); 35 origins only; ICB only; frozen by override |
| M2f-r4 (phase 1b; not merged) | m2f-redesign: docs/preregistration.md L213–215, docs/m2f_redesign.md, src/nhs_ae/models/m2.py | Identified; aggregate 0.88; 0.90 / 0.52 outside COVID | WIS expectation missed; ICB +23.5% vs ETS; 0/35 fits on target; no shock mechanism (L171–173); not reproducible from `merge-check` |
| MinT-shrink reconciliation | L213–215; reconcile/mint.py; evaluate/stage_f.py; tests/test_mint.py | Coherence: M1 gaps 3.6% → 0.02–0.03% | Worsens M1; over-covers aggregates; spreads blow-ups; unregistered W fallback (`DEFAULT_REL_VAR = 0.01`, stage_f.py L49); left out of the live path without a §10 row |
| Decision layer (illustrative) | L148–155, L178, L217; decide/occupancy.py; evaluate/stage_g.py | Tolerance set in advance and honoured; honest labelling | Fails its check; no skill; shrinkage ineffective; stale beds; occupancy above 100% in 74/390 rows; route from trust to ICB memo unspecified [inference] |

Source: sections 5.1–5.7.

---

## 8. Amendment log summary

**Verdict.** The §10 log is extensive and mostly written before its results. It is also incomplete, partly out of order, split across branches, and some rows carry results. The full log is docs/preregistration.md §10 (L166–217).

| Set | Rows |
|---|---|
| `merge-check` / `m2f-redesign` | 46 / 46 |
| Shared (identical to `16d47dd`) | 43 |
| Only on `merge-check`: Stage F design, F2, implementation (L213–215) | 3 |
| Only on `m2f-redesign`: M2f-r2, r3, r4 (L213–215 there) | 3 |
| Distinct across both | 49 |
| At `prereg-v1` (5 pre-freeze, 2 at the freeze) | 7 |

Source: diff of the two files; `git show prereg-v1:docs/preregistration.md` (amendments reader).

| Theme | Rows | Decisions |
|---|---|---|
| Pre-freeze definitions | L172–175, L183 | Origin day; B0 intervals; region-only hierarchy; B1/B2; MASE scale |
| Freeze | L181, L182 | H4 reframed, H4-original kept, H4b added; phase-1b split (M2 time-boxed; R2, M3, H5, ICB-level H3, covariates deferred) |
| M1 line | L176, L177, L179, L180 | Defaults; tuning; v2 and v3 as exploratory |
| Decision layer | L178, L217 | Tolerance; Stage G design (edited in place at `47da87d`) |
| Work order | L184–L188 | Re-split; CONF disclosure; §9 on CONF; labels; B and C not run |
| Stages A and D | L189–L191, L216 | Assessable criterion; noise-floor design; floor narrowed; calibration selection rule |
| ICB and M2 ladder | L192–L212 | 36 ICBs; cold starts; E0; rungs; centring (L198); override (L204); M2f not identified (L210); `m2d_corr` (L211); freeze (L212) |
| Stage F / phase 1b | L213–215 on each branch | ICB-level H3, F2 / M2f-r2 to r4 |

- **Rows describing results** (brief §0.3), none of them flagged:
  - Change column: L210, L185, L186, L204, L212.
  - Reason column: L176, L177, L179, L181, L211, and m2f L214–215.
- **Hygiene.**
  - L183 and L216–217 are out of date order.
  - The Appendix A extension has no row, despite the L168 preamble.
  - L217 was edited in place.
- **Missing decision rows.**
  - STOP 4, 7 and 8.
  - The F2 reference change (*row added late on 2026-09-11*).
  - The §3 covariates dropped.
  - H4-original and H4b status.
  - H2's M2 level and phase.
  - H5 (L182 vs L184).
  - L182 revoked for ICB-level H3.
  - The Stage E provider-level MMD applied at ICB level.
- **Merge [inference].** Both branches added different rows after L212, so a conflict is almost certain. A merge must keep all six rows.

---

## 9. Pending work, decisions and risks

**Verdict.** The forecast can still ship by 31 October. Decisions and missing code gate it, not compute.

### 9.1 Critical path to 31 October

| Step | Owner | Timing |
|---|---|---|
| 1. Choose the live model, level and venue (D1); record STOP 7 and 8 in §10 | Ellie; agent writes the rows | Now; gates everything |
| 2. Fix the `run_rung` cache trap and the shared-state risk | agent | Before any M2 run |
| 3. Build the live entry point: as-of load at 2026-10, fit, calibrate, write `forecasts/`, aggregates, illustrative breach table | agent | 1–3 agent-days [inference] |
| 4. Archive the 2026-09-10 release with `--snapshot`; dry-run at origin 2026-09 | agent | The only rehearsal |
| 5. If the live model is conformalised: plan → STOP 9 → `conf-plan-v1` (pushed) → one-process Stage H | agent; Ellie authorises | Before 8 October [inference] |
| 6. 8 October: ingest with `--snapshot 2026-10-08`; run; QA; fill the memo; publish | agent; Ellie signs off | 17 weekdays to Friday 30 October |

Source: pending reader, from brief L360–365, L410–449, L487–498; stage_e.py L99–101; ingest/cli.py L60, L156.

**Compute** (derived; results/E-m2/M2D_diagnostics.md, M2D_CORR_diagnostics.md).
- At M2d's 98.4 s per fit, the 34 missing DEV origins take about 56 min serially (about 19 min on 3 workers).
- The 21 CONF origins take 34–49 min.
- Under the contention seen for `m2d_corr`, these become about 28 h and 17 h.

### 9.2 Stage H pre-flight

**Draft plan written.** docs/confirmatory_plan.md v0.3 (2026-09-11, untagged) turns the items below into pre-flight tasks P0–P14 and decisions D1–D7. The dossier's decisions in §9.4 map onto the plan as follows:

| Dossier (§9.4) | Plan |
|---|---|
| D1 (live model) and D7 (live calibration and sealed rows) | D5 |
| D4 (M2f-r4) | D1 |
| D5 (hypothesis set) | §3, §9, D6 (default `m1` carries H1, H2 and H4, as registered) and D7 (the duplicate origins 2025-07 to 2025-09) |
| D6 (guards) | G1 and D4 |

The plan's compute estimate uses M2d's 98 s per fit, as §9.1 does, not the contended 49 minutes.

- [ ] docs/confirmatory_plan.md, reviewed at STOP 9 with Ellie's written go-ahead, then tagged `conf-plan-v1` and pushed (brief L424–436).
- [ ] Frozen M2 re-run on all 69 DEV origins. L194 says "before Stage H"; L212 says "carried into" it.
- [ ] Zero-forecast and small-pool calibration guard, registered before the unseal. Decide whether it changes the STOP 4 method (docs/results.md L445–448).
- [ ] Hypothesis set fixed: H2's M2 clause (level and phase); which M1 and which calibration count for H1 and H2; the status of H4-original and H4b; H5; revoking L182 for H3.
- [ ] Whether M2f-r4 enters CONF (a first test; needs the merge and its rows).
- [ ] Appendix A correction as an amendment, since it changes the inputs at 2025-08 and 2025-09.
- [ ] A single-process unseal, for "exactly one entry".
- [ ] Caveats to state: 5 winter origins at h3; CONF already seen for B0–B2 and M1; CONF outturns may be revised on 12 November [inference].

### 9.3 Stage I (not started)

Missing:
- the write-up;
- the Pages scorecard (I3);
- the "What didn't work" section (I2; section 6 above has the material);
- the full amendment log (I2).

The I1 headline (section 2.8) and the I4 sentence (section 5.2) need rewriting. The corroboration citation the brief requires (L466–470) is absent from docs/ and from docs/memo_draft.md and is unverified, so it must not be used until checked. It is also framed there as "nothing beats seasonal naive", whereas here M1 and ETS beat B0 by 28–42% in MASE (Table 5.1a) [inference].

### 9.4 Decisions waiting for Ellie

1. **D1, live model and level**: M1 + pooled, ETS, frozen M2 at ICB level, or an ensemble. This gates the pipeline and the order of Stage H.
2. **D2, STOP 7**: MinT or built-in coherence for the live aggregates (the agent recommends leaving MinT out; docs/results.md L441–444).
3. **D3, STOP 8**: is the decision layer illustrative, and does the memo ship?
4. **D4**: merge `m2f-redesign`? Does M2f-r4 enter Stage H? After any merge, re-check that `m2d_corr` reproduces; m2.py gained 133 lines (`git diff --stat 16d47dd b77430e`).
5. **D5, the Stage H hypothesis set.** The brief (L440) conflicts with the pre-registration (L74, L141–144, L182), and the pre-registration wins (brief L11–12).
6. **D6**: calibration guards before the unseal.
7. **D7**: how live calibration may use sealed rows. Scoring them before the unseal would be an unlogged look [inference].
8. **D8**: waive or amend the unmet DoD items 3 and 4.
9. **D9**: the I1 framing and the trust count.
10. **D10**: publication venue; pushing branches and tags so that the `conf-plan-v1` timestamp is public (brief L431).
11. **D11**: which ICB(s) the memo covers (docs/memo_draft.md L1), and how trust-level breach probabilities appear in it.
12. **D12**: optional exploratory work (MinT without aggregates; capped DtACI; occupancy persistence). Each needs registering first, and none is on the critical path.

### 9.5 Definition of Done (brief L489–498)

| # | Item | Status |
|---|---|---|
| 1 | Seal guard; exactly one unseal entry | Partial: guard met; 0 entries (results/unseal_log.jsonl) |
| 2 | Noise floor used as MMD throughout | Partial: used in D and E as cross-target means; not in Stage F's prose (docs/results.md L431) |
| 3 | Specification curve | Not met: Stage B skipped (L188) |
| 4 | 0.87–0.93 at every horizon and origin-year on DEV | Not met: 4.7 pp best (stop4.txt); frozen M2 9.1 pp (stop6.txt) |
| 5 | M2 frozen and dated before Stage H | Met (L212; `m2-frozen-v1`) |
| 6 | Occupancy validated against KH03 with a stated tolerance | Check met (L178); reconstruction failed, so illustrative only |
| 7 | Confirmatory plan tagged before unsealing | Pending |
| 8 | Amendment log complete, every row a decision | Not met (section 8) |
| 9 | results.md separates exploratory from confirmatory | Largely met; stale at L155–169 and L263–264 |
| 10 | Live forecast published by 31 October | Pending; no code path |

### 9.6 Risks

| Risk | Evidence | Mitigation |
|---|---|---|
| Live path not built in time | No entry point; 17 weekdays | Build and dry-run before 8 October |
| Seal vs calibration sequencing | Pooled window at 2026-10 | Decide D1 and D7 now |
| Contention on the shared machine | Same fits took 9.95 h vs 0.34 h | No phase-1b jobs during Stage H or the live run |
| Stale cache or overwrite | stage_e.py L99–101; shared `data/processed` | New output paths; fix `run_rung` |
| Ellie's time | About 2 days a week (docs/build_strategy.md L12); 12 decisions | Take the decisions in one sitting |
| Memo credibility | 89–91% is the all-target figure; unsourced "6%" and "±14%"; 92% needs a citation | Correct before filling |
| Split log and F2 reproducibility | Rows on one branch; r4 forecasts in a gitignored cache | Merge deliberately, or pin the draws |
| H2's M2 clause likely fails | ICB coverage 0.84 at h2, h4, h6 [inference] | Fix level and phase in the plan |
| CONF thin and already seen | 5 winter origins; L185 | State as a limitation |
| Tags only local; CI failing; Appendix A error | `origin/main` at `48d9b0c`; `.[xls]`; section 3.2 | Push tags; install `.[dev,xls]`; amendment |

---

## 10. Source index

**Governance.**
- ../CLAUDE_CODE_BRIEF.md (L5–12, L43–71, L119–122, L360–365, L397, L410–510).
- docs/preregistration.md (§1–§9 L22–164; §10 L166–217; Appendix A L221–270).
- docs/results.md; docs/scope.md; README.md; docs/build_strategy.md; docs/handover.md.
- src/nhs_ae/evaluate/{splits,metrics,harness,cli}.py; tests/test_splits.py; results/unseal_log.jsonl; results/README.md.
- Commits `4d9f2c0`, `ac97817`, `300e1e7`, `caa077b`. Tags `prereg-v1`, `backtest-v1`, `m2-frozen-v1`.

**Data and infrastructure.**
- data/raw/manifest.jsonl.
- data/processed/{ae_monthly_all_vintages, ae_monthly_latest, kh03, discharge}.parquet; data/processed/parse_failures.csv; data/processed/stage_d/forecasts_b1.parquet; data/processed/backtest/forecasts.parquet.
- data/reference/provider_icb_*.csv.
- src/nhs_ae/ingest/{cli,recover,download}.py; src/nhs_ae/evaluate/{asof,audit}.py; src/nhs_ae/features/; src/nhs_ae/models/{gbm,statistical,`__init__`}.py.
- tests/test_recover.py; pyproject.toml; .github/workflows/monthly_ingest.yml.

**backtest-v1 and M1.**
- results/backtest-v1/{bootstrap_tests, backtest_summary, coverage_by_horizon, revision_audit, training_leakage, vintage_coverage}.csv.
- results/m1-tuning/{m1_search, bootstrap_tuned_vs_others}.csv; results/m1-v2/{bootstrap_v2_vs_others, wis_ratio_to_ets_by_horizon}.csv; results/m1-v3/{bootstrap_v3_vs_others, coverage_by_horizon_all_models, wis_ratio_to_ets_by_horizon_all_m1}.csv.
- Commits `15ae475`, `e2c1654`, `e98b618`, `8fb6a3b`, `10414d6`, `48d9b0c`.

**Stage A.** results/A-noise-floor/{noise_floor.md, noise_table.csv, seed_runs.csv}; src/nhs_ae/evaluate/noise.py; `9ae74ef`, `c58be85`.

**Stage D.**
- results/D-calibration/{stop4.txt, pareto.csv, wis_winter_h3.csv, wis_outside_covid.md, coverage_by_horizon_year.csv, decision_loss.md, decision_loss.csv}.
- data/processed/stage_d/scores.parquet; src/nhs_ae/evaluate/stage_d.py; src/nhs_ae/calibrate/online.py.
- Commits `93a9630`, `47da87d`.

**Stage G and memo.**
- results/G-decision/{stop8.txt, occupancy_validation.md, occupancy_validation.csv, los_coefficients.csv, breach_probabilities.csv}.
- src/nhs_ae/decide/occupancy.py; src/nhs_ae/evaluate/stage_g.py; docs/memo_draft.md; docs/memo_template.md.
- Commit `87fef49`.

**Stage E.**
- results/E-m2/{stop5.txt, stop6.txt, ladder_final.txt, ladder_results.csv, coverage_by_horizon_year.csv, M2*_diagnostics.md, m2f_aggregates.csv, parameterisation_probe.md, wis_outside_covid.md}.
- data/processed/stage_e/diagnostics_*.csv; src/nhs_ae/models/m2.py; src/nhs_ae/evaluate/stage_e.py.
- Commits `376ea5d`, `fbe9f93`, `524c689`, `328c844`, `8d600bf`, `53c774d`, `aa56237`, `16d47dd`.

**M2f (branch `m2f-redesign`).**
- docs/m2f_redesign.md; docs/preregistration.md L213–215.
- results/E-m2/{M2F_R*_diagnostics.md, m2f_r*_icb.txt, m2f_r4_covid_split.csv, m2f_aggregates.csv, ladder_results.csv}.
- nhs-ae-forecast/data/processed/stage_e/{diagnostics_m2f_r*.csv, forecasts_m2f_r4.parquet}.
- Commits `fd0b59f`, `536f696`, `cea58c7`, `e96e172`, `613913a`, `b77430e`.

**Stage F.**
- results/F-reconciliation/{stop7.txt, h3_results.md, h3_results.csv, coherence_vs_calibration.md, coherence_vs_calibration.csv, calibration_blowups.csv}.
- data/processed/stage_f/; src/nhs_ae/reconcile/mint.py; src/nhs_ae/evaluate/stage_f.py; tests/test_mint.py.
- Commits `bc6ca3c`, `0addd3d`, `d70d0a2`, `059a368`, `caa077b`.

**Pending.** results/E-m2/M2D_diagnostics.md, M2D_CORR_diagnostics.md; data/processed/stage_e/m2d/ and m2d_corr/ (file modification times); data/raw/ listing; `git diff --stat 16d47dd b77430e`.
