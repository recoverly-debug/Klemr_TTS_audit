"""Claim registry + scope-filter + logic-binding + state-machine tests."""
from __future__ import annotations

from datetime import datetime

import pytest

from klemr.canonical import CancellationEvent, Party, Provenance, SourceRef
from klemr.claims import (
    ClaimState,
    IncompatibleRule,
    can_transition,
    default_registry,
)
from klemr.claims.raf_1a import RafAutoCancelClaim
from klemr.rules import default_rule_store

PROV = Provenance(sources=(SourceRef(source_file="c.csv"),))


def _cancel(initiated_by=Party.BUYER, tracking_uploaded_at=None):
    return CancellationEvent(
        order_id="1",
        initiated_by=initiated_by,
        tracking_uploaded_at=tracking_uploaded_at,
        cancelled_at=datetime(2026, 5, 2),
        provenance=PROV,
    )


def test_raf_1a_registered_and_bound_to_rule():
    registry = default_registry()
    store = default_rule_store()

    claim = registry.get("raf-1a")
    assert claim.title.startswith("TikTok Shop RAF")
    assert claim.rule_id == "raf.auto_cancel_exemption"

    rule = claim.rule(store)
    assert rule.rule_id == claim.rule_id
    assert len(claim.gates(store)) == 3
    assert claim.resolution_policy(store).filable.tier == "filable_tier1"


def test_registry_lists_only_raf_1a_for_this_slice():
    keys = [c.key for c in default_registry().all()]
    assert keys == ["raf-1a"]


# ---- scope filter: Gates 1 & 2 live in the plugin, not the canonical event ----
def test_scope_filter_gate1_and_gate2():
    claim = RafAutoCancelClaim()

    buyer_preship = _cancel(initiated_by=Party.BUYER, tracking_uploaded_at=None)
    assert claim.gate1_buyer_initiated(buyer_preship) is True
    assert claim.gate2_pre_shipment(buyer_preship) is True
    assert claim.in_scope(buyer_preship) is True

    # seller-initiated fails Gate 1
    seller = _cancel(initiated_by=Party.SELLER, tracking_uploaded_at=None)
    assert claim.gate1_buyer_initiated(seller) is False
    assert claim.in_scope(seller) is False

    # shipped (tracking before cancel) fails Gate 2
    shipped = _cancel(
        initiated_by=Party.BUYER, tracking_uploaded_at=datetime(2026, 5, 1)
    )
    assert claim.gate2_pre_shipment(shipped) is False
    assert claim.in_scope(shipped) is False


# ---- FIX 3: explicit rule -> logic binding ----
def test_logic_id_binding_accepts_matching_rule():
    claim = RafAutoCancelClaim()
    rule = claim.rule(default_rule_store())  # asserts compatibility internally
    assert rule.logic_id == claim.logic_id == "raf.auto_cancel.v1"


def test_logic_id_binding_rejects_foreign_rule():
    claim = RafAutoCancelClaim()
    rule = default_rule_store().latest("raf.auto_cancel_exemption")
    foreign = rule.model_copy(update={"logic_id": "carrier.overcharge.v1"})
    with pytest.raises(IncompatibleRule):
        claim.assert_compatible(foreign)


# ---- state machine: a candidate is never directly filable ----
def test_candidate_must_be_verified_before_filable():
    assert can_transition(ClaimState.CANDIDATE, ClaimState.NEEDS_VERIFICATION) is True
    # the core invariant: no candidate -> filable shortcut (Gate 3 must intervene)
    assert can_transition(ClaimState.CANDIDATE, ClaimState.FILABLE) is False


def test_verification_outcomes():
    for dst in (ClaimState.FILABLE, ClaimState.HELD, ClaimState.REVIEW):
        assert can_transition(ClaimState.NEEDS_VERIFICATION, dst) is True


def test_filable_can_build_packet_and_is_terminal():
    assert can_transition(ClaimState.FILABLE, ClaimState.PACKET_BUILT) is True
    assert can_transition(ClaimState.PACKET_BUILT, ClaimState.FILABLE) is False
