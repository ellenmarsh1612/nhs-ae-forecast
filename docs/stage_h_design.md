# Stage H runner: design (pre-flight P3, with P5)

**Status: v2.2, 2026-09-14.** v2.2 records P11, the seal hardening, built once Ellie permitted the `splits.py` edits on 2026-09-14: `splits.py` now enforces the seal's rules for every caller, with a new `seal_rules.py` (§1, §2.10), the HEAD rule at the seal accepts only the hash commit H1 (§3.2.4, §4), and the post-run state is defined (§9). v2.1 adds what an adversarial review of the built runner found: the case-3 crash procedure, the fixed input set, the environment-drift rule, the writer's rule for mixed tables and the F2 coherence-gap exclusion. Written before any Stage H code and before any CONF result;
nothing in it came from looking at CONF. It turns `docs/confirmatory_plan.md` §3–§6 and the P3
and P5 rows into a buildable spec, and settles the questions the plan leaves open. Each
settlement is marked **[default]**, and every [default] is copied into the amendment "Stage H
implementation details" before the tag, so Ellie can overrule it at STOP 9.

v2 folds in a read-only code mapping (five readers and a completeness critic) and an adversarial
review of v1 (four lenses, every major finding independently verified); both 2026-09-13, file and
line references to `cf4ba6c`. The main v2 changes:
- every data build is bounded by an end origin;
- the unseal record survives a crash, with a rerun rule written before the tag;
- scores are written and hashed before any statistic is computed;
- the runner's hash commit is reconciled with P11's HEAD rule;
- H1, H3 and H4 get composite fragility rules;
- MinT runs over DEV origins as well.

## 1. Shape

A package, `src/nhs_ae/evaluate/stage_h/`, stands in for the plan's `evaluate/stage_h.py`: the
runner is too large for one module. There is one entry point, `python -m nhs_ae.evaluate.stage_h COMMAND`:

| Command | When | What it does |
|---|---|---|
| `pin` | before the tag; refuses once `conf-plan-v1` exists | Rebuilds the vintage table from `data/raw` in a scratch directory and writes `docs/stage_h_pins.json`, the run's reference values (§3.1). Committed before the tag; the hashes are copied into the plan's P5 row |
| `prepare [--dev-side]` | before the tag, on the final pre-tag code | Runs checks 6–8, then copies the 13 pool and M2 inputs (§8), read-only, into `data/processed/stage_h/inputs/`, each source checked for its origin set (M2 for its SHA-256) and hashed before and after copying. With `--dev-side`, also generates the 8 DEV-side files with the step-3 code on a P4 rebuild kept outside the inputs directory. Writes `SHA256SUMS` and `prepare.json` (commit, Python, platform, all 21 SHA-256s, the vintage hashes including the dev-reach hash). Without `--dev-side`, the record says so and `pin` refuses it. Any later edit to check 11's paths (§3.2) means running it again, so the order is: code final (P11 merged), `prepare --dev-side`, `pin`, a dry run at that code, tag (§1, "Order before the tag") |
| `preflight` | on the final pre-tag commit, and again just before `run` | Every step-2 check that does not need the tag, with HEAD standing in for it; writes nothing |
| `dry-run` | now, and again before the tag | Steps 2–5 on DEV origins 2023-07 to 2023-12, treated as CONF-like, with no token (§10). Writes only `data/processed/stage_h_dry/<head>/` and `results/H-dryrun/` |
| `run --unseal-token-file PATH [--amendment TITLE]` | after the tag and Ellie's written go-ahead | Steps 2–6, in one process |
| `report --from-scores` | only after a crash, in a later process | Rebuilds every table from the hashed step-4 and step-5 files with no guarded call: the crash policy's recomputation path (§9) |

**Modules:**
- `common.py`: constants and the run context.
- `seal.py`: token handling, log and witness accounting, the guarded-call wrapper, split-checked scoring, and the post-unseal process tripwire.
- `checks.py`: step-2 checks, `pin`, the P4 rebuild, and `preflight`.
- `generate.py`: step-3 blocks, the M2 loop, QA, hashes, the D7 and P13 checks, and the hash commit.
- `pools.py`: first-release tables at every level, joining the inputs to the new forecasts, G1, both calibration populations, MinT with injected frames, and the runner-side sealed-period guards.
- `stats.py`: the comparison wrapper, the two-way bootstrap, leave-one-origin-out, verdict and fragility helpers, and DEV ranges.
- `hypotheses.py`: H1, both H2 clauses, the primary, the headline, H3, H4, H4-original, H4b, H5 and F2.
- `store.py`: the write-then-hash store for step-4 and step-5 outputs, and the verifying loader.
- `report.py`: the CSVs, `confirmatory_results.md`, the README with provenance, and the step-6 summary.
- `__main__.py`: orchestration and progress records.

