"""Calibration layers applied to a model's quantile forecasts after the fact (Stage D).

``online.py`` holds the three post-hoc methods (pooled split conformal, per-series
conformal with shrinkage, DtACI) that walk through a backtest's forecast table origin by
origin. EnbPI needs refits, so it is a forecaster in ``models/enbpi.py`` instead.

Rule every method obeys: at origin *t* a method may learn only from forecasts whose target
month had been published by *t* (``first_release``), using the value as first published.
An h-step-ahead interval is therefore checkable no earlier than h months after it was
issued. Ignoring that delay would let a backtest learn about the April 2020 collapse at
the April 2020 origin, a month before the data existed.
"""
