"""Tier-1 evidence packet tests. Requires the `packet` extra (reportlab + pillow)."""
from __future__ import annotations

import csv
from datetime import date, datetime
from decimal import Decimal

import pytest

pytest.importorskip("reportlab", reason="evidence tests require the 'packet' extra (reportlab+pillow)")

from klemr.canonical.charges import ChargeType
from klemr.canonical.provenance import Provenance, SourceRef
from klemr.claims.raf_1a import RafAutoCancelClaim
from klemr.claims.state import ClaimState
from klemr.evidence import build_packet
from klemr.gates.confidence import Confidence
from klemr.ledger import EvidenceLedger, replay, verify_finding
from klemr.normalization.pipeline import settlement_order_ids
from klemr.reconciliation import reconcile
from klemr.reconciliation.finding import CreditMatchKey, Finding, make_finding_id
from klemr.rules import default_rule_store

from tests.conftest import RESOLUTIONS

RULE = default_rule_store().latest("raf.auto_cancel_exemption")
PROV = Provenance(sources=(SourceRef(source_file="c.csv", content_sha256="0" * 64),))
AT = datetime(2026, 6, 17, 12, 0, 0)


def _finding(order_id, ceiling, content_hash=None) -> Finding:
    h = content_hash or RULE.content_hash()
    return Finding(
        finding_id=make_finding_id("raf-1a", order_id, h),
        claim_key="raf-1a", rule_id=RULE.rule_id, rule_version=RULE.version,
        rule_content_hash=h, provenance=PROV, ceiling_amount=Decimal(ceiling),
        credit_match_key=CreditMatchKey(order_id=order_id, charge_class="refund_administration_fee"),
        confidence=Confidence.for_unverified_candidate(), state=ClaimState.NEEDS_VERIFICATION,
        mature=True, fresh=False,
    )


def _verify(ledger, finding, value, evidence_ref):
    return verify_finding(ledger, finding, value, rule=RULE, reviewer="qa",
                          resolved_at=AT, evidence_ref=evidence_ref).finding


# ---- synthetic: totals are row-sums, citation resolves, hash matches ----
def test_cover_totals_are_row_sums_and_citation_resolves(tmp_path):
    ledger = EvidenceLedger(":memory:")
    f1 = _verify(ledger, _finding("A", "1.11"), "auto_approved", None)
    f2 = _verify(ledger, _finding("B", "2.22"), "auto_approved", None)
    f3 = _verify(ledger, _finding("C", "3.33"), "seller_canceled", None)
    r = build_packet([f1, f2, f3], rule_store=default_rule_store(), ledger=ledger,
                     run_date=date(2026, 6, 17), run_fingerprint="fp",
                     out_path=tmp_path / "p.pdf")
    # derived from the shown findings, not literals
    assert r.tier1_count == 2 and r.tier1_total == Decimal("3.33")  # 1.11 + 2.22
    assert r.tier2_count == 1 and r.tier2_total == Decimal("3.33")
    assert r.evidence_pages == 2
    # citation/tamper check resolved via rule_id+version and matches the findings' hash
    assert r.hash_matches is True
    assert r.rule_content_hash == RULE.content_hash()


def test_tampered_hash_is_flagged(tmp_path):
    ledger = EvidenceLedger(":memory:")
    f = _verify(ledger, _finding("X", "1.00", content_hash="deadbeef" * 8), "auto_approved", "x.png")
    r = build_packet([f], rule_store=default_rule_store(), ledger=ledger,
                     run_date=date(2026, 6, 17), run_fingerprint="fp", out_path=tmp_path / "p.pdf")
    assert r.hash_matches is False  # citation still resolves, but integrity line warns


def test_missing_evidence_ref_renders_pending_not_faked(tmp_path):
    ledger = EvidenceLedger(":memory:")
    f = _verify(ledger, _finding("NOPIC", "1.00"), "auto_approved", evidence_ref=None)
    r = build_packet([f], rule_store=default_rule_store(), ledger=ledger,
                     run_date=date(2026, 6, 17), run_fingerprint="fp",
                     out_path=tmp_path / "p.pdf", screenshots_dir="fixtures/screenshots")
    assert r.pending_orders == ["NOPIC"]
    assert r.real_screenshots == 0  # never a fabricated image


def test_determinism_same_inputs_identical_bytes(tmp_path):
    ledger = EvidenceLedger(":memory:")
    f = _verify(ledger, _finding("A", "1.00"), "auto_approved", "576478578200712737.png")
    kw = dict(rule_store=default_rule_store(), ledger=ledger, run_date=date(2026, 6, 17),
              run_fingerprint="fp", screenshots_dir="fixtures/screenshots")
    build_packet([f], out_path=tmp_path / "a.pdf", **kw)
    build_packet([f], out_path=tmp_path / "b.pdf", **kw)
    assert (tmp_path / "a.pdf").read_bytes() == (tmp_path / "b.pdf").read_bytes()


# ---- full fixture funnel: 23 filable / $15.72, 7 dismissed / $4.89 ----
@pytest.fixture(scope="module")
def verified(canonical_dataset, tiktok_export):
    claim = RafAutoCancelClaim()
    rule = default_rule_store().latest("raf.auto_cancel_exemption")
    domain = {e.order_id for e in canonical_dataset.events}
    recon = reconcile(canonical_dataset, claim, rule, domain=domain, as_of=date(2026, 6, 17),
                      settlement_order_ids=settlement_order_ids(tiktok_export))
    with open(RESOLUTIONS, newline="") as fh:
        res = {r["order_id"].strip(): r["resolution"].strip() for r in csv.DictReader(fh)}
    ledger = EvidenceLedger(":memory:")
    for f in recon.findings:
        verify_finding(ledger, f, res[f.credit_match_key.order_id], rule=rule, reviewer="haus-qa",
                       resolved_at=AT, evidence_ref=f"{f.credit_match_key.order_id}.png")
    final = replay(ledger, recon.findings, rule)
    lines = {}
    for f in final:
        if f.state is ClaimState.FILABLE:
            oid = f.credit_match_key.order_id
            lines[oid] = [c for c in canonical_dataset.by_order[oid].charges
                          if c.charge_type is ChargeType.REFUND_ADMINISTRATION_FEE and c.is_deduction]
    return final, ledger, recon, lines


def test_full_packet_23_pages_and_row_sum_totals(verified, tmp_path):
    final, ledger, recon, lines = verified
    r = build_packet(final, rule_store=default_rule_store(), ledger=ledger,
                     run_date=date(2026, 6, 17), run_fingerprint=recon.run_fingerprint,
                     out_path=tmp_path / "packet.pdf", screenshots_dir="fixtures/screenshots",
                     charge_lines=lines,
                     funnel={"canceled": recon.canceled_orders, "in_scope": recon.in_scope,
                             "flagged": recon.flagged})
    assert r.evidence_pages == 23
    assert r.total_pages == 27  # cover + policy + gate + 23 evidence + tier-2
    assert r.tier1_total == Decimal("15.72")  # row-sum of the 23 filable
    assert r.tier2_count == 7 and r.tier2_total == Decimal("4.89")
    assert r.hash_matches is True
    assert r.real_screenshots == 23 and r.pending_orders == []
