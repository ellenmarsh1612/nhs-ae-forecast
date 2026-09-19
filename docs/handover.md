# Handover pack (skeleton — completed in week 7)

Written for an ICB or trust analyst who has to keep the forecasts running without the
author. Every section answers one operational question. Keep it short; link to code.

## 1. What runs, when

| Job | Trigger | What it does | Output |
|---|---|---|---|
| `monthly-ingest`, job `ingest` (GitHub Action) | daily 11:00 UTC, days 8–21 | archives the current and previous financial years' files as a dated snapshot (`--snapshot` = run date), rebuilds the parquet **on the runner only**, runs the tests, and commits `data/raw` if the archive changed. `data/processed` is gitignored and never committed | `data/raw/<date>/` and `data/raw/manifest.jsonl` (committed) |
| `monthly-ingest`, job `forecast` | the second Thursday, after a new vintage is archived; or by hand (`workflow_dispatch`, `forecast: true`) | rebuilds the processed data from the archive, runs `nhs-ae-forecast live` for that month's origin with both models (`ets`, the live model, and the `m2f_r4` shadow), writing to `ci_forecasts/`, and uploads that directory. It does not commit or publish | artifact `forecast-<model>-<date>` |

Every scheduled run also records the files it saw again as "sightings" in the manifest (stored:
false, no new file), so on days 8–21 the bot commits `archive: vintage <date>` even when nothing
was published.

## 2. How to run it by hand

```bash
make install
nhs-ae-ingest run --snapshot YYYY-MM-DD      # archive the release; the date is the release day
nhs-ae-forecast live --origin YYYY-MM --snapshot YYYY-MM-DD --model m2f_r4   # and --model ets
```

The ingest needs the `xls` extra (xlrd, openpyxl); without them the build now refuses to
run instead of silently dropping every workbook. M2f-r4 needs the `models` extra (PyMC,
nutpie). One environment runs everything: `.venv-m2`, pinned in `requirements-lock.txt`
(Python 3.13, macOS arm64). To recreate it:

```bash
python3.13 -m venv .venv-live
.venv-live/bin/pip install -r requirements-lock.txt
.venv-live/bin/pip install -e . --no-deps
```

A fresh environment built this way on 2026-09-12 passed all 241 tests and reproduced
`forecasts/2026-09` bit for bit, for both models.

## 3. Backfill

- `nhs-ae-ingest build` rebuilds every parquet from `data/raw/` alone, no network.
- `nhs-ae-ingest recover` rebuilds the pre-archive version history from the Internet
  Archive. It is idempotent (URLs already in the manifest are skipped) and caches every
  Archive response under `data/cache/wayback/`, so re-running after a failure is cheap.
  Pass `--years` to limit it; `--redo` to re-process; `--delay` to be gentler on the
  Archive.
- `nhs-ae-ingest coverage --origins 2019-09 2025-09` lists, per origin, the periods for
  which no version that was current at that origin exists. That list is Appendix A of
  the pre-registration; do not fill the gaps with revised data.
- *TODO week 7.* How to re-run a forecast from an earlier origin.

## 4. Retrain

*TODO.* Retraining is automatic at every origin. Hyperparameters are refreshed only if
the drift triggers in §6 fire; the procedure and validation window are described here.

## 5. Revisions

- May and November: NHS England publishes revised files (new URL, new link label). The
  ingest job stores the new version under that day's snapshot; nothing is overwritten.
  Every manifest line carries `available_from`, the date that version became current.
- After a revision, the scorecard's *outturn* values change for the revised months.
  This is expected. The as-of forecasts do **not** change.

## 6. Drift triggers (re-forecast / investigate)

*TODO week 7 — to be set from the backtest distribution.* Planned triggers:
- rolling 3-month bias at England level outside ± X%;
- 90% interval coverage over the last 6 origins below Y%;
- any provider whose latest outturn is outside its 99% interval two months running;
- a new `unmapped__` column appearing in the ingest log (schema drift).

## 7. When a trust is missing

