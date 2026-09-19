# results/H-confirmatory

Written 2026-09-15T18:12:28+00:00 by `python -m nhs_ae.evaluate.stage_h run` (design: `docs/stage_h_design.md`).

## Provenance

In full in `provenance.json` ("facts": step 2's checks; "extra": the run's).

### Facts

- **tag_object**: `"c4e72e0d6c82b55c45282a5f11bc7b83206e0e7d"`
- **tag_commit**: `"14202e21f6049927dda363c4cf634ca61e6fe62a"`
- **head**: `"14202e21f6049927dda363c4cf634ca61e6fe62a"`
- **amendment**: `null`
- **log_oneline**: `""`
- **diff_stat**: `""`
- **python**: `"3.13.12"`
- **platform**: `"macOS-15.2-arm64-arm-64bit-Mach-O"`
- **env_drift**: `{}`
- **manifest_sha**: `"0adeded94ccf43506c8f01158f3477ed426147f36b6c695682ee3f1ddc7ee293"`
- **stored_files**: `501`
- **reference_files**: `4`
- **n0**: `0`
- **prior_lines**: `[]`
- **witness_lines**: `0`
- **inputs**: `21`
- **gen_commit**: `"026c4202c3a168c8aed7333b62d71b9f9e182269"`
- **quarantine**: `"data/processed/quarantine/pre-seal/backtest/forecasts.parquet"`
- **quarantine_sha**: `"6c369958a08ef4443de7a899b58bb107d599e8370ea1492f9089748d8e7f9614"`
- **loadavg**: `[2.81, 6.15, 6.0]`
- **vintages**: `{"path": "/Users/trin3615/Documents/NHS_forecast/merge-check/data/processed/stage_h/14202e21f6049927dda363c4cf634ca61e6fe62a/vintages/ae_monthly_all_vintages.parquet", "row_hash": "db419ce45b6039a230fa9db4d0d7c5ac8022987ff210df913515ee75ee038b70", "rows": 1072039, "failures": ["data/raw/2023-05-11/August-2022-AE-by-provider-revised-110523-1Gqhs.xls", "data/raw/2023-05-11/December-2022-AE-by-provider-UScya-revised-110523.xls", "data/raw/2023-05-11/October-2022-AE-by-provider-vM3Lk-revised-110523.xls", "data/raw/2023-11-09/August-2023-AE-revised-91123-by-provider-H18X9.xls", "data/raw/2023-11-09/September-2023-AE-revised-91123-by-provider-bnE2T.xls", "data/raw/2025-09-11/October-2022-AE-by-provider-vM3Lm-revised-110523.xlsx", "data/raw/2026-05-14/December-2025-AE-by-provider-revised-F5epgl.xls", "data/raw/2026-06-11/November-2025-NEL-YTD-Growth-rates.xls"], "manifest_sha": "0adeded94ccf43506c8f01158f3477ed426147f36b6c695682ee3f1ddc7ee293"}`
- **d7_slices**: `{"2025-07": "5418189190e649557646a559a8a7094b380344c85166508699cce88593150a99", "2025-08": "5418189190e649557646a559a8a7094b380344c85166508699cce88593150a99", "2025-09": "5418189190e649557646a559a8a7094b380344c85166508699cce88593150a99"}`

### Extra

- **mode**: `"run"`
- **start**: `"14202e21f6049927dda363c4cf634ca61e6fe62a"`
- **hash_commit**: `"f56db9e95a0f8b19694e82a7e9070826699a678b"`
- **unseal_entry**: `{"timestamp": "2026-09-15T18:04:53+00:00", "token": "14202e21f6049927dda363c4cf634ca61e6fe62a", "head": "f56db9e95a0f8b19694e82a7e9070826699a678b", "argv": ["/Users/trin3615/Documents/NHS_forecast/merge-check/src/nhs_ae/evaluate/stage_h/__main__.py", "run", "--unseal-token-file", "/Users/trin3615/.stage_h/conf-plan-v1.token", "--jobs", "8"], "sealed_rows": 21, "origins": ["2024-01-01", "2025-09-01"]}`
- **inputs_source**: `"stage_h/inputs"`
- **lock_sha256**: `"fbb0311275776816cb1a388902a188e9c48aa1cf065ed4899433a718d62d70ed"`
- **pins_blob**: `"5dd573ca1faa2e08d3221b4935755f258476e052"`
- **tables_written**: `175`

## Files

- `confirmatory_results.md`: the verdicts, the primary comparison and every label
- `verdicts.json`: every non-table result, None as null
- `tables/`: one CSV per table and slice; a table whose slice columns hold several values is written as one file per value (plan §5, design §7.1)
- `score_hashes.csv`: the store's SHA-256s and row hashes (the crash policy's score files)
- `provenance.json`: every fact and field above, in full
