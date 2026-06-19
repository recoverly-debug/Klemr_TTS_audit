"""Confidence gate + the human-review (Gate 3) gate.

Step 1 ships the confidence model. The review-queue / resolution-write gate — the
decisive, surfaced-in-the-UI gate that must never be inferred from data — is
implemented in Step 4.
"""
from klemr.gates.confidence import Confidence, ConfidenceLevel

__all__ = ["Confidence", "ConfidenceLevel"]