**Changes outside the package**, each behaviour-preserving and tested:
- `stage_f.reconcile_model`'s body becomes `stage_f.reconcile_frames(cal, fr, failed, origins, icb_of, region_of)`; `reconcile_model` wraps it.
- `stage_f.f2_table` gains `origins=`; the runner always passes it.
- `calibrate.online` gains an optional pool trace (each pool's origin set), for the P3 tests.
- `ingest.cli.cmd_build`'s de-duplication moves into a function the runner shares.
- `stage_e._fit_origin` gains `shift=0`.

**P11, the seal hardening** (Ellie permitted the `splits.py` edits on 2026-09-14). Until then the runner enforced these rules on its own side only; its own checks stay, and `splits` now enforces them for every caller:
- `evaluate/seal_rules.py` (new, standard library only, so `splits` imports it without a cycle): the git helpers, the §10 row reader, the HEAD rules (`start_commit_ok`, `hash_commit_ok`), `names_run`, the tree and import rules, the witness path, and the post-run state (`post_run_problems`). `stage_h/checks.py` and `seal.py` keep their names as thin wrappers over it.
- `evaluate/splits.py`: `assert_not_sealed(frame_or_origins, unseal_token=None, *, amendment=None)` checks the unseal context on the first tokened call of a process and keeps it for later calls, and returns without the token in the post-run state (§2.10, §9). `live.py` still imports `SEALED_ORIGINS` from it.
- Guards inside `calibrate.online.first_release` and `calibrate`, and `stage_f._median_errors`, each taking `unseal_token=`; `stage_f.reconcile_frames` passes it on. `pools.py` passes its token (None in the dry run) to each, and keeps its own guards (§2.5).
- `evaluate/cli.py` (`nhs-ae-backtest`): `summary --include-sealed` and `run --unseal-token` are deleted. `run` refuses any sealed origin before any data are read, by membership of `SEALED_ORIGINS` rather than through `assert_not_sealed`, so the refusal outlasts the post-run state.
- `stage_h/seal.open_seal` and `cmd_run` pass `--amendment` on to `splits`.

`stage_h/common.py` is not touched.

**Order before the tag.** P11 merged, then `prepare --dev-side`, then `pin`, then a dry run at that code, then the tag. `splits.py` is one of check 11's generation paths (§3.2.11), so P11 has to land before `prepare --dev-side`. `seal_rules.py` is deliberately outside those paths: the seal's rules change no forecast.

## 2. Seal invariants, in the order the runner meets them

1. **Steps 2 and 3 compare no forecast with an outturn.**
   - They never call `load_truth`, `truth_long`, `icb_truth`, `agg_truth`, `truth_all`, `first_release`, `calibrate`, `g1.last_observed`, `_median_errors`, any scorer, `audit.*`, or any plotting.
   - Tripwires installed in every worker initialiser, and in the parent, raise on any of these during step 3. They are tested with `jobs=2`.
   - **Exception, stated in the amendment:** residuals that the frozen models compute on as-of training data while generating their registered forecasts. Closed by Ellie's STOP 9 decision D-1 (2026-09-15; §10 row "STOP 9 decisions") to this list: the residuals, losses, likelihoods and residual correlations computed on as-of training data by default M1's fitting and its in-model conformal step, B0's in-sample errors, and the fitting of B1 (ETS), B2 (STL+ARIMA), M1 v3 raw and `m2d_corr`; and, in the live pipeline, the raw ETS fit and the unpublished M2f-r4 shadow fit. None is persisted or printed, and they fall outside P12; any other such comparison before the unseal entry needs an amendment row.
2. **The token is read from a file only at the moment it is needed.**
   - Step 2 reads the file, checks the token against the tag commit, and discards it.
   - Step 4 reads it again, after every process pool has closed.
   - The token is never in `sys.argv`, `os.environ`, `initargs` or any task argument. Spawn workers copy the parent's argv and environment, so a command-line token would reach every worker.
   - After the guarded call, a tripwire makes process creation raise.
   - The guarded wrapper refuses to run when `multiprocessing.parent_process()` is not None.
3. **Pre-unseal checks, then the guarded call.** At the end of step 3, before the `try` block that covers the unseal, the runner asserts:
   - HEAD equals H1, the runner's hash commit (§4), and H1's parent is the start commit S;
   - the diff from S to H1 only adds the listed files;
   - every forecast file re-hashes to its entry;
   - `git status --porcelain` is empty;
   - `multiprocessing.active_children() == []`;
   - `splits._logged_tokens` is empty.

   Then the first guarded call of the process is `assert_not_sealed(split_origins("conf"), token, amendment=TITLE)`, with all 21 origins, in the parent. There `splits` checks the unseal context itself (§2.10).
4. **Every build that reads sealed data is bounded.** One end origin E is used by every builder: E = 2025-09 in run mode and 2023-12 in the dry run. The builders are the first-release tables, `last_observed`, the joined DEV + new tables, the calibration and MinT origin sets, and H4b's windows. No literal 2025-09 appears outside `common.py`.
5. **Runner-side sealed-period guards.** Before every `calibrate` call and every `_median_errors` call, `pools.py` runs `assert_not_sealed(merged.loc[merged.y_first.notna(), ["period"]], token)`, with token None in the dry run. The check covers every row carrying a first release, because CQR scores are computed before the `valid` filter.
   - The dry run also asserts that every first-release table has period ≤ 2023-11 and resolved ≤ 2023-12.
   - A negative-control test sets E = 2025-09 in dry mode and must raise.
   - **Since P11 the same checks also sit inside the calibration and reconciliation code:** `online.first_release` checks the table it builds; `online.calibrate` checks every forecast row that carries a first release (origin and period), where the CQR scores are computed and before any `valid` filter; `stage_f._median_errors` checks its merged rows before any error. Each calls `splits.assert_not_sealed` through the module attribute, so the tripwires and test spies see every call. `pools.py` passes its token to `first_release`, to `calibrate` (in `calibrate_population` and `pool_trace`) and to `reconcile_frames`, and keeps the guards above.
6. **Scoring.**
   - DEV frames are scored with token None, and their origins are asserted to be DEV.
   - CONF frames are scored with the token, and their origins are asserted to be CONF. A tokened call skips the embargo, so a DEV origin in a tokened frame would score a sealed target.
   - For DEV scoring, the embargoed (origin, horizon) pairs are asserted to be exactly those whose period is 2024-01 or later.
   - Every statistic comes from `harness.score_forecasts` output, via the store (§9).
7. **Log and witness accounting.**
   - **Witness.** As soon as the guarded call returns, the new log line is also appended to a witness file in the git common directory: `$(git rev-parse --git-common-dir)/nhs_ae/unseal_witness.jsonl`. That file is untracked by construction and shared by every worktree. It survives checkout, stash, reset, clean, `git worktree remove` and branches cut from the tag.
   - **The new line is checked at once:**
     - `token` equals the tag commit;
     - `head` equals H1;
     - `origins` equals ["2024-01-01", "2025-09-01"];
     - `sealed_rows` equals 21;
     - `argv` names `nhs_ae.evaluate.stage_h run`.
   - **The `finally` block** covers every exit after the `try` begins.
     - It expects n0 + 1 lines in this worktree's log if the guarded call returned, and n0 otherwise; every other worktree's log is unchanged.
     - It flags any line that does not parse.
     - If an exception is already in flight, the accounting result is attached with `exc.add_note(...)` and the original propagates. A `SealAccountingError` is raised only when the body succeeded.
     - The block runs no git operation.
   - **The dry run** asserts zero new lines everywhere, and no witness file change.
8. **Paths.**
   - The runner refuses to start if `data/processed/stage_h/<tag-commit>/` or `results/H-confirmatory/` exists.
   - It writes only there, plus three carve-outs: the tracked `results/unseal_log.jsonl`, written by `splits`; the witness file; and the runner's git commits (§4, §9).
   - Inputs come from the sibling `data/processed/stage_h/inputs/` and from the quarantined pre-seal forecast file (P13, read with filters, §4).
9. **One vintage table.**
   - Every load uses the rebuilt vintage path (P4).
   - Every `ProcessPoolExecutor` the runner creates is checked, by a spy on its `initargs`, to carry that path.
   - Each worker initialiser hashes the file it loaded and returns the hash, which the parent checks against the pin.
10. **The seal in `splits` (P11).** `assert_not_sealed` returns before any git call when nothing sealed is present. Otherwise, in order:
    - **Post-run state** (§9): if it holds, token None and the tag commit return without a log line, and any other token raises.
    - **Token.** None raises; so does a missing tag, or a token that is not the tag commit.
    - **The first tokened call of a process** refuses, writing nothing, unless all four rules hold. The tag commit and HEAD come from one `rev-parse` each and are passed to `seal_rules`, so there is one source of truth.
      - *HEAD:* HEAD is the runner's hash commit H1 on a start commit S (§4). HEAD = S is refused.
      - *argv:* the process is `python -m nhs_ae.evaluate.stage_h run`: under `-m`, `sys.argv[0]` is the package's `__main__.py` and `sys.argv[1]` is `run`.
      - *Tree:* nothing modified, staged or untracked outside `results/` and `data/`, by the repository's ignore rules only (`git -c core.excludesFile=/dev/null status --porcelain --untracked-files=all`).
      - *Import:* check 7's rule: `nhs_ae` is imported from PROJECT_ROOT's `src/nhs_ae`, and PROJECT_ROOT is the git toplevel, which fixes the log `splits` writes to.
    - **Later tokened calls** of the process (pools, calibration, MinT, scoring) reuse that context. They refuse unless HEAD is still the validated head; `amendment` None reuses the remembered amendment, and a different one refuses. **[default]** The tree and import rules are not checked again after the first call. `_pre_unseal` has just run check 6, and clutter appearing mid-run (a Finder `.DS_Store`, an editor's swap file) must not crash the run after the unseal.
    - **The log line**, once per process per token, keeps its format (timestamp, token, head, argv, sealed_rows, origins). It is written and `fsync`ed before the token and its context are recorded, so a failed write followed by a retry is validated again, never passed silently.
    - **No bypass.** No environment variable, configuration switch or module flag lifts any rule. Tests patch the named seams (`splits._context_problems`, `_import_problems`, `_post_run`) with `monkeypatch`; `tests/conftest.py` makes `_post_run` return False in every test that does not ask for the real one, so no test depends on the real repository's tags.

## 3. Step 2: pre-run checks

### 3.1 Pins (`docs/stage_h_pins.json`, written by `pin` before the tag)

The pins hold:
- the manifest SHA-256;
- the vintage row-content hash, for both the runner's rebuild and the shared `ae_monthly_all_vintages.parquet`;
- the parse-failure list;
- the `data/reference` file hashes;
- the SHA-256 and the canonical row hash of every permitted input (§8), with its origin set, model, level and mode;
- the dev-reach hash: the row hash of the vintage rows with period ≤ 2023-11 (the last period any DEV-origin slice reads), at every snapshot. `prepare` records it on the table it generated on, and `pin` refuses unless its own rebuild reproduces it;
- the quarantine path and hash;
- the D7 as-of slice hashes at 2025-07, 2025-08 and 2025-09;
- the platform string and Python version;
- the commit that ran `prepare --dev-side`.

**Row-content hash [default]:** the SHA-256 of `pd.util.hash_pandas_object(frame[cols], index=False).to_numpy()`. The frame is first sorted by `snapshot, period, org_code, metric, source_file`, and `cols` is every column in a fixed order. The same definition is used for forecasts and scores ("canonical row hash").

In run mode the pins and the lock are read from the tag (`git show conf-plan-v1:docs/stage_h_pins.json`, `git show conf-plan-v1:requirements-lock.txt`), never from the working tree.

### 3.2 Checks, in order (run mode)

1. **Output directories.** Neither exists.
2. **Tag.** `git cat-file -t conf-plan-v1` is `tag` (annotated), and `git ls-remote origin refs/tags/conf-plan-v1` returns the local tag object (P9's push).
3. **Token.** The token file's content equals the tag commit. The token is then discarded (§2.2).
4. **Start commit S.** S is HEAD. It must be the tag commit, or, with `--amendment TITLE`, a descendant of the tag whose `docs/preregistration.md` contains exactly one §10 row titled TITLE, a row absent at the tag. HEAD = S holds at step 2 only: at the guarded call `splits` requires HEAD = H1, the hash commit on S (§4, §2.10, P11). **[default]** Crash-fix commits go on top of the runner's last commit (§9), on the tag's line of descent, never on `main`, where the archive bot commits on days 8–21. The runner prints `git log --oneline tag..HEAD` and `git diff --stat tag..HEAD` and records them in the README.
5. **No data, pin or lock change since the tag.** `git diff --quiet conf-plan-v1 HEAD -- data/raw data/reference docs/stage_h_pins.json requirements-lock.txt` must succeed.
6. **Clean tree.** `git status --porcelain` is empty, untracked files included. `preflight` catches untracked clutter such as `.DS_Store` and `.claude/` before the tag.
7. **Import location.** `nhs_ae.__file__` lies under the git toplevel's `src/nhs_ae`, and `config.PROJECT_ROOT` equals the toplevel.
8. **Environment.** `pip freeze`, without comment lines and the `-e` line, equals the tag's lock, and the `-e` line's commit is HEAD. Both are hard refusals. Python and the platform must equal the pins. **[default]** Drift in either is accepted only under `--amendment`, and only when the TITLE row quotes every new value verbatim and reports a P0b-style reproduction in the new environment. The drift is recorded in the README. Operationally, hold macOS and conda updates from `pin` until `conf-run-v1`; a drifted Python is restored from the cached conda package, not by amendment.
9. **Raw data.**
   - The manifest SHA-256 equals the pin.
   - Every stored file's bytes match its manifest SHA-256.
   - `missing_readers(manifest)` is empty.
   - Each `data/reference` file matches its pin.
10. **Unseal logs and witness.**
    - Every witness line appears in HEAD's committed `results/unseal_log.jsonl`.
    - The working-tree log equals HEAD's copy.
    - Every other worktree's log is absent or empty.
    - Without `--amendment`, this worktree's log and the witness are both empty.
    - With `--amendment`, this worktree's log may hold k prior lines. Each must have token equal to the tag commit, argv naming `stage_h run`, and a head that descends from the tag, and the TITLE row must quote each line's timestamp. n0 is then k. **[default]**
11. **Inputs.** The pinned names are exactly the 21 files of §8, each pinned with its expected origin set, and M2's SHA-256 is E-m2-rerun69's. Every permitted input matches its pinned SHA-256, row hash and origin set. The generation code has not changed since the `prepare --dev-side` commit: `git diff --quiet <gen-commit> <tag> -- src/nhs_ae/models src/nhs_ae/features src/nhs_ae/evaluate/harness.py src/nhs_ae/evaluate/asof.py src/nhs_ae/evaluate/metrics.py src/nhs_ae/ingest/recover.py src/nhs_ae/evaluate/splits.py src/nhs_ae/evaluate/stage_h/common.py src/nhs_ae/evaluate/stage_h/generate.py requirements-lock.txt`. `splits.py` and `common.py` fix the DEV origins; `metrics.py` (the scale column) and `recover.py` (as-of dates, month ranges) lie on the harness's path. P11's `splits.py` change therefore lands before `prepare --dev-side` (§1, "Order before the tag"). `seal_rules.py` is deliberately not on the list: the seal's rules change no forecast.
12. **Quarantine (P13).** The quarantined pre-seal forecast file exists at its pinned path, matches its hash, and is ignored by git (`git check-ignore`, and no file under it is tracked). **[default]** The location is `data/processed/quarantine/pre-seal/`, which amends P13's `data/quarantine/pre-seal/`, a path neither tracked nor ignored.
13. **Load.** `os.getloadavg()` is recorded, with a warning above 2. It never refuses.
14. **Rebuild (P4).** The vintage table is rebuilt into `stage_h/<tag>/vintages/`. Its row hash must equal the pin, its parse failures must equal the pinned list, and its D7 slice hashes (2025-07, 2025-08, 2025-09) must be equal to each other and to the pins. If the slices differ, the premise of the 19 information sets fails, and the run stops here.

**Dry mode** runs checks 6–9, 11 and 13, logs counts for check 10, and rebuilds into the dry directory. The dry run skips the tag, token, start-commit, quarantine and output-directory checks.

## 4. Step 3: generation (no guarded call)

All blocks read the rebuilt table and write under `stage_h/<tag>/forecasts/`, one file per model × level × mode.

| Block | Models | Level | Mode | Origins | Code path |
|---|---|---|---|---|---|
| Provider | B0, B1, B2, default M1 (`m1`), M1 v3 raw | provider | as-of and final | all 21 **[default: final at all 21, rather than the 5 H4 needs, so the P13 check is complete]** | `harness.generate_forecasts(..., vintages_path=run)` |
| ICB | B1, B2, M1 v3 raw | ICB | as-of | 21 | same |
| Aggregates | B1, B2, M1 v3 raw | region, England | as-of | 21 | `stage_f._init(run, BASE_MODELS)` + `_agg_task` (SummedView) |
| M2 | `m2d_corr`, frozen settings | ICB, region, England | as-of | 21 | `stage_e._init(run)` + `_fit_origin(..., shift)` |

M2f-r4 is not generated (D1 = exclude).

**M2 fit policy** (plan §6):
- 3 workers × 4 cores. The fit seed is year × 100 + month and the predictive-draw seed is the month.
- An exception gets one retry with both seeds + 1,000. A second failure makes the origin failed, and its rows are absent.
- `BrokenProcessPool` and `KeyboardInterrupt` are crashes, not fit failures.
- R-hat, ESS and divergences are recorded and reported, and exclude nothing.
- **[default]** The H2 M2 clause is *not evaluable* if 4 or more of the 19 counted units failed (more than 20%). The 21-fit count is reported alongside. A failed 2025-07 fit leaves that unit missing; it is not replaced by 2025-08 or 2025-09.
- **[default]** An exception in a harness model is a crash under the crash policy; the retry rule is M2's.

**QA.** Only counts, NaNs, quantile order and hashes are checked. Per file and per (model, level, mode, origin, target):
- the key set equals the panel-active series × 6 horizons × 9 quantiles, and is identical across the harness models;
- the counts of NaN rows, negative quantiles, crossed quantiles and all-zero rows;
- horizon → period: period − h equals the training end month, which is 2025-06 at as-of origins 2025-08 and 2025-09;
- the file SHA-256 and the canonical row hash.

**D7 check.** Forecasts at 2025-08 and 2025-09 are compared with 2025-07's.
- Deterministic models: the maximum absolute difference is reported; 0 is expected.
- `m2d_corr`: its seeds differ by origin, so the seed-stability statistic is reported instead: the median and 95th percentile of |Δq| over the 50% width, against 5% and 20%.
- **[default]** Reported, not a stop. The information-set identity was already checked in step 2.

**P13 check.**
- The comparison is values only, at provider level: B0, B1, B2 and default M1, both modes.
- The quarantined file is read with pyarrow filters (origins in CONF, provider level, those models) and the key and value columns only.
- Reported per model × mode:
  - keys found only in the new or only in the old file;
  - NaN mismatches;
  - the share identical;
  - the median and maximum relative difference.
- Expected result:
  - B0, B2 and default M1 identical in as-of mode;
  - B1 different, since it is now seeded;
  - final mode different only if the archive changed.
- **[default]** Reported, not a stop.

**Hash commit H1. [default]**
- The runner writes `results/H-confirmatory/{forecast_hashes.csv, m2_fits.csv, timings.csv, qa_counts.csv}`.
- It commits them with `git -c core.hooksPath=/dev/null commit --no-verify`. H1 is then a single-parent child of S whose diff only *adds* those four files.
- The unseal log's `head` will be H1. That proves the hashes existed before the unseal.
- **The plan's P11 HEAD rule accepts exactly this shape, and only H1 (P11).** At the first tokened call of a process, HEAD must be H1: S's single child made by the runner, whose diff from S only adds the four named files. S is either the tag, or an amendment descendant (§3.2.4). HEAD = S is refused: the runner never unseals at S, and accepting S would let a script unseal before the forecasts are hashed. A chain of runner commits, a merge, a commit that touches any other path, or one that modifies a hash file rather than adding it, is refused.
- **The argv rule (P11).** The same call also requires the process to be `python -m nhs_ae.evaluate.stage_h run` (§2.10), so no other script can make the first unseal, even at H1.

## 5. Step 4: unseal, calibrate, reconcile (one parent process)

1. **The guarded call** and its line check (§2.3, §2.7). A progress record `unsealed` is written.
2. **First-release tables.**
   - Provider and ICB: `online.first_release(v, month_range(2017-08, E), since=2017-07-01, level=...)`, with EXCLUDE dropped from the ICB table.
   - Region and England come from the ICB table. **[default]** An aggregate has a first release only once every mapped ICB beneath it has one: `y_first` is their sum and `resolved` their maximum. Stage F summed whichever ICBs were present. On DEV all ICBs are always present, so the two rules agree there.
   - The table stops at E. The lost-original periods 2025-07 to 2025-09 first appear at origin 2025-11, so they enter no CONF pool.
3. **Base tables.** For each model × level, the P5 input (restricted to origins before the first new origin in the dry run) is joined to the new forecasts; overlapping origins are refused.
4. **G1.**
   - `last_observed` over 2017-07..E at every level, then `failed_forecasts` for each model × level, with counts.
   - The DEV check compares both the input-span and the DEV-origin counts with `results/F-reconciliation-G1/failed_counts.csv`. A mismatch is reported.
5. **Calibration** (pooled, with G1, guarded as in §2.5). **[default]** Two populations, as each was registered:
   - the **Stage D population**, all provider codes, for the primary and the headline at provider level;
   - the **Stage F population**, hierarchy members only (UNMAPPED and LEGACY excluded at aggregate levels), for H3 and F2.

   On DEV the two coincide from 2022-08, when no non-member provider has a forecast any more.
6. **MinT** per base, through `stage_f.reconcile_frames` with injected frames (guarded as in §2.5).
   - It runs over **every DEV and CONF origin**, 2018-04 to E, so the DEV side of H3 and F2 comes from the same code path.
   - At a DEV origin t, W and the pools use only rows with resolved ≤ t ≤ 2023-12, so no sealed value enters a DEV row.
7. **H4b's as-of and final windows** (§7.10). They are computed here because they read sealed values.
8. **Storage.** Every step-4 output goes into the store (§9) as soon as it is computed: calibrated frames per model × level × population, reconciled frames, G1 failed tables, H4b components.

## 6. Step 5: score once

1. **Re-hash** the forecast files.
2. **Truth:**
   - provider and ICB: `truth_long(load_truth(v, region_map), ...)`;
   - region and England: `stage_e.agg_truth(v)`, which scores only months with every ICB present.
3. **Score DEV** (no token), **then CONF** (the token), for every model × level × mode × stage (raw, calibrated, reconciled).
4. **G1 marking.**
   - B1, B2 and M1 v3 raw rows (raw, calibrated and reconciled) pass through `g1.mark`. Failed forecasts keep their WIS and count as not covered.
   - Every G1 table comes as issued, which is decisive, and with failed forecasts dropped.
   - All-zero forecasts of B0, default M1 and `m2d_corr` are counted and not treated; G1's scope is the three bases.
5. **Write the scores.** Every scored frame, with its `failed` flag and its `dropped` dict, goes into the store. Writing the store's `SHA256SUMS` for scores is the crash policy's "score written" boundary (§9).

## 7. Statistics (fixed before any CONF result)

### 7.1 Origins and slices
- **CONF19** is 2024-01 to 2025-07, the unit of every pooled statistic (D7).
- **CONF21** is reported alongside. In origin bootstraps 2025-08 and 2025-09 fold into 2025-07's unit.
- **W5**, the winter-h3 origins, are 2024-01, 2024-10, 2024-11, 2024-12 and 2025-01. D7 does not touch them.
- D7 is never applied to DEV. The truncated DEV origins 2018-11 and 2021-10 are not exact duplicates, and keep their as-of targets.
- **No table mixes slices** (plan §5). Each CSV carries split, months, horizons, level, mode, origin set and G1 variant as columns, and `report.py` asserts one value of each per file. CONF19 and CONF21, DEV and CONF, and provider and ICB always go into separate tables. Coverage is always shown by horizon and by origin-year.

### 7.2 Two-forecast comparisons
- Every comparison, including those inside `stage_f.h3_table` and `f2_table`, goes through one wrapper. The wrapper calls `paired_bootstrap(a=reference, b=tested, unit="series", n=1000, seed=0, keys=("series","target","origin","horizon","period"))`.
- It asserts one model, mode and level per frame, and unique keys.
- It reports n_ref and n_tested (rows without NaN), n_pairs, and the rows left unpaired on each side.
- An empty join is reported as *not evaluable*.

### 7.3 H1
- **Slice:** B0 → default M1, MASE, provider, as-of, h = 3, winter, W5. M1 v3 raw is reported alongside.
- **Per target:** *confirmed* if rel_hi < −0.15. Otherwise *not confirmed (refuted, as registered)*, qualified as:
  - *point estimate meets the bar* (rel ≤ −0.15);
  - *partial support* (−0.15 < rel < 0);
  - *no improvement* (rel ≥ 0).
- **Overall:** *confirmed* only if all three targets are.
- **Also reported:** a pooled-targets row (descriptive; also the `n_pairs` test fixture), and the §9 caveat that the bootstrap is within one winter.
- **Leave-one-origin-out (LOO) over W5: [default]** For each of the five 4-origin subsets s, compute every target's rel and rel_hi on the rows with origin ≠ o.
  - *Per-target verdict:* fragile if min_s rel_hi ≤ −0.15 ≤ max_s rel_hi.
  - *Qualifier:* fragile if its boundary (−0.15 or 0) lies in [min_s rel, max_s rel].
  - *Overall verdict:* the composite statistic is m_s = max over targets of rel_hi (H1 is confirmed in s if and only if m_s < −0.15). The overall verdict is fragile if min_s m_s ≤ −0.15 ≤ max_s m_s.
  - *Extension, beyond the registered range rule:* a verdict is also fragile if the full-sample verdict differs from any subset's.
  - The subsets that flip the overall verdict are reported, with the dropped origin at each extreme.

### 7.4 Two-way coverage bootstrap **[default: Künsch moving blocks]**

**Units.**
- The series present in the slice: providers, or ICBs for H2's M2 clause.
- The origin units, in calendar order: 19. In the 21-origin version, 2025-08 and 2025-09 fold into 2025-07's unit.
- If an origin is missing (a failed M2 fit), the units are the ordered list of origins present, and a block may span the gap.
- The unit list is fixed across horizons within a table.

**Draws.**
- `rng = np.random.default_rng(0)`.
- First the series draws, a 1000 × S matrix of indices.
- Then the block starts, a 1000 × k matrix drawn uniformly on 0..n−l, with l = min(3, n) and k = ⌈n/l⌉.
- The slots are start + 0..l−1, concatenated and truncated to n.

**Statistic.**
- For each cell and resample b: Σ_s Σ_u W_bs V_bu K_su ÷ Σ_s Σ_u W_bs V_bu N_su, where K counts covered rows and N scored rows. Each row is therefore weighted equally, as the plan's measure requires.
- One set of draws serves a whole table: every horizon, target, interval level and model in it. Gaps between models are therefore paired.

**Interval and diagnostics.**
- The interval is the 2.5 and 97.5 percentiles (numpy's linear rule).
- Resamples with a zero denominator are dropped and counted.
- A cell with fewer than 3 contributing origin units is marked *origin-degenerate* and reported with its provider-only interval. This happens only in the dry run: every CONF19 origin × horizon is scored.
- The within-period (provider-only) interval reuses the same series draws with every origin weight set to 1.
- Each cell also reports the bootstrap mean minus the point estimate.
- **End effect.** Because of the truncation, the expected origin multiplicities are unequal. For n = 19 and l = 3 they are 0.41 (2024-01), 0.76, then 1.12 for interior units, 0.71 and 0.35 (the 2025-07 unit). This is a property of the textbook scheme; it is reported, not corrected.

### 7.5 Coverage verdicts

**Primary** (M1 v3 raw + pooled + G1; provider, all months, as-of, CONF19, pooled over providers and targets):
- *within tolerance* if 0.85 ≤ lo_h and hi_h ≤ 0.95 at every h;
- *outside tolerance* if some h has hi_h < 0.85 (under-covering) or lo_h > 0.95 (over-covering), each named;
- otherwise *inconclusive*.

The primary's rule already uses the intervals, so it carries no fragility label.

**Reported alongside the primary** (decides nothing; D2):
- the point estimates of cov90_h;
- the provider-only intervals;
- pooled cov50_h, and per-target cov90_h and cov50_h, each with a two-way interval from the table's shared draws **[default]**;
- the 0.87–0.93 cells: `stage_d.coverage_cells` on the G1-marked CONF19 rows, for origin-years 2024 (12 origins) and 2025 (7 origins) × h = 1–6, each marked met or not met, with the failed-dropped variant;
- the CONF21 cells in a separate table **[default]**;
- the DEV range (§7.13).

**H2, M1 clause** (default M1; provider, all months, as-of, CONF19; point estimates decide):
- *confirmed* if some h in 4–6 is outside [0.85, 0.95];
- *refuted* if every h is inside;
- *neither* if h4–6 are all inside and some h ≤ 3 is outside.

The direction is named in each case. Origin-year × horizon cells (2024 and 2025) are reported for CONF19, with CONF21 in a separate table. The §9 caveat is stated.

**H2, M2 clause** (`m2d_corr`, ICB level; point estimates decide):
- *confirmed* if every h is inside;
- *refuted* if any h is outside, with the direction named;
- *not evaluable* under §4's rule.

It is labelled as a phase-1b test at ICB level, under the §9 fallback. Also reported:
- the origin-year × horizon cells;
- CONF R-hat, ESS and divergences per fit, and their origin-year medians set against the DEV trend table;
- the Text A limitation.

**Fragility of a coverage verdict. [default]** A verdict is fragile if a horizon that decides it has a two-way interval containing a band edge. Per-horizon crossing flags are also reported.

| Verdict | Fragile when |
|---|---|
| H2 M1 confirmed | every outside h ≥ 4 crosses an edge |
| H2 M1 refuted | any h crosses |
| H2 M1 neither | any h ≥ 4 crosses, or every outside h ≤ 3 crosses |
| H2 M2 confirmed | any h crosses |
| H2 M2 refuted | every outside h crosses |

### 7.6 Descriptive headline
- **What is compared:** B1, B2 and M1 v3 raw, raw against + pooled (Stage D population), at provider level, CONF19, G1-marked, on common rows.
- **What is reported:**
  - raw and pooled cov90, each with a two-way interval;
  - each gap to nominal, in pp;
  - pooled − raw, with a paired interval from the shared draws;
  - all by horizon and by origin-year.
- **[default] Also reported:** raw ETS's 90% coverage at ICB level, the level the live forecast is issued at, in a separate table. It is descriptive only.

### 7.7 H3
- **Method:** `stage_f.h3_table`, with inputs checked by the wrapper, on the CONF19-scored W5 rows.
- **Levels:** England shows the point estimate, with its interval marked n/a (one series). Region carries a caution (bootstrap over 7 series). The headline is M1's verdict (D3 = (a)). The note "R2 not tested (phase 1b)" is printed.
- **LOO over W5: [default]**
  - For each subset s, the H3 verdict is computed from both clauses: ICB rel_hi_s < 0 and provider rel_s ≤ 0.02.
  - The verdict is fragile if the five subset verdicts are not all the same, or (extension) if any differs from the full-sample verdict.
  - Per-clause ranges (ICB rel_hi against 0, provider rel against 0.02) are reported descriptively.

### 7.8 H4 (exploratory on CONF)
- **Slice:** B0, B1, B2 and default M1, with M1 v3 raw alongside; provider level, W5, both modes, per target.
- **2% clause:** a model × target *differs* if rel_lo > 0.02 or rel_hi < −0.02 (rel = final ÷ as-of − 1).
- **Ranking:** computed per target on the rows every one of the four models scored in both modes. **[default]** Models are ranked by the mean over series of per-series mean WIS, the weighting `rel` uses. The ranking holds if the order is the same in both modes.
- **Verdict:** refuted if any model × target differs or any target's ranking changes.
- **LOO over W5: [default]**
  - A 2% call is fragile if 0.02 ∈ [min rel_lo, max rel_lo] or −0.02 ∈ [min rel_hi, max rel_hi].
  - A target's ranking is fragile if any subset changes its outcome.
  - The verdict is fragile if the five subset verdicts are not all the same, or (extension) if any differs from the full sample.
- **Also reported:** G1 marking and a failed-dropped variant for B1, B2 and M1 v3 raw.

### 7.9 H4-original
- For each mode, model (B1, B2, default M1, and M1 v3 raw alongside) and target, rel of B0 → model is computed on that mode's rows.
- Δpp = 100 × (rel_final − rel_asof).
- It *holds* if any |Δpp| > 5 or H4's ranking changes.

### 7.10 H4b (labelled *seen*)
- **Window (P14):** for each counted origin o, W_o is the 12 months ending at o's as-of end month E_o, not at M−1.
- **Components**, per target, on provider rows (England total = sum of provider rows, the audit convention):
  - value revisions V = Σ over provider-months in both (final − as-of);
  - late submissions L = Σ over final-only provider-months (final);
  - withdrawals Wd = Σ over as-of-only provider-months (as-of).
- **Identity:** Σ final − Σ as-of = V + L − Wd. A unit test checks it.
- **late_larger** means |L| > |V|.
- **Verdict per target:** *confirmed* if late_larger holds at 10 or more of CONF19. The 21-origin version (11 or more) is reported alongside. **[default]** Overall *confirmed* only if every target is; otherwise the per-target labels.
- **Lost originals**, a separate split: provider-months in periods E_o < p ≤ M−1.
- **DEV side:** all 69 DEV origins, shown side by side. No registered range exists for H4b.

### 7.11 H5
One line: not evaluable on CONF, and never testable on a sealed split (plan §3).

### 7.12 F2 on CONF
- **Method:** `stage_f.f2_table` with `origins=CONF19`, CONF21 in separate tables.
- **Contenders:** ETS + pooled, ETS + pooled + MinT, M1 + pooled, M1 + pooled + MinT, and `m2d_corr`. There is no M2f-r4 (D1 = exclude).
- **Reported at ICB, region and England:**
  - the coherence gap (mean and max), labelled "median non-additivity" for `m2d_corr`. **[default]** Aggregates whose median is not positive are left out of the gap, and so are G1-failed forecasts, which are issued as zeros; the excluded count is reported;
  - cov90 and cov50 by horizon and overall, and origin-year cells;
  - winter-h3 WIS per target relative to M1 + pooled, with intervals (England n/a), and their geometric mean.
- Both G1 variants are given.
- **DEV side:** all 69 DEV origins, passed explicitly.

### 7.13 DEV side by side
- **Winter-h3 statistics** (H1, H3, H4, H4-original, F2's WIS): one value per DEV winter season, 2018/19 to 2022/23. The truncated origins keep their as-of targets, so 2021/22 has 3 winter-h3 origins. **[default]** The one-origin 2023/24 fragment is shown but excluded from the minimum and maximum. A CONF value outside [min, max] is flagged *outside DEV's range*.
- **Coverage:** one value per assessable DEV origin-year (2018, 2019, 2021, 2022 and 2023, each with at least 6 origins) and horizon. **[default]** The flag is applied to CONF's origin-year cells (2024 and 2025) against the DEV minimum and maximum at each horizon. The pooled CONF19 value is shown beside the range as context, without a flag.
- H4b and the F2 coherence gaps have no registered range, so they are shown side by side only.

## 8. Permitted inputs (P5) and the DEV side **(agreed by Ellie on 2026-09-14: §10 row "P5 widened")**

**Pool inputs.** P5 permits "the DEV forecasts that feed CONF pools". These are the 12 files `stage_f/base_{b1,b2,m1_v3_raw}_{provider,icb,region,england}.parquet`, covering origins 2017-07 to 2023-12. `pin` records their SHA-256s, which are then copied into the plan's P5 row.

**B1 inputs are used as they are.** All four B1 files predate the ETS seed fix, so they are unseeded. Keeping them keeps every DEV-origin calibration identical to Stage D, Stage F and the P2 re-run. The consequence, disclosed in the results, is that CONF B1 pools mix unseeded DEV draws with seeded CONF ones. P0b measured the typical difference at a median of 0.25%.

**What the DEV side also needs,** generated before the tag by `prepare --dev-side` with the step-3 code, then pinned, with the generating commit recorded:
- B0 and default M1, as-of, at the 69 DEV origins;
- final-mode B0, B1, B2, default M1 and M1 v3 raw at the DEV winter-h3 origins;
- as-of B1 at the same origins, seeded, so the DEV H4 comparison is not confounded by seeded against unseeded draws.

`m2d_corr` at the 69 DEV origins already exists (`stage_h_prep/forecasts_m2d_corr.parquet`, SHA-256 `58b43b3d…`). It is copied and pinned as well.

DEV calibrated and reconciled rows are built inside the run from the pool inputs; they are not inputs.

**The permitted set is fixed.** It has 21 files: 12 pool, 1 M2 and 8 dev-side, each with its expected origin set (`common.P5_ORIGINS`; the names are `common.P5_INPUTS`). On 2026-09-14 the 12 pool files each held exactly origins 2017-07 to 2023-12 (78), and the M2 file hashed to `58b43b3d…`.
- `pin` and check 11 refuse any other set.
- `pin` also refuses a `prepare` made without `--dev-side`, so no DEV statistic can be dropped silently.
- `prepare` runs the clean-tree, import and environment checks first.
- It verifies every copied file's SHA-256, and the M2 file against the hash in `results/E-m2-rerun69/README.md`.
- It records the hash of the vintage rows any DEV origin can read. `pin` must reproduce that hash, so the DEV side was built on the pinned table.

This widens P5's permitted list, by the amendment of 2026-09-14. The alternative, regenerating everything inside the run, would have left P5 as written but taken the run from about 1.5 hours to about 3; it was not taken, and is not built.

## 9. Store, commits, crash paths

**Store (`store.py`).**
- Every step-4 and step-5 output is written to parquet under `stage_h/<tag>/step4/` or `stage_h/<tag>/scores/` as soon as it is computed.
- Each file is recorded with its SHA-256 and canonical row hash in `SHA256SUMS`, and the whole list is copied to `results/H-confirmatory/score_hashes.csv`.
- Every statistic is computed from files read back through one verifying loader. So `run`, `dry-run` and `report --from-scores` share one path, and the dry run tests the recovery path.

**Progress.** `stage_h/<tag>/progress.jsonl` holds timestamped records, written atomically: `unsealed`, `scores-about-to-be-written`, `scores-written`, `results-written`, `committed`. Until `scores-written`, stdout prints counts only.

**Crash cases.** The case is read from disk:
- *case 1:* no log line;
- *case 2:* a log line but no `scores-written`;
- *case 3:* `scores-written` present.

**Crash procedure. [default]**
- **Case 1 or 2.** A fix commit goes on top of the runner's last commit. It runs `git rm -r results/H-confirmatory`, commits `results/unseal_log.jsonl` if it holds a line, and adds the amendment row, which quotes any log line's timestamp. The step-3 outputs are moved aside to `stage_h/discarded/<timestamp>/`. The rerun then uses `--amendment TITLE`.
- **Case 3.**
  - First, commit `results/unseal_log.jsonl` and `results/H-confirmatory/` as the crashed run left them, with any code fix, in the crash-fix commit on top of the runner's last commit (H1), as in cases 1 and 2. If no code fix is needed, commit them alone. Any exit after the unseal that leaves the line uncommitted says so in a note on the exception.
  - `report --from-scores` then refuses unless HEAD's committed log holds this run's line (token = the tag commit, head = the H1 of the `unsealed` progress record) and every witness line; HEAD descends from H1 and holds its four hash files unchanged; and the tree is clean (checks 6–8 run as in step 2, with no pins, so Python or platform drift since the run is recorded, not refused).
  - The run's step-2 facts are kept in the `sealing` progress record, and the recomputed README and `provenance.json` carry them as `run_facts`.
  - It rebuilds every table from the store with zero guarded calls. Step 3's tripwires are applied across every loaded module, and a trip stops the command.
  - It re-hashes the forecast files and the M2 fits table against H1's copies.
  - It writes to `results/H-confirmatory/recomputed-<HEAD>/`, which is exempt from refuse-if-exists, and compares every recomputed table, and `verdicts.json`, with the original byte for byte. In the dry run any difference is a failure (§10), and the command exits with status 1.
  - A fix that changes any step-4 or step-5 hash is the "corrected after unsealing" case, reported alongside the original with "no re-runs" marked as not met.
  - After the report, commit `recomputed-<HEAD>/` and tag that commit by hand. A tag on the crash-fix commit before the report is not the post-run state: that commit holds no run-mode provenance.

**Step 6. [default]**
- The runner writes `results/H-confirmatory/`, reproducing the log line in it, and commits it together with `results/unseal_log.jsonl`.
- It prints the Stage H summary: every verdict, the primary comparison, and the DEV and CONF tables side by side.
- It prints the `git tag -a conf-run-v1` command. Tagging and pushing stay deliberate human acts, done only after the accounting has passed. The tag must be annotated: a lightweight tag is not the post-run state.

**Post-run state (`conf-run-v1`, P11).** It holds only if `seal_rules.post_run_problems` finds nothing wrong, that is, if all of these hold at PROJECT_ROOT:
1. `refs/tags/conf-plan-v1` exists; T is its commit.
2. `refs/tags/conf-run-v1` is an annotated tag, and its commit R descends from T. Both tags are resolved as `refs/tags/NAME`, never by git's short-name lookup.
3. R holds a completed run's record: a run-mode `results/H-confirmatory/provenance.json` or `recomputed-*/provenance.json` (`extra.mode` is "run" and `extra.unseal_entry` an object). E is that entry. All such files agree, and `results/H-confirmatory/unseal_entry.json`, if R holds it, equals E (parsed JSON is compared, not bytes). A crash-fix commit that removed `results/H-confirmatory`, or a case-3 crash-fix commit before `report --from-scores`, fails here.
4. R's committed `results/unseal_log.jsonl` ends with E and holds it once. E's token is T and its argv a stage_h run. Its head H is a full SHA before R, the runner's hash commit on a parent S that is T or after T, and R holds H's four hash files byte for byte (`_on_h1`'s relation). E is anchored to R's own records, so after a case-2 crash and an amendment rerun the crashed run's line, whose head is a real hash commit too, is one of the other lines, disclosed as in 5.
5. Every other line of R's log is disclosed: a §10 row absent at T, in R's or HEAD's committed preregistration, quotes its timestamp as a whole ISO-8601 value. HEAD's rows count, so a stray line found later can be disclosed rather than deleted. A line with an empty timestamp is never disclosed.
6. Every line of every worktree's log (`git worktree list`) and of the witness is E or disclosed as in 5. Absent or empty files pass.
7. Any git error, missing object, or unreadable or unparseable file keeps the seal: the check fails closed.

In the post-run state `assert_not_sealed` returns for token None or T, without a log line, so later live calibrations add no entry (plan §10); any other token raises. A state that holds is cached for the process, keyed by both tag commits, HEAD and the bytes of every log and the witness. **[default]** No network call is made: the push of `conf-run-v1` is checked by hand after the printed `git push`. **CI:** the workflow's `actions/checkout@v4` clones at depth 1 without tags, so the post-run state cannot hold there, and every sealed read in CI raises, as before the run. A calibrated forecast built in CI would need `fetch-depth: 0` and the tags; under D5 = (b) the live model is uncalibrated, so none is needed.

**Plan text changed before the tag** (P7 rows):
- P11's HEAD rule (§4): H1 only at the seal, and the argv rule;
- P11's post-run condition becomes the state above (every log line is either the conf-run-v1 run's entry, anchored to R's own records, or disclosed by timestamp in a §10 row), replacing "exactly one line";
- P13's path;
- P5's input list (§8);
- the empty-log rule of step 2 gains the `--amendment` exception.

## 10. The dry run (P3)
- **Origins:** 2023-07 to 2023-12, treated as CONF-like. E = 2023-12.
- **Inputs:** restricted to origins before 2023-07; the six dry-run origins are regenerated.
- **Seal:**
  - no token, and no explicit guarded call;
  - zero new log lines anywhere, and no witness change;
  - the runner-side guards (§2.5) are active, with token None.
- **Step 2 in dry mode:** as §3.2 says.
- **Outputs:** only to `data/processed/stage_h_dry/<head>/` and `results/H-dryrun/`. The latter holds DEV-only results and is committed as P3 evidence.
- **Scoring:** `score_forecasts(..., None)` drops every row with period 2024-01 or later as embargoed. Those are exactly the 15 of 36 origin × horizon pairs (for every series present at those keys). No 2024 period is scored.
- **Statistics:** every function runs on the store's read-back.
  - With a unit list fixed across horizons, n = 6 and l = 3 at every horizon. Zero-denominator resamples at h5 and h6 are dropped and counted.
  - Cells with fewer than 3 contributing origins are marked origin-degenerate.
  - Winter h3 has one origin (2023-10), so LOO is empty and fragility is n/a.
- **M2 retry path:** exercised by forcing one retry at 2023-08. The result is compared with `seed_stability/m2d_corr/2023-08_s1000.parquet`.
- **Reproduction checks,** as oracles outside the run proper:
  - B2 and M1 v3 raw forecasts must equal the DEV inputs, and `m2d_corr` must equal `stage_h_prep`, bit for bit;
  - B0, default M1 and final-mode rows must equal the `--dev-side` files;
  - DEV-origin calibrated rows must equal the P2 re-run's, for B1 at origins up to 2023-06 only;
  - DEV-origin reconciled rows must equal `stage_f_g1/mint_*`, for origins before 2023-07;
  - `stage_f.h3_table` pooled over the DEV winter-h3 rows must reproduce `results/F-reconciliation-G1/h3_results.csv`;
  - the G1 counts must match `results/F-reconciliation-G1/failed_counts.csv`.
- `report --from-scores` on the dry-run store must give byte-identical CSVs and zero log lines.

## 11. Tests (P3)
- **`h1_table`:**
  - tested MASE at 0.8 × the reference gives rel = −0.20 and *confirmed*;
  - pooled-target `n_pairs` equals the row count;
  - the default keys give 3× (negative control);
  - boundaries: −0.15 exactly and 0.
- **Fragility:**
  - H1: not confirmed, with one target clearly failing and another straddling, is not fragile;
  - two targets that flip under different dropped origins are not fragile;
  - confirmed, with one target straddling, is fragile;
  - the full-sample-differs extension;
  - H3: both clauses failing with only one straddling is not fragile, and holding with one straddling is fragile;
  - H4: the rel_lo/rel_hi rules, a ranking flip, and "refuted" with every refuting element fragile.
- **Two-way bootstrap:**
  - all rows covered gives [1, 1];
  - it is reproducible under seed 0;
  - n = 19 gives block starts 0..16 and 19 slots;
  - the end-effect multiplicities match §7.4;
  - rows are weighted equally;
  - D7 folding;
  - provider-only equals every origin weight set to 1;
  - a zero-denominator resample is dropped;
  - a gap in the origin list;
  - n < 3 and origin-degenerate cells.
- **Verdicts:** every coverage verdict at the 0.85 and 0.95 edges, *neither*, direction naming, and the fragility table.
- **Pools:**
  - the pool's origin set advances at each CONF-like origin, with a frozen first-release table detected as a negative control;
  - the first-release table used at origin t holds every period published by t, including a late submitter and three consecutive lost originals (provider, ICB, and aggregates with the completeness rule);
  - DEV-origin calibrations and reconciliations are unchanged when CONF-like origins are appended;
  - on real DEV data, the freeze-and-jump at 2018-11/12 and 2021-10/11;
  - the runner-side guards raise on a sealed period without a token (negative control: E = 2025-09 in dry mode).
- **MinT:** `reconcile_frames` reproduces `reconcile_model`.
- **Seal:**
  - a tokened **rehearsal** in a temporary git repository with a real annotated `conf-plan-v1` tag, run on a synthetic vintage table with real calendar dates (2016–2026) and stub forecasters. `splits` is pointed at the temporary repository and its log, but `_tag_commit` and `_head_commit` are not faked, and the first tokened call's HEAD, argv and tree rules (P11) run for real; only its import rule is stubbed, since the temporary repository imports `nhs_ae` from the worktree. Tripwires refuse any file outside `tmp_path`. It asserts:
    - exactly one log line, whose `head` is the hash commit;
    - every guarded call received the token;
    - CONF-only frames were scored with the token and DEV-only frames without it;
    - the step-6 commit holds the results and the log;
    - the real worktrees' logs are unchanged;
  - HEAD rule cases (step 2's start commit and §4's hash commit):
    - accepted: the tag; tag + hash commit; amendment descendant + hash commit;
    - refused: a hash commit touching another path; two stacked hash commits; a hash commit that modifies a file;
  - P11, on temporary repositories (`tests/test_seal_rules.py`, `test_splits.py`, `test_seal_guards.py`, `test_backtest_cli_seal.py`): at the seal, H1 accepted and S itself refused, with the argv, tree and import rules and the per-process context; the post-run state and each way it fails; the guards in `online` and `stage_f`; the CLI's refusals. The rehearsal adds the amendment path end to end (case 3), and the post-run state on a real run's step-6 commit and on case 3's recomputation commit;
  - crash cases:
    - the guarded call raises before writing, so zero lines are accepted and the original exception surfaces;
    - a raise after scoring gives one line and `scores-written`;
    - a rerun with k = 1 under `--amendment` is accepted;
    - a reverted log is refused, and so is a fix branch cut from the tag while the witness holds a line;
  - a worker sees no token in `sys.argv` or `os.environ`;
  - worker `initargs` carry the run's vintage path;
  - the step-3 tripwires, run with `jobs=2`;
  - `report --from-scores` makes zero guarded calls, and a tampered score file is refused.
- **Step 2:** each check on a synthetic git repository:
  - clean tree and HEAD, including the descendant rule;
  - freeze, pins read from the tag, and the data/pin/lock diff refusal;
  - logs and witness;
  - output directories and the quarantine path.
- **H4 and H4b:**
  - the common-row ranking ignores extra rows;
  - the H4b identity;
  - window alignment at a synthetic truncated origin;
  - the lost-originals split.
- **Report:**
  - the primary report holds the 12 origin-year cells;
  - a frame mixing slices is written as one file per slice, each holding one value;
  - every registered verdict path is rendered, with None shown as n/a;
  - the rehearsal's tables carry their slice columns.

## 12. Not in P3
- Running `pin` and `prepare` for real (P4, P5), after Ellie agrees to §8.
- The P11 changes (`seal_rules.py`, `splits.py`, the guards in `online` and `stage_f`, and `cli`). They are not part of P3; they landed as separate work on 2026-09-14, once Ellie permitted the `splits.py` edits (§1, §2.10, §9).
- The P13 quarantine move.
- The P10 and P14 corrections to Appendix A.
- The P7 amendment rows other than "Stage H implementation details" and the plan-text changes listed in §9.
