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
from klemr.gates.confidence import Confidence, ConfidenceLevel
from klemr.ledger import EvidenceLedger, replay, verify_finding
from klemr.normalization.pipeline import settlement_order_ids
from klemr.reconciliation import reconcile
from klemr.reconciliation.finding import CreditMatchKey, Finding, make_finding_id
from klemr.rules import default_rule_store

from tests.conftest import RESOLUTIONS

RULE = default_rule_store().latest("raf.auto_cancel_exemption")
PROV = Provenance(sources=(SourceRef(source_file="c.csv", content_sha256="0" * 64),))
AT = datetime(2026, 6, 17, 12, 0, 0)


def _finding(order_id, ceiling, content_hash=None, mature=True, fresh=False) -> Finding:
    h = content_hash or RULE.content_hash()
    return Finding(
        finding_id=make_finding_id("raf-1a", order_id, h),
        claim_key="raf-1a", rule_id=RULE.rule_id, rule_version=RULE.version,
        rule_content_hash=h, provenance=PROV, ceiling_amount=Decimal(ceiling),
        credit_match_key=CreditMatchKey(order_id=order_id, charge_class="refund_administration_fee"),
        confidence=Confidence.for_unverified_candidate(), state=ClaimState.NEEDS_VERIFICATION,
        mature=mature, fresh=fresh,
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
    # A filable finding whose recorded rule hash no longer matches the store's rule (e.g.
    # the rule data changed AFTER this finding was filed). It cannot be (re)resolved — the
    # provenance guard blocks that — but a previously-filed one still reaches the packet,
    # whose integrity line must warn. Construct it directly in the filable state.
    f = _finding("X", "1.00", content_hash="deadbeef" * 8).model_copy(update={
        "state": ClaimState.FILABLE,
        "confidence": Confidence.for_unverified_candidate().model_copy(
            update={"recovery": ConfidenceLevel.HIGH}),
    })
    r = build_packet([f], rule_store=default_rule_store(), ledger=EvidenceLedger(":memory:"),
                     run_date=date(2026, 6, 17), run_fingerprint="fp", out_path=tmp_path / "p.pdf",
                     validate_against_ledger=False)  # isolate the display-layer hash check
    assert r.hash_matches is False  # citation still resolves, but integrity line warns


def test_projection_finding_without_ledger_resolution_is_rejected(tmp_path):
    # a filable-looking finding with NO recorded ledger resolution (an in-memory
    # projection) must never become a packet — "never filable on a guess".
    f = _finding("P", "1.00").model_copy(update={"state": ClaimState.FILABLE})
    with pytest.raises(ValueError):
        build_packet([f], rule_store=default_rule_store(), ledger=EvidenceLedger(":memory:"),
                     run_date=date(2026, 6, 17), run_fingerprint="fp", out_path=tmp_path / "p.pdf")


def test_require_evidence_fails_hard_on_missing_screenshot(tmp_path):
    ledger = EvidenceLedger(":memory:")
    f = _verify(ledger, _finding("NOPIC", "1.00"), "auto_approved", evidence_ref=None)
    # draft mode (default) still renders with a placeholder; finalize mode refuses
    build_packet([f], rule_store=default_rule_store(), ledger=ledger, run_date=date(2026, 6, 17),
                 run_fingerprint="fp", out_path=tmp_path / "draft.pdf")  # ok
    with pytest.raises(ValueError):
        build_packet([f], rule_store=default_rule_store(), ledger=ledger, run_date=date(2026, 6, 17),
                     run_fingerprint="fp", out_path=tmp_path / "final.pdf", require_evidence=True)


def test_missing_evidence_ref_renders_pending_not_faked(tmp_path):
    ledger = EvidenceLedger(":memory:")
    f = _verify(ledger, _finding("NOPIC", "1.00"), "auto_approved", evidence_ref=None)
    r = build_packet([f], rule_store=default_rule_store(), ledger=ledger,
                     run_date=date(2026, 6, 17), run_fingerprint="fp",
                     out_path=tmp_path / "p.pdf", screenshots_dir="fixtures/screenshots")
    assert r.pending_orders == ["NOPIC"]
    assert r.real_screenshots == 0  # never a fabricated image


def test_ripe_now_split_is_row_sums_summing_to_total(tmp_path):
    ledger = EvidenceLedger(":memory:")
    fm = _verify(ledger, _finding("M", "4.00", mature=True), "auto_approved", None)
    fi = _verify(ledger, _finding("I", "1.00", mature=False, fresh=True), "auto_approved", None)
    r = build_packet([fm, fi], rule_store=default_rule_store(), ledger=ledger,
                     run_date=date(2026, 6, 17), run_fingerprint="fp", out_path=tmp_path / "p.pdf")
    assert r.tier1_mature_total == Decimal("4.00") and r.tier1_mature_count == 1
    assert r.tier1_maturing_total == Decimal("1.00") and r.tier1_maturing_count == 1
    # maturity is a split of the SAME total, not a new number
    assert r.tier1_mature_total + r.tier1_maturing_total == r.tier1_total == Decimal("5.00")


def test_full_window_screenshot_is_cropped_but_clean_capture_is_not(tmp_path):
    from PIL import Image as _Img
    wide = tmp_path / "wide.png"; _Img.new("RGB", (1600, 900), "white").save(wide)   # full window (1.78)
    tall = tmp_path / "tall.png"; _Img.new("RGB", (800, 1000), "white").save(tall)   # clean capture (0.8)
    ledger = EvidenceLedger(":memory:")
    f1 = _verify(ledger, _finding("WIDE", "1.00"), "auto_approved", str(wide))
    f2 = _verify(ledger, _finding("TALL", "1.00"), "auto_approved", str(tall))
    r = build_packet([f1, f2], rule_store=default_rule_store(), ledger=ledger,
                     run_date=date(2026, 6, 17), run_fingerprint="fp", out_path=tmp_path / "p.pdf")
    assert r.cropped_screenshots == 1  # only the full-window capture; clean capture left intact
    assert r.real_screenshots == 2 and r.pending_orders == []


def test_build_packet_rejects_empty_inputs(tmp_path):
    with pytest.raises(ValueError):
        build_packet([], rule_store=default_rule_store(), ledger=EvidenceLedger(":memory:"),
                     run_date=date(2026, 6, 17), run_fingerprint="fp", out_path=tmp_path / "p.pdf")


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
    # ripe-now split (row-sums of the maturity flag) sums back to the unchanged total
    assert r.tier1_mature_count == 17 and r.tier1_mature_total == Decimal("11.84")
    assert r.tier1_maturing_count == 6 and r.tier1_maturing_total == Decimal("3.88")
    assert r.tier1_mature_total + r.tier1_maturing_total == Decimal("15.72")
    assert r.cropped_screenshots == 23  # all fixture exhibits are full-window captures
