"""Claim state machine — the locked full lifecycle (transitions wired as the lanes land).

    candidate -> needs_verification -> {review} -> filable | held | dismissed[T]
    filable -> packet_built -> filed -> approved | rejected | disputed
    approved -> credited -> closed[T]
    rejected -> dismissed[T] | review

Terminals: ``dismissed`` and ``closed``. ``packet_built`` is NOT terminal.

Invariants this enforces:
- A candidate is only ever a *ceiling*: it cannot jump straight to ``filable`` — it
  must pass through ``needs_verification`` (Gate 3).
- ``seller_canceled`` (Gate 3 = NOT exempt) routes to terminal ``dismissed`` (carrying
  a ``tier2_appeal_candidate`` flag in the resolution metadata), never to ``held``.
  ``held`` is reserved for not-yet-resolved reasons (immature / unverified / tier2_appeal).

The filed-onward states/transitions exist now so Step 3+ builds on a stable contract;
they are not yet exercised until the reconciliation + recovery lanes land.
"""
from __future__ import annotations

from enum import Enum


class ClaimState(str, Enum):
    CANDIDATE = "candidate"
    NEEDS_VERIFICATION = "needs_verification"
    REVIEW = "review"
    FILABLE = "filable"
    HELD = "held"
    DISMISSED = "dismissed"  # terminal
    PACKET_BUILT = "packet_built"
    FILED = "filed"
    APPROVED = "approved"
    REJECTED = "rejected"
    DISPUTED = "disputed"
    CREDITED = "credited"
    CLOSED = "closed"  # terminal


TERMINAL_STATES: frozenset[ClaimState] = frozenset(
    {ClaimState.DISMISSED, ClaimState.CLOSED}
)

# Allowed forward transitions. Anything not listed is rejected.
ALLOWED_TRANSITIONS: dict[ClaimState, frozenset[ClaimState]] = {
    ClaimState.CANDIDATE: frozenset({ClaimState.NEEDS_VERIFICATION}),
    ClaimState.NEEDS_VERIFICATION: frozenset(
        {ClaimState.REVIEW, ClaimState.FILABLE, ClaimState.HELD, ClaimState.DISMISSED}
    ),
    ClaimState.REVIEW: frozenset(
        {ClaimState.FILABLE, ClaimState.HELD, ClaimState.DISMISSED}
    ),
    # held = not-yet-resolved (immature / unverified / tier2_appeal): can resolve later.
    ClaimState.HELD: frozenset(
        {ClaimState.FILABLE, ClaimState.DISMISSED, ClaimState.REVIEW}
    ),
    ClaimState.FILABLE: frozenset({ClaimState.PACKET_BUILT, ClaimState.HELD, ClaimState.REVIEW}),
    ClaimState.PACKET_BUILT: frozenset({ClaimState.FILED}),  # NOT terminal
    ClaimState.FILED: frozenset(
        {ClaimState.APPROVED, ClaimState.REJECTED, ClaimState.DISPUTED}
    ),
    ClaimState.APPROVED: frozenset({ClaimState.CREDITED}),
    ClaimState.CREDITED: frozenset({ClaimState.CLOSED}),
    ClaimState.REJECTED: frozenset({ClaimState.DISMISSED, ClaimState.REVIEW}),
    ClaimState.DISPUTED: frozenset(
        {ClaimState.APPROVED, ClaimState.REJECTED, ClaimState.DISMISSED}
    ),
    ClaimState.DISMISSED: frozenset(),  # terminal
    ClaimState.CLOSED: frozenset(),  # terminal
}


def can_transition(src: ClaimState, dst: ClaimState) -> bool:
    return dst in ALLOWED_TRANSITIONS.get(src, frozenset())


def is_terminal(state: ClaimState) -> bool:
    return state in TERMINAL_STATES