Missing submissions are stored as NaN. Aggregates are missingness-aware and carry a
count of missing providers. Do **not** fill with zero. If a trust is missing for three
consecutive months, check the NHS England statistical commentary for the reason.

## 8. When trusts merge

Run the lineage step (`nhs_ae.ingest.lineage`) to refresh the canonical code map. The
merged series is treated as a cold start; the hierarchical model's partial pooling
provides the prior. Record the merger in `docs/lineage_log.md`.

## 9. When a feed breaks

Symptoms and first checks:
- `unmapped__` columns in the ingest log: NHS England renamed a column. Add a rule to
  `HEADER_RULES` in `config.py`; the joined "group sub-header" text is what the rule sees.
- "no recognised metric columns": the page links the wrong file (it has happened). Check
  the link on the NHS England page; the file is archived but ignored.
- "Could not locate header row": a new physical layout. `parse._read_raw` documents the
  three known ones.
- `data/processed/parse_failures.csv` lists archived files the reader cannot open; a
  workbook there is harmless if the CSV of the same month and vintage parsed.
- Run with `--years 2026-27` to limit a re-run to the current year.
*TODO week 7:* who to contact.

## 10. Contacts and licences

Data: NHS England, Open Government Licence v3.0. Code: MIT.

## 11. Operational risks

*Hypotheses, not findings. No test is attached to either mechanism.*

- **M2's sampling degrades with origin date.** Across the 69 DEV origins, the frozen M2's
  median max R-hat rises from 1.015 (2018–19) to 1.069 (2023). Its median min bulk ESS falls
  from 199–229 (2018–19) to 63 (2023) (`results/E-m2-rerun69/`). At three late origins the
  forecast quantiles were nonetheless stable across seeds
  (`results/E-m2-rerun69/seed_stability/`). Two candidate mechanisms:
  - **(a) The expanding training window.** Each origin fits a longer series. If this is the
    cause, sampling will go on degrading in production indefinitely.
  - **(b) The COVID break entering the training window.** From 2021, every fit has to absorb
    the 2020–21 break. If this is the cause, sampling will stabilise as the break becomes a
    smaller share of the series.

  The largest step lies between 2018–20 (1.015–1.026) and 2021 (1.047). That is consistent with
  (b) but does not establish it. Two facts cut against each mechanism taken alone: the flat
  pre-COVID years (1.015 in both 2018 and 2019) against (a), and the further rise in 2023
  (1.052 to 1.069) against (b).

## 12. Runbook: the 8 October 2026 run, end to end

The first live forecast is made from origin **2026-10**: data fetched on the release day,
Thursday 8 October 2026, training to September 2026. The winter months December 2026 to
March 2027 are h3–h6. The live forecast is **uncalibrated**: M2f-r4's posterior intervals, or
ETS's native intervals. Never add a conformal wrapper on this path. It would need calibration
pools of sealed rows, and that puts the whole of Stage H in front of the deadline.

**Before 8 October (all of these block the run):**
1. The code is on `main`, the branch scheduled Actions run. `main` was fast-forwarded to
   `merge-check` on 2026-09-12. The bot commits archive changes to `main` on days 8–21, so do
   further work on `main`, or merge `main` in before pushing. Otherwise the Action runs stale
   code.
2. D1 is settled. On 2026-09-12 it came out **EXCLUDE** (`results/E-m2f-69/`), so the live model
   is **raw ETS** and `m2f-r4-frozen` does not exist. The M2f-r4 path still runs, as a shadow,
   in case D1 is revisited; its manifest records that the tag is absent.
3. **Environment (done 2026-09-12).** Run both the ingest and the live command in `.venv-m2`,
   or in a fresh environment built from `requirements-lock.txt` (section 2). This is the
   environment that makes the record run; the ingest refuses to build without xlrd and openpyxl.
4. **Stage H and publication.** The ship rule (`docs/d1_precommitments.md` (c)) applies only if
   D1 = include, because it tests M2f-r4 on CONF. Under EXCLUDE, raw ETS is uncalibrated and
   needs no calibration pool, so publishing it does not wait for Stage H. Stage H still runs for
   the confirmatory claims. Publish with raw ETS's known limitation stated: its upper tail fails
   (PIT top bin 1.74× over 69 DEV origins, 1.90× over 35).

