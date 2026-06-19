"""Step 3 acceptance: detection funnel, Findings, resolution states, determinism.

All counts are derived from the fixtures, never fitted. as_of = 2026-06-17 (the export
date) is what reproduces the reference's 24 mature / 1 fresh."""
from __future__ import annotations

import csv
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

pytest.importorskip("pandas", reason="reconciliation tests read fixtures via the 'ingest' extra")

from klemr.canonical.charges import Charge, ChargeType
from klemr.canonical.events import CancellationEvent, Party
from klemr.canonical.provenance import Provenance, SourceRef
from klemr.claims.raf_1a import RafAutoCancelClaim
from klemr.claims.state import ClaimState
from klemr.gates.confidence import ConfidenceLevel
from klemr.normalization.entity import OrderRecord
from klemr.normalization.pipeline import settlement_order_ids
from klemr.reconciliation import apply_resolutions, reconcile
from klemr.rules import default_rule_store

from tests.conftest import RESOLUTIONS

RULE_ID = "raf.auto_cancel_exemption"
AS_OF = date(2026, 6, 17)


@pytest.fixture(scope="module")
def claim():
    return RafAutoCancelClaim()


@pytest.fixture(scope="module")
def rule():
    return default_rule_store().latest(RULE_ID)


@pytest.fixture(scope="module")
def recon(canonical_dataset, tiktok_export, claim, rule):
    domain = {e.order_id for e in canonical_dataset.events}
    return reconcile(
        canonical_dataset, claim, rule,
        domain=domain, as_of=AS_OF,
        settlement_order_ids=settlement_order_ids(tiktok_export),
    )


@pytest.fixture(scope="module")
def resolutions():
    with open(RESOLUTIONS, newline="") as f:
        return {r["order_id"].strip(): r["resolution"].strip() for r in csv.DictReader(f)}


# ---- the funnel, exact ----
def test_funnel_exact(recon):
    assert recon.canceled_orders == 1448
    assert recon.in_scope == 1156
    assert recon.flagged == 30
    assert recon.ceiling_amount == Decimal("20.61")
    assert recon.mature == 24
    assert recon.fresh == 1
    assert len(recon.anomalies) == 0
    assert len(recon.out_of_scope_informational) == 206


def test_ceiling_is_a_row_sum_not_a_stored_literal(recon, canonical_dataset):
    # recompute independently from the canonical charge rows for the flagged orders
    flagged_orders = {f.credit_match_key.order_id for f in recon.findings}
    independent = Decimal("0.00")
    for oid in flagged_orders:
        for c in canonical_dataset.by_order[oid].charges:
            if c.charge_type is ChargeType.REFUND_ADMINISTRATION_FEE and c.is_deduction:
                independent += c.deduction_magnitude
    assert independent == Decimal("20.61")
    assert recon.ceiling_recomputed() == Decimal("20.61") == recon.ceiling_amount


def test_detection_leaves_findings_unverified(recon):
    # Gate 3 is not in the data -> nothing auto-resolved.
    assert all(f.state is ClaimState.NEEDS_VERIFICATION for f in recon.findings)
    for f in recon.findings:
        assert f.confidence.match is ConfidenceLevel.HIGH      # clean order_id join
        assert f.confidence.recovery is ConfidenceLevel.LOW    # Gate 3 unresolved


# ---- resolution -> states ----
def test_resolution_funnel_reconciles_to_30(recon, resolutions, rule):
    final = apply_resolutions(recon.findings, resolutions, rule)
    by_state = {}
    sums = {}
    for f in final:
        by_state[f.state.value] = by_state.get(f.state.value, 0) + 1
        sums[f.state.value] = sums.get(f.state.value, Decimal("0.00")) + f.ceiling_amount

    assert by_state.get("filable") == 23
    assert sums["filable"] == Decimal("15.72")
    assert by_state.get("dismissed") == 7
    assert sums["dismissed"] == Decimal("4.89")
    assert by_state.get("held", 0) == 0
    assert by_state.get("review", 0) == 0
    # every flagged row is accounted for: 23 + 7 + 0 = 30
    assert sum(by_state.values()) == 30

    filable = [f for f in final if f.state is ClaimState.FILABLE]
    dismissed = [f for f in final if f.state is ClaimState.DISMISSED]
    assert all(f.confidence.recovery is ConfidenceLevel.HIGH for f in filable)
    assert all(f.tier2_appeal_candidate for f in dismissed)  # NOT held; appeal flagged


