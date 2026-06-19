"""Claim state machine (minimal).

candidate -> needs_verification -> {filable | held | review} -> packet_built

A candidate is only ever a *ceiling*. It cannot jump straight to ``filable``: it
must pass through ``needs_verification`` (Gate 3), enforcing the invariant that
nothing is filable without a recorded ``auto_approved`` resolution.
"""
from __future__ import annotations

from enum import Enum


class ClaimState(str, Enum):
    CANDIDATE = "candidate"
    NEEDS_VERIFICATION = "needs_verification"
    FILABLE = "filable"
    HELD = "held"
    REVIEW = "review"
    PACKET_BUILT = "packet_built"


# Allowed forward transitions. Anything not listed is rejected.
ALLOWED_TRANSITIONS: dict[ClaimState, frozenset[ClaimState]] = {
    ClaimState.CANDIDATE: frozenset({ClaimState.NEEDS_VERIFICATION}),
    ClaimState.NEEDS_VERIFICATION: frozenset(
        {ClaimState.FILABLE, ClaimState.HELD, ClaimState.REVIEW}
    ),
    # A held/review claim can be re-verified and move between resolved states.
    ClaimState.REVIEW: frozenset({ClaimState.FILABLE, ClaimState.HELD}),
    ClaimState.HELD: frozenset({ClaimState.FILABLE, ClaimState.REVIEW}),
    ClaimState.FILABLE: frozenset({ClaimState.PACKET_BUILT, ClaimState.HELD, ClaimState.REVIEW}),
    ClaimState.PACKET_BUILT: frozenset(),
}


def can_transition(src: ClaimState, dst: ClaimState) -> bool:
    return dst in ALLOWED_TRANSITIONS.get(src, frozenset())
