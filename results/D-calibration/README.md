# results/D-calibration

Stage D of the 2026-09-10 work order, produced by `nhs-ae-backtest calibration --jobs 6` on 2026-09-10 at commit `47da87d`. Design and selection rule: pre-registration amendment of 2026-09-10 (Stage D design).

- `coverage_by_horizon_year.csv`: 90%/50% coverage per candidate × origin-year × horizon (target = all, or per target), region assessable / covid_window, origins, assessed, in_band
- `wis_winter_h3.csv`: winter horizon-3 WIS per candidate and target, relative to raw ETS with 95% paired bootstrap intervals over providers
- `pareto.csv`, `fig_pareto.png`: acceptance check and Pareto front
- `stop4.txt`: the STOP 4 summary
- `decision_loss.md`: written after Stage G (selection by decision loss needs the occupancy check)
