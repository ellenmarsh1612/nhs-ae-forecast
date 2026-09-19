# Provenance of this snapshot

This repository is a snapshot, without history, of the private working repository
`nhs-ae-forecast-dev` at commit `e7c224c5cfa7f5e778bb1db17e85277a7656329c`. It was assembled by
`site/build_snapshot.py`, which lists in its own docstring everything left out and why.

## What is here

* `src/`, `tests/` — the code and its suite, unchanged.
* `docs/` — the pre-registration, the amendment log, the confirmatory plan and design, the
  confirmatory results, the live-forecast handover, and the brief for the portfolio site.
* `results/H-confirmatory/` — the sealed run's own output, byte-identical, including its
  provenance and unseal records.
* `results/F-reconciliation*/`, `results/G-decision/` — summaries of the reconciliation and
  decision-layer work. **Every decision-layer figure is illustrative only**: the registered
  validation failed (median error 8.7 pp against a 5 pp tolerance), and that label travels
  with every table derived from it.
* `site/` — one machine-readable file of every number the portfolio site may show, each with
  the path it was read from, plus the figures built from it.
* `data/processed/ae_monthly_all_vintages.parquet` — the vintage panel (1.9 MB).

## What is not here

* `data/raw/` — 106 MB of archived NHS England files. Rebuild it with
  `nhs-ae-ingest run`, which fetches from NHS England, or `nhs-ae-ingest discover` to list
  the URLs first. The panel above is the parsed result, so nothing here needs it.
* Documents the confirmatory run no longer supports, and a machine-specific runbook. They
  remain in the private repository; `site/REPORT.md` lists every claim and where it failed.

## Absolute paths in the run records

`results/H-confirmatory/provenance.json`, `unseal_entry.json`, `README.md` and
`results/unseal_log.jsonl` contain absolute paths from the machine the confirmatory run was
made on, including the path of the token file it read. The token's *value* is the plan
commit `14202e2`, which is public by design. These files are the integrity record of the
run: editing them would break the hashes that make the record checkable, so they are left
exactly as the run wrote them.
