"""Hierarchical reconciliation (phase 1, week 5).

- MinT (shrinkage) for point forecasts.
- Sample-based reconciliation for probabilistic forecasts (reconcile each posterior /
  bootstrap sample path, then take quantiles) so intervals stay coherent.
- Compare against the PyMC model's native coherence.
"""
