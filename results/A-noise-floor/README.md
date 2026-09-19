# results/A-noise-floor

Stage A of the 2026-09-10 work order. Produced by
`nhs-ae-backtest noise-floor --jobs 4` on 2026-09-10 at commit `c58be85`.

- `seed_runs.csv`: one row per run × seed × slice × target
- `noise_table.csv`: mean, SD, min–max per run × slice × target, with the minimum meaningful differences
- `noise_floor.md`: the report and the STOP 1 summary
- `fig_seed_vs_config.png`: seed noise against the 16 search configurations on the search's slice
