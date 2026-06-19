"""Reconciliation — the deterministic 'accountant' (Step 3).

Applies a claim type's rule to canonical events + charges to produce Finding
Candidates and the detection funnel, splitting genuine anomalies from the
informational (out-of-scope / not-in-settlement) buckets. Reproduces
``reference/detect.py``. Not implemented in this slice.
"""