def test_fresh_finding_is_filable_flagged_not_a_held_state(recon, resolutions, rule):
    final = apply_resolutions(recon.findings, resolutions, rule)
    fresh = [f for f in final if f.fresh]
    assert len(fresh) == 1
    assert fresh[0].state is ClaimState.FILABLE  # filable count stays 23
    assert fresh[0].mature is False
    assert fresh[0].hold_reason is None  # maturity is a flag, not a hold state


# ---- credit_match_key separation ----
def test_credit_match_key_excludes_rule_provenance(recon):
    f = recon.findings[0]
    k = f.credit_match_key
    assert set(k.model_dump().keys()) == {"order_id", "charge_class", "sku_id"}
    assert k.charge_class == "refund_administration_fee"
    # rule hash/version are provenance, NOT identity
    assert f.rule_content_hash and f.rule_version
    assert f.rule_content_hash not in k.canonical()
    assert f.rule_version not in k.canonical()


# ---- determinism ----
def test_two_runs_are_identical(canonical_dataset, tiktok_export, claim, rule):
    domain = {e.order_id for e in canonical_dataset.events}
    sett = settlement_order_ids(tiktok_export)
    a = reconcile(canonical_dataset, claim, rule, domain=domain, as_of=AS_OF, settlement_order_ids=sett)
    b = reconcile(canonical_dataset, claim, rule, domain=domain, as_of=AS_OF, settlement_order_ids=sett)
    assert a.run_fingerprint == b.run_fingerprint
    assert [f.finding_id for f in a.findings] == [f.finding_id for f in b.findings]
    assert [f.ceiling_amount for f in a.findings] == [f.ceiling_amount for f in b.findings]
    assert [f.state for f in a.findings] == [f.state for f in b.findings]


def test_period_alignment_diagnostic(recon):
    # cancellation orders absent from settlement (no settled RAF = nothing to recover)
    assert len(recon.not_in_settlement) == 92


# ---- Gate-2 participation (synthetic; the fixture can't prove this) ----
def _record(oid, tracking, cancelled):
    prov = Provenance(sources=(SourceRef(source_file="x.csv", content_sha256="0" * 64),))
    ev = CancellationEvent(order_id=oid, initiated_by=Party.BUYER,
                           tracking_uploaded_at=tracking, cancelled_at=cancelled, provenance=prov)
    raf = Charge(order_id=oid, charge_type=ChargeType.REFUND_ADMINISTRATION_FEE,
                 amount="-1.00", provenance=prov)
    return OrderRecord(order_id=oid, cancellation=ev, charges=(raf,))


def test_gate2_filters_a_buyer_shipped_order(claim, rule):
    # Both BUYER-initiated + carry a RAF. Only the pre-ship one should flag; the one
    # whose tracking precedes the cancel is shipped -> out of scope -> no finding.
    shipped = _record("SHIPPED", datetime(2026, 5, 1), datetime(2026, 5, 2))
    preship = _record("PRESHIP", None, datetime(2026, 5, 2))
    ds = SimpleNamespace(by_order={"SHIPPED": shipped, "PRESHIP": preship}, sources=())
    res = reconcile(ds, claim, rule, domain={"SHIPPED", "PRESHIP"}, as_of=date(2026, 6, 1))
    assert [f.credit_match_key.order_id for f in res.findings] == ["PRESHIP"]
    assert res.flagged == 1
    assert res.in_scope == 1  # the shipped buyer order is NOT in scope
