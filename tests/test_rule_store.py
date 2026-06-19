"""Rule-store tests: RAF policy loads as data, gate-3 invariant, resolution split,
maturity boundary, deterministic content hash, version selection."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

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


# ---- policy values live as DATA, not constants ----
def test_raf_fee_schedule_values(store):
    rule = store.latest(RULE_ID)
    fs = rule.fee_schedule
    assert fs.referral_fee_rate == Decimal("0.20")
    assert fs.per_sku_cap == Decimal("5.00")  # the $5/SKU cap
    assert fs.cap_effective_date == date(2025, 5, 15)
    assert fs.cap_basis == "sku"
    assert fs.currency == "USD"


def test_rule_carries_logic_id(store):
    # FIX 3: the data declares which engine logic may evaluate it.
    assert store.latest(RULE_ID).logic_id == "raf.auto_cancel.v1"


def test_raf_cap_applies_per_sku_then_sums_at_cent_precision(store):
    fs = store.latest(RULE_ID).fee_schedule
    # one SKU under the cap: 20% of 12.34 = 2.468 -> 2.47 (HALF_UP, cents)
    assert fs.raf_for_sku(Decimal("12.34")) == Decimal("2.47")
    # one SKU over the cap: 20% of 50.00 = 10.00 -> capped at 5.00
    assert fs.raf_for_sku(Decimal("50.00")) == Decimal("5.00")
    # referral lines are stored negative; magnitude is used
    assert fs.raf_for_sku(Decimal("-50.00")) == Decimal("5.00")
    # cap PER SKU, THEN sum: 5.00 (capped) + 0.60 + 2.47 = 8.07
    order_total = fs.raf_for_order([Decimal("50.00"), Decimal("3.00"), Decimal("12.34")])
    assert order_total == Decimal("8.07")
    # NOT the same as capping the order as a whole at $5 — that would wrongly give 5.00
    assert order_total != fs.per_sku_cap


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
        ("approved", "filable_tier1"),
        ("seller_canceled", "held_tier2"),
        ("Seller Canceled", "held_tier2"),
        ("manual", "held_tier2"),
        ("", "needs_review"),
        ("other", "needs_review"),
        ("bought by mistake", "needs_review"),  # a buyer reason is never filable
    ],
)
def test_resolution_classification(store, raw, tier):
    policy = store.latest(RULE_ID).resolution_policy
    assert policy.classify(raw).tier == tier


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
