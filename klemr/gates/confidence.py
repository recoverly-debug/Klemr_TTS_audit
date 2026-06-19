"""Per-finding confidence model.

Four independent axes, per the v7 confidence gate. The axes are kept orthogonal so a
weak finding is explainable:
- ``extraction`` — did we read the source rows correctly?
- ``rule``       — does the policy clearly apply?
- ``match``      — is the entity resolution / order<->charge join sound? (join quality ONLY)
- ``recovery``   — is the money actually recoverable? (this is where the decisive,
                   human/API-verified Gate 3 lives — NOT in ``match``)

For RAF-1a the order_id join is clean, so an unverified candidate has HIGH ``match``
(the join is sound) but LOW ``recovery`` (Gate 3 unresolved). ``match`` stays a real
signal for claim types where the join is fuzzy.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


class ConfidenceLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Confidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    extraction: ConfidenceLevel  # read the source rows correctly?
    rule: ConfidenceLevel  # does the policy clearly apply?
    match: ConfidenceLevel  # entity resolution / join quality (NOT Gate 3)
    recovery: ConfidenceLevel  # actually recoverable? (Gate 3 / filability lives here)

    @classmethod
    def for_unverified_candidate(cls) -> "Confidence":
        """A detected-but-unverified RAF-1a candidate: extraction/rule high and the
        order_id join is clean (``match`` HIGH), but recovery stays LOW until the
        decisive Gate 3 is resolved by a human/API."""
        return cls(
            extraction=ConfidenceLevel.HIGH,
            rule=ConfidenceLevel.HIGH,
            match=ConfidenceLevel.HIGH,
            recovery=ConfidenceLevel.LOW,
        )
