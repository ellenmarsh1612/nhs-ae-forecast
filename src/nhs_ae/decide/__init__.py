"""Decision layer (phase 1, week 6).

admissions forecast samples × emergency length-of-stay distribution → bed-days
→ vs general & acute bed stock (KH03) → P(occupancy > 92%) per trust per month
→ escalation beds required at a chosen breach-probability threshold, with cost-loss.

Phase 2 (allocation.py): two-stage stochastic programme allocating a fixed ICB budget of
escalation beds / agency shifts across trusts against the forecast scenario set.
"""
