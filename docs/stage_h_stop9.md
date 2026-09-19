# STOP 9: the go-ahead for `conf-plan-v1`

Prepared on 2026-09-15 for Ellie. It covers the commit that adds this file to `merge-check`
(`git log -1 --format=%H -- docs/stage_h_stop9.md`); that commit is the one to be tagged.
Nothing in the plan has been run on CONF: no token has been used, no tag exists, and every
unseal log is empty.

## What the go-ahead approves

1. **The confirmatory plan, v1.0** (`docs/confirmatory_plan.md`), as committed. The v1.0 pass
   brought text written before D1 and D5 into line and made §6 match the runner; no rule,
   threshold or decision changed except as D-21 below states (plan §12 items 20–21).
2. **The design's [default] choices, as a block** (`docs/stage_h_design.md` v2.2; all 50 are
   listed, with their alternatives and stakes, in `docs/stage_h_defaults.md`), subject to the
   three decisions below. Overruling one later needs an amendment row, and any code change it
   implies, before the tag.
3. **The §10 rows dated 2026-09-13 to 2026-09-15** in `docs/preregistration.md`: G1 and its
   re-run, the two "Stage H implementation details (P3)" rows, "P5 widened", "Seal hardening
   (P11) and the post-run seal state", "Appendix A corrected (P10)", the ten P7 rows (H1, H2's
   "neither", the phase-1b override, H4, H4b, H5, F2 on CONF, P12, P13, the unmet DEV
   calibration target).
4. **Then:** `conf-plan-v1` is tagged on this commit and pushed (P9), and Stage H runs by
   `docs/stage_h_run_sheet.md`, sections B–F.

## Three decisions

**Decided by Ellie on 2026-09-15, as recommended** (§10 row "STOP 9 decisions"): D-1 confirmed and
closed to the list below, now also in design §2.1; D-20 Künsch kept; D-21 4 or more of the 19 counted
units. What remains is the go-ahead itself.

**D-1. The training-residual exception.** *Recommendation: confirm it, narrowed to a closed
list.* The frozen models compute residuals on their own training data while making their
registered forecasts: default M1's 12-month in-model conformal step, B0's in-sample errors,
and fitting itself. At CONF origins, and at the live origin, that training data include 2024–26
months. These residuals are never saved or printed, and no issued forecast is compared with an
outturn, so the P12 row and design §2.1 treat them as outside the seal; without the exception
no registered model could be run at a CONF or live origin at all. The row's list ends with
"model fitting", which is open-ended. The closed list, as decided: *the residuals, losses,
likelihoods and residual correlations computed on as-of training data by default M1's fitting
and its in-model conformal step, B0's in-sample errors, and the fitting of B1, B2, M1 v3 raw and
`m2d_corr`; and, in the live pipeline, the raw ETS fit and the unpublished M2f-r4 shadow fit.*
None is saved or printed; anything else needs an amendment row.

**D-20. Moving blocks in the two-way coverage bootstrap.** *Recommendation: keep the
registered Künsch scheme.* With 19 origins, Künsch blocks give the first and last origin
units about 0.41 and 0.35 of an interior origin's weight; circular blocks give every origin
equal weight, but switching needs a code change, tests and a new dry run. Checked on DEV on
2026-09-15: on two 19-origin windows (2021-12 to 2023-06, and 2020-06 to 2021-12 across COVID),
circular blocks change no horizon's reading and no verdict of the primary, the largest
endpoint shift is 0.69 pp, and over 100 seeds the verdict never differs between the schemes.

**D-21. When H2's M2 clause is not evaluable.** *Recommendation: 4 or more of the 19 counted
origin units failing (21%), with the 21-fit count alongside; a failed 2025-07 fit is not
replaced by 2025-08 or 2025-09.* This is the design's reading, and the v1.0 plan's §6 step 3
now states it. Plan v0.4 said "more than 20% of an M2 model's origins", which over 21 fits
means 5 or more; the two differ only at exactly four failures. The design counts units
because D7 counts 19 information sets, and the three 2025 fits share one. If you prefer the
v0.4 reading, that line changes back before the tag.

## Read before approving (no decision needed)

- **Fragility labels (D-23, D-25, D-27).** A leave-one-origin-out verdict is also labelled
  fragile when the full-sample verdict differs from any subset's, a little stricter than the
  plan's range rule. It changes labels, not verdicts.
- **Four statements corrected today** (plan §12 item 21; `docs/stage_h_defaults.md`): the plan's
  H4b lost-originals periods (empty on the 19 counted origins); M2's ICB level (where it was
  fitted and frozen; the §9 fallback's trigger was never tested); at the truncated DEV origins
  2018-11 and 2021-10 the as-of and final rows do not pair, so both drop out of H4's DEV side;
  Appendix A's heading ("excluded") is superseded by its keep rule.
- **The run itself (D-5).** Python and the platform must match the pins, so no macOS, conda or
  pip update until `conf-run-v1`. The final dry run logged load averages of 6.8 to 12; close
  other heavy work before `run`.

## Ready: what was checked on 2026-09-15

| Item | State | Evidence |
|---|---|---|
| Code | frozen | 730 tests passed at `026c420`; only documents and pins have changed since |
| Environment | matches the pins | `pip freeze` equals `requirements-lock.txt`; Python 3.13.12; macOS 15.2 arm64 |
| Inputs (P5) | 21 pinned | `prepare --dev-side` at `026c420`; `pin` at `d8ff305`; SHA-256s in plan §7.1 |
| Data (P4) | pinned | manifest SHA-256 `0adeded9…`; the rebuild equals the shared table (1,072,039 rows; 8 parse failures, pinned) |
| D7 | holds | the 2025-07, 2025-08 and 2025-09 as-of slices hash equal (`54181891…`) |
| Quarantine (P13) | pinned | `quarantine/pre-seal/backtest/forecasts.parquet`, `6c369958…` |
| Seal | closed | no `conf-*` tag locally or on origin; every worktree's unseal log empty or absent; no witness file |
| Final dry run | exit 0 | `8398d8b`, `results/H-dryrun/d8ff305dbbd7/`: every statistic computed; `report --from-scores` byte-identical; reproduction identical |
| `preflight` | clean | on `8398d8b`; run again on this commit before the go-ahead |
| Pre-flight P0–P14 | done | all but P9, the tag itself (plan §7) |

## From now until `conf-run-v1`

- **Frozen code and data.** A change to check 11's generation code means `prepare --dev-side`,
  `pin` and a new dry run; a change to `data/raw` means `pin` again; any other code change means
  a new dry run. Documents may change before the tag, never after.
- **Do not merge `main`.** The archive bot adds a line to `data/raw/manifest.jsonl` on `main`
  each day until the 21st (it is already one commit ahead); merged, it would make the run refuse.
- **The machine.** Mains power, lid open, nothing else heavy, and hands off the worktree while
  `run` works (`docs/stage_h_run_sheet.md`, section 0).

## Giving the go-ahead

Write it in the conversation, naming the commit, for example: *"Go ahead: tag `<commit>` as
`conf-plan-v1` and run Stage H."* The three decisions are already recorded. Tagging and pushing are yours to do, or to tell me to do (P9); the run sheet
gives every command, and the token goes from git straight into a file, never onto a command
line.
