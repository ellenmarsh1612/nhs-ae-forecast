"""Evaluation harness (phase 1, week 2 – built BEFORE any real model).

- asof.py    : what was known at an origin. ``load_asof(origin, mode)`` returns the
               training data as it stood on the second Thursday of the origin month
               (as-of mode) or with every period at its latest revision (final mode);
               ``load_truth`` is the outturn. Panels per target and hierarchy level.
- metrics.py : weighted interval score, pinball loss, coverage at 50/90%, MASE against
               the in-sample seasonal-naive scale, PIT, paired bootstrap over series.
- harness.py : rolling-origin backtest driving every model through the same code path
               in both modes; fixed forecast-table contract; scored frame.
- cli.py     : ``nhs-ae-backtest run | summary``.
- report.py  : (to come) scorecard tables and calibration plots.
"""
