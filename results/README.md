# Results in this snapshot

The full working repository holds twenty result directories; this snapshot ships the ones a
reader needs to check the confirmatory claims, plus the sources `site/build_numbers.py`
reads. The development-window documents in `docs/` cite the others by name.

| Path | What it holds |
|---|---|
| `H-confirmatory/` | **The confirmatory run** of 2026-09-15 (tag `conf-run-v1`): `verdicts.json`, 175 tables under `tables/`, the run's `provenance.json`, its `unseal_entry.json`, the P13 and D7 integrity checks, the M2 fit diagnostics and the timings. Summarised in `docs/confirmatory_results.md` |
| `unseal_log.jsonl` | The sealed window was opened once. This is that one line |
| `F-reconciliation/`, `F-reconciliation-G1/` | H3 and F2 on the development window. **Read the G1 re-run**: without that guard, ETS's all-zero forecasts at origin 2020-05 turn its rows into artefacts (+3,449% at provider level, against +5.4% guarded) |
| `G-decision/` | The decision layer, **illustrative only**: `occupancy_validation.md` records the registered check failing at 8.7 pp against a 5 pp tolerance, and every table derived from it carries that label |
| `D-calibration/` | Coverage by origin-year and horizon for the calibration candidates, including the 2020 COVID cells the confirmatory table excludes by design |
| `A-noise-floor/` | The seed-noise floor: how much a metric moves when only the random seed changes, which is what any tuning gain has to beat |
| `m1-tuning/` | The 16 pre-registered hyperparameter configurations and their scores |

Provenance and what was left out: `PROVENANCE.md`. Verification: `site/REPORT.md`.
