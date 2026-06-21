"""Reconciliation — the deterministic 'accountant' (Step 3).

Composes a claim plugin's predicates over the canonical dataset into provenance-linked
Findings + the detection funnel, then (separately) applies verified Gate-3 resolutions.
Reproduces ``reference/detect.py``'s funnel.
"""
from klemr.reconciliation.coverage import RecheckNote, recheck_next_settlement
from klemr.reconciliation.engine import (
    Anomaly,
    OutOfScopeRow,
    ReconciliationResult,
    apply_resolutions,
    reconcile,
    resolve_finding,
    run_fingerprint,
)
from klemr.reconciliation.finding import (
    CreditMatchKey,
    Finding,
    HoldReason,
    make_finding_id,
)

__all__ = [
    "reconcile",
    "apply_resolutions",
    "resolve_finding",
    "run_fingerprint",
    "ReconciliationResult",
    "Anomaly",
    "OutOfScopeRow",
    "Finding",
    "CreditMatchKey",
    "HoldReason",
    "make_finding_id",
    "RecheckNote",
    "recheck_next_settlement",
]
