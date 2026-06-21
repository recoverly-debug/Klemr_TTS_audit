"""Rule-store tests: RAF policy loads as data, gate-3 invariant, resolution split,
maturity boundary, deterministic content hash, version selection."""
from __future__ import annotations

from datetime import date

import pytest

from klemr.rules import (
    RAF_AUTO_CANCEL_RULE_ID,
    DuplicateRuleVersion,
    RuleNotFound,
    RuleStore,
    default_rule_store,
)

RULE_ID = RAF_AUTO_CANCEL_RULE_ID


@pytest.fixture
def store() -> RuleStore:
    return default_rule_store()


# ---- generic envelope carries logic binding + claim-specific payload as data ----
def test_rule_carries_logic_id(store):
    # the data declares which engine logic may evaluate it (rule->logic binding).
    assert store.latest(RULE_ID).logic_id == "raf.auto_cancel.v1"


def test_payload_is_opaque_to_the_envelope(store):
    # claim-specific policy lives in `payload`; the envelope does not type it.
    # (RAF interprets payload["fee_schedule"] — covered in test_claims.py)
    rule = store.latest(RULE_ID)
    assert "fee_schedule" in rule.payload
    assert not hasattr(rule, "fee_schedule")  # no RAF-specific field on the envelope


def test_citation_is_verbatim(store):
    c = store.latest(RULE_ID).citation
    assert c.last_revised == date(2025, 5, 8)
    assert c.quote.startswith("If a refund is initiated by the buyer before the order is shipped")
    assert "no Refund Administration Fee will be charged" in c.quote


# ---- the decisive invariant: Gate 3 is not in the data ----
def test_three_gates_and_gate3_not_in_data(store):
    gates = store.latest(RULE_ID).gates
    assert len(gates) == 3
    by_num = {g.number: g for g in gates}

    assert by_num[1].in_data is True and by_num[1].decisive is False
    assert by_num[2].in_data is True and by_num[2].decisive is False

    g3 = by_num[3]
    assert g3.in_data is False
    assert g3.decisive is True
    assert g3.source == "seller_center"
    # the rule exposes exactly one decisive gate, and it is gate 3
    assert store.latest(RULE_ID).decisive_gate is g3


# ---- resolution -> tier mapping (the decision split as data); reason is noise ----
@pytest.mark.parametrize(
    "raw,tier",
    [
        ("auto_approved", "filable_tier1"),
        ("Auto-Approved", "filable_tier1"),
        ("approved", "needs_review"),  # ambiguous: "approved by whom?" -> never auto-filable
        ("auto", "needs_review"),      # ditto
        ("seller_canceled", "dismissed"),  # Gate 3 = NOT exempt -> terminal dismissed
        ("Seller Canceled", "dismissed"),
        ("manual", "dismissed"),
        ("", "needs_review"),
        ("other", "needs_review"),
        ("bought by mistake", "needs_review"),  # a buyer reason is never filable
    ],
)
def test_resolution_classification(store, raw, tier):
    policy = store.latest(RULE_ID).resolution_policy
    assert policy.classify(raw).tier == tier


def test_seller_canceled_carries_tier2_appeal_flag(store):
    # the Tier-2 appeal is metadata on the dismissed outcome, never a primary state.
    policy = store.latest(RULE_ID).resolution_policy
    out = policy.classify("seller_canceled")
    assert out is policy.dismissed
    assert "tier2_appeal_candidate" in out.flags


# ---- maturity / freshness boundary (pure policy math) ----
def test_maturity_boundary(store):
    params = store.latest(RULE_ID).parameters  # maturity_days=21, fresh_days=3
    as_of = date(2026, 6, 18)
    cutoff = date(2026, 5, 28)  # as_of - 21d
    assert params.mature_cutoff(as_of) == cutoff
    assert params.is_mature(cutoff, as_of) is True  # boundary is mature (<=)
    assert params.is_mature(date(2026, 5, 29), as_of) is False
    assert params.is_mature(None, as_of) is False


def test_freshness_boundary(store):
    params = store.latest(RULE_ID).parameters
    as_of = date(2026, 6, 18)
    fresh_cutoff = date(2026, 6, 15)  # as_of - 3d
    assert params.is_fresh(date(2026, 6, 16), as_of) is True
    assert params.is_fresh(fresh_cutoff, as_of) is False  # strictly greater
    assert params.is_fresh(None, as_of) is False


# ---- reproducibility: content hash is deterministic and stable across loads ----
def test_content_hash_deterministic(store):
    a = store.latest(RULE_ID).content_hash()
    b = default_rule_store().latest(RULE_ID).content_hash()
    assert a == b
    assert len(a) == 64  # sha256 hex


# ---- store mechanics ----
def test_get_versions_and_effective_on(store):
    rule = store.latest(RULE_ID)
    assert store.get(RULE_ID, "2025-05-15") is rule
    assert store.effective_on(RULE_ID, date(2026, 1, 1)) is rule
    with pytest.raises(RuleNotFound):
        store.effective_on(RULE_ID, date(2025, 1, 1))  # before any version
    with pytest.raises(RuleNotFound):
        store.get(RULE_ID, "9999-99-99")


def test_duplicate_version_with_different_content_rejected(store):
    rule = store.latest(RULE_ID)
    mutated = rule.model_copy(update={"description": "tampered"})
    with pytest.raises(DuplicateRuleVersion):
        store.register(mutated)


def test_reregistering_identical_version_is_ok(store):
    rule = store.latest(RULE_ID)
    store.register(rule)  # idempotent: same (id, version), same content hash
    assert store.latest(RULE_ID) is rule