**On 8 October:**
1. 09:30 UK: NHS England publishes the September 2026 data.
2. 11:00 UTC: the Action archives snapshot 2026-10-08, runs the tests, commits `data/raw`,
   then runs the forecast job for both models and uploads `forecast-<model>-2026-10-08`.
3. If the Action fails, or `main` lacks the code, do the same by hand:
   ```bash
   nhs-ae-ingest run --snapshot 2026-10-08
   python -m nhs_ae.ingest.kh03 build
   nhs-ae-forecast live --origin 2026-10 --snapshot 2026-10-08 --model m2f_r4
   nhs-ae-forecast live --origin 2026-10 --snapshot 2026-10-08 --model ets
   ```
4. **Check the ingest.**
   - `data/raw/manifest.jsonl` has a stored row with `available_from` 2026-10-08 for the
     September 2026 file.
   - The build logged no more than the known 8 unparseable files
     (`data/processed/parse_failures.csv`).
5. **Check each forecast.** It prints `FORECAST WRITTEN: forecasts/2026-10/<model>`.
   - Exit code 2 means a ship-blocking check failed. The reasons are printed and written to
     `forecasts/2026-10/<model>__REJECTED/manifest.json`. **Do not override them.** The most
     likely cause is a vintage that is missing or mis-dated.
6. **Read `manifest.json`.**
   - `training_ends` is 2026-09.
   - `periods` h3–h6 are 2026-12 to 2027-03.
   - `snapshot` is 2026-10-08.
   - `coherence_gap` is under 1% at region and England.
   - `sampling` gives R-hat, ESS and divergences. They are reported and exclude nothing.
7. **Commit** `forecasts/2026-10/` for both models: the dated record. Do not edit it afterwards.
   A re-run goes to a new directory, since the command never overwrites.
   - **The record is the by-hand run** in the analyst's pinned environment. `manifest.json`
     records the environment.
   - The Action's artifact is a cross-check. It agrees within seed noise, not bit for bit.
     On 2026-09-12 a Linux runner gave ETS quantiles up to 3.9% from the macOS run, and a
     different M2f-r4 chain from the same seed (run 34683377113).
8. **Publish** raw ETS (`forecasts/2026-10/ets`), with its upper-tail limitation stated. The
   M2f-r4 output is kept as an unpublished shadow. The trust breach table carries its
   illustrative label and failed validation in every row, and ships only with them.

**Rehearsal, 18 September 2026 (code `cf007d3`).** The whole live path was re-run at origin
2026-09, snapshot 2026-09-10, for both models, into a scratch directory, and compared with the
committed 2026-09 dry run (made on 12 September at `9a17011`):

- **Both models reproduce bit for bit.** All 7,128 quantile rows match for ETS and for
  M2f-r4, with identical coherence gaps and identical sampling diagnostics (R-hat 1.090,
  minimum bulk ESS 29, no divergences, 89 s). `checks_failed` is empty for both. So the ~25
  commits of Stage H work since 12 September changed nothing on the live path.
- **`.DS_Store` was making the manifest report a dirty tree.** The rehearsal's first manifest
  carried `tree_dirty_outside_forecasts: True` because of a stray Finder file at the
  repository root. It is now in `.gitignore`. Before the record run, check
  `git status --porcelain` is empty; the field goes into the published record.
- **PyTensor logs three `OverflowError: Python integer … out of bounds for int8` tracebacks**
  during the M2f-r4 compile, from its `local_subtensor_merge_slice` rewrite. They are caught
  internally, the rewrite is skipped, and the run completes normally with the same numbers.
  They are noise, not a failure; do not stop the run because the Action log shows them.

**Afterwards.** Score h1 (October 2026) against the outturn published on 12 November 2026.
The 2026-09 dry run's h1 (September 2026) is scored on 8 October.
