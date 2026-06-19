"""Per-finding confidence model.

Four independent axes, per the v7 confidence gate. For RAF-1a, ``match`` and
``recovery`` must stay ``LOW`` until Gate 3 is verified — encoded in the factory
below so a mere candidate can never *look* confident.
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

    extraction: ConfidenceLevel  # did we read the source rows correctly?
    rule: ConfidenceLevel  # does the policy clearly apply?
    match: ConfidenceLevel  # is the order<->charge join sound + Gate 3 met?
    recovery: ConfidenceLevel  # is the money actually recoverable?

    @classmethod
    def for_unverified_candidate(cls) -> "Confidence":
        """A detected-but-unverified candidate: extraction/rule can be high, but
        match and recovery are LOW until Gate 3 is resolved by a human/API."""
        return cls(
            extraction=ConfidenceLevel.HIGH,
            rule=ConfidenceLevel.HIGH,
            match=ConfidenceLevel.LOW,
            recovery=ConfidenceLevel.LOW,
        )
