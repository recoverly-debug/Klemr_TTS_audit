"""Claim-type plugins, registry, and the claim state machine.

``default_registry()`` returns a registry with every built-in claim type loaded.
RAF-1a is the only one in scope for this slice; new claim types register here.
"""
from klemr.claims.base import ClaimRegistry, ClaimType, IncompatibleRule
from klemr.claims.raf_1a import RafAutoCancelClaim, RafFeeSchedule
from klemr.claims.state import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATES,
    ClaimState,
    IllegalTransition,
    assert_transition,
    can_transition,
    is_terminal,
)


def default_registry() -> ClaimRegistry:
    registry = ClaimRegistry()
    registry.register(RafAutoCancelClaim())
    return registry


__all__ = [
    "ClaimType",
    "ClaimRegistry",
    "IncompatibleRule",
    "RafAutoCancelClaim",
    "RafFeeSchedule",
    "ClaimState",
    "ALLOWED_TRANSITIONS",
    "TERMINAL_STATES",
    "IllegalTransition",
    "assert_transition",
    "can_transition",
    "is_terminal",
    "default_registry",
]
