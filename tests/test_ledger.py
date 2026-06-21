"""Evidence-ledger + verify-flow unit tests (synthetic findings, no fixture I/O)."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from decimal import Decimal

import pytest

from klemr.canonical.provenance import Provenance, SourceRef
from klemr.claims.state import ClaimState, IllegalTransition
from klemr.gates.confidence import Confidence, ConfidenceLevel
from klemr.ledger import EvidenceLedger, replay, verify_finding
from klemr.reconciliation.finding import CreditMatchKey, Finding, make_finding_id
from klemr.rules import default_rule_store

RULE = default_rule_store().latest("raf.auto_cancel_exemption")
PROV = Provenance(sources=(SourceRef(source_file="c.csv", content_sha256="0" * 64),))
AT = datetime(2026, 6, 17, 12, 0, 0)


def _finding(order_id="O1", state=ClaimState.NEEDS_VERIFICATION, ceiling="1.00") -> Finding:
    return Finding(
        finding_id=make_finding_id("raf-1a", order_id, RULE.content_hash()),
        claim_key="raf-1a",
        rule_id=RULE.rule_id,
        rule_version=RULE.version,
        rule_content_hash=RULE.content_hash(),
        provenance=PROV,
        ceiling_amount=Decimal(ceiling),
        credit_match_key=CreditMatchKey(order_id=order_id, charge_class="refund_administration_fee"),
        confidence=Confidence.for_unverified_candidate(),
        state=state,
        mature=True,
        fresh=False,
    )


@pytest.fixture
def ledger():
    lg = EvidenceLedger(":memory:")
    yield lg
    lg.close()


# ---- append-only ----
def test_ledger_is_append_only(ledger):
    verify_finding(ledger, _finding(), "auto_approved", rule=RULE, reviewer="qa", resolved_at=AT)
    assert ledger.count("resolutions") == 1
    with pytest.raises(sqlite3.Error):
        ledger.connection.execute("UPDATE resolutions SET reviewer='tamper'")
    with pytest.raises(sqlite3.Error):
        ledger.connection.execute("DELETE FROM resolutions")
    with pytest.raises(sqlite3.Error):
        ledger.connection.execute("UPDATE transitions SET to_state='closed'")


# ---- the two decisive outcomes ----
def test_auto_approved_filable_recovery_high_linked_transition(ledger):
    f = _finding("O1")
    r = verify_finding(ledger, f, "auto_approved", rule=RULE, reviewer="qa",
                       resolved_at=AT, evidence_ref="O1.png")
    assert r.finding.state is ClaimState.FILABLE
    assert r.finding.confidence.recovery is ConfidenceLevel.HIGH
    assert r.resolution_id and r.transition_id
    # the transition is linked to the resolution that caused it
    tr = ledger.transitions_for(f.finding_id)
    assert len(tr) == 1
    assert tr[0].resolution_id == r.resolution_id
    assert tr[0].from_state == "needs_verification" and tr[0].to_state == "filable"
    res = ledger.latest_resolution(f.finding_id)
    assert res.gate == "gate3_auto_approved" and res.source == "seller_center"
    assert res.rule_content_hash == RULE.content_hash()


def test_seller_canceled_dismissed_tier2_recovery_low(ledger):
    r = verify_finding(ledger, _finding("O2"), "seller_canceled", rule=RULE,
                       reviewer="qa", resolved_at=AT)
    assert r.finding.state is ClaimState.DISMISSED
    assert r.finding.tier2_appeal_candidate is True
    assert r.finding.confidence.recovery is ConfidenceLevel.LOW


# ---- never auto-resolve ----
def test_unresolved_finding_stays_needs_verification(ledger):
    f = _finding("O3")
    # no resolution recorded -> replay leaves it untouched
    (only,) = replay(ledger, [f], RULE)
    assert only.state is ClaimState.NEEDS_VERIFICATION
    assert only.confidence.recovery is ConfidenceLevel.LOW


def test_non_decisive_resolution_records_fact_but_no_transition(ledger):
    f = _finding("O4")
    r = verify_finding(ledger, f, "no longer needed", rule=RULE, reviewer="qa", resolved_at=AT)
    assert r.finding.state is ClaimState.NEEDS_VERIFICATION  # never auto-resolved
    assert r.transition_id is None
    assert ledger.count("resolutions") == 1 and ledger.count("transitions") == 0


# ---- illegal transition raises, writes nothing ----
def test_illegal_transition_raises_and_writes_nothing(ledger):
    candidate = _finding("O5", state=ClaimState.CANDIDATE)  # candidate -> filable is illegal
    with pytest.raises(IllegalTransition):
        verify_finding(ledger, candidate, "auto_approved", rule=RULE, reviewer="qa", resolved_at=AT)
    assert ledger.count("resolutions") == 0 and ledger.count("transitions") == 0


# ---- idempotency + append-only correction ----
def test_reapplying_same_resolution_is_a_noop(ledger):
    f = _finding("O6")
    first = verify_finding(ledger, f, "auto_approved", rule=RULE, reviewer="qa", resolved_at=AT)
    again = verify_finding(ledger, first.finding, "auto_approved", rule=RULE, reviewer="qa", resolved_at=AT)
    assert again.no_op is True
    assert ledger.count("resolutions") == 1 and ledger.count("transitions") == 1


def test_correction_is_a_new_row_and_latest_wins(ledger):
    f = _finding("O7")
    # a non-decisive first pass (legal: stays needs_verification), then a decisive correction
    verify_finding(ledger, f, "unclear", rule=RULE, reviewer="qa", resolved_at=AT)
    second = verify_finding(ledger, f, "auto_approved", rule=RULE, reviewer="qa", resolved_at=AT)
    assert second.finding.state is ClaimState.FILABLE
    assert len(ledger.resolutions_for(f.finding_id)) == 2  # append-only correction
    assert ledger.latest_resolution(f.finding_id).resolved_value == "auto_approved"
