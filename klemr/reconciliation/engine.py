"""The deterministic reconciliation engine ("the accountant").

Composes a claim plugin's predicates over the canonical dataset to produce
provenance-linked Findings + the detection funnel. Deterministic and idempotent:
same inputs (same source content hashes + same rule hash) -> identical findings and
run fingerprint. Math decides — every amount is recomputed from charge rows.

The decisive Gate-3 signal is NOT in the data, so detection leaves findings in
``needs_verification`` (recovery LOW); it never auto-resolves. ``apply_resolutions``
is the separate, human/API-driven step that transitions findings via the rule
store's ``classify`` (the only resolution -> outcome path).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from klemr.canonical.charges import Charge, ChargeType
from klemr.canonical.provenance import Provenance, SourceRef
from klemr.claims.raf_1a import RafAutoCancelClaim
from klemr.claims.state import ClaimState
from klemr.gates.confidence import Confidence, ConfidenceLevel
from klemr.reconciliation.finding import (
    CreditMatchKey,
    Finding,
    make_finding_id,
)
from klemr.rules.models import Rule


@dataclass(frozen=True)
class Anomaly:
    order_id: str
    code: str
    detail: str


@dataclass(frozen=True)
class OutOfScopeRow:
    order_id: str
    reason: str
    raf_charged: Decimal


@dataclass(frozen=True)
class ReconciliationResult:
    findings: tuple[Finding, ...]
    as_of: date
    run_fingerprint: str
    # funnel
    canceled_orders: int
    in_scope: int
    flagged: int
    ceiling_amount: Decimal
    mature: int
    fresh: int
    anomalies: tuple[Anomaly, ...] = ()
    out_of_scope_informational: tuple[OutOfScopeRow, ...] = ()
    # period-alignment diagnostic: domain orders with no settlement presence
    not_in_settlement: tuple[str, ...] = ()

    def ceiling_recomputed(self) -> Decimal:
        """Row-sum of per-finding ceilings — proves the total is never a stored literal."""
        return sum((f.ceiling_amount for f in self.findings), Decimal("0.00"))


def _merge_provenance(sources_lists) -> tuple[SourceRef, ...]:
    seen: dict[tuple, SourceRef] = {}
    for sources in sources_lists:
        for ref in sources:
            seen[(ref.source_file, ref.sheet, ref.row_indices, ref.content_sha256)] = ref
    return tuple(seen.values())


def run_fingerprint(source_hashes, rule_hashes) -> str:
    """Deterministic fingerprint of the inputs: source content hashes + rule hashes."""
    parts = sorted(source_hashes) + sorted(rule_hashes)
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def reconcile(
    dataset,
    claim: RafAutoCancelClaim,
    rule: Rule,
    *,
    domain: set[str],
    as_of: date,
    settlement_order_ids: set[str] | None = None,
) -> ReconciliationResult:
    """Detect flagged findings for ``claim`` over ``domain`` (passed in, never hardcoded)."""
    rule_hash = rule.content_hash()
    params = rule.parameters
    charge_type: ChargeType = claim.recoverable_charge_type

    findings: list[Finding] = []
    anomalies: list[Anomaly] = []
    out_of_scope: list[OutOfScopeRow] = []
    ceiling_total = Decimal("0.00")
    n_in_scope = n_mature = n_fresh = 0

    for oid in domain:
        record = dataset.by_order.get(oid)
        event = record.cancellation if record else None
        if event is None:
            continue
        charges = record.charges if record else ()
        raf_lines = [
            c for c in charges if c.charge_type is charge_type and c.is_deduction
        ]
        raf_total = sum((c.deduction_magnitude for c in raf_lines), Decimal("0.00"))

        if not claim.in_scope(event):
            # out-of-scope cancellation that still carried RAF -> informational, NOT a finding
            if raf_total > 0:
                out_of_scope.append(
                    OutOfScopeRow(oid, _out_of_scope_reason(event, claim), raf_total)
                )
            continue

        n_in_scope += 1
        if raf_total <= 0:
            continue  # in scope but no RAF charged -> nothing to recover (not flagged)

        statement_date = max(
            (c.statement_date for c in raf_lines if c.statement_date), default=None
        )
        mature = params.is_mature(statement_date, as_of)
        fresh = params.is_fresh(statement_date, as_of)
        n_mature += int(mature)
        n_fresh += int(fresh)

        codes = _anomaly_codes(oid, raf_lines, charges, claim, rule, anomalies)

        provenance = Provenance(
            sources=_merge_provenance(
                [event.provenance.sources, *[c.provenance.sources for c in raf_lines]]
            ),
            ingested_at=event.provenance.ingested_at,
        )
        sku_ids = {c.sku_id for c in raf_lines if c.sku_id}
        finding = Finding(
            finding_id=make_finding_id(claim.key, oid, rule_hash),
            claim_key=claim.key,
            rule_id=rule.rule_id,
            rule_version=rule.version,
            rule_content_hash=rule_hash,
            provenance=provenance,
            ceiling_amount=raf_total,
            credit_match_key=CreditMatchKey(
                order_id=oid,
                charge_class=charge_type.value,
                sku_id=next(iter(sku_ids)) if len(sku_ids) == 1 else None,
            ),
            confidence=Confidence.for_unverified_candidate(),
            state=ClaimState.NEEDS_VERIFICATION,  # Gate 3 not in data -> verify, never auto-resolve
            mature=mature,
            fresh=fresh,
            anomalies=tuple(codes),
        )
        findings.append(finding)
        ceiling_total += raf_total

    not_in_settlement: tuple[str, ...] = ()
    if settlement_order_ids is not None:
        not_in_settlement = tuple(sorted(o for o in domain if o not in settlement_order_ids))

    source_hashes = [
        s.content_sha256 for s in dataset.sources if s.content_sha256
    ]
    findings.sort(key=lambda f: f.credit_match_key.order_id)
    return ReconciliationResult(
        findings=tuple(findings),
        as_of=as_of,
        run_fingerprint=run_fingerprint(source_hashes, [rule_hash]),
        canceled_orders=len(domain),
        in_scope=n_in_scope,
        flagged=len(findings),
        ceiling_amount=ceiling_total,
        mature=n_mature,
        fresh=n_fresh,
        anomalies=tuple(anomalies),
        out_of_scope_informational=tuple(out_of_scope),
        not_in_settlement=not_in_settlement,
    )


def _out_of_scope_reason(event, claim: RafAutoCancelClaim) -> str:
    why = []
    if not claim.gate1_buyer_initiated(event):
        why.append(f"initiated_by={event.initiated_by.value}")
    if not claim.gate2_pre_shipment(event):
        why.append("shipped before cancel")
    return "; ".join(why)


def _anomaly_codes(oid, raf_lines, charges, claim, rule, sink: list[Anomaly]) -> list[str]:
    codes: list[str] = []
    fee_schedule = claim.fee_schedule(rule)
    cap = fee_schedule.per_sku_cap
    # 1) a single RAF line above the per-SKU cap
    for line in raf_lines:
        if line.deduction_magnitude > cap:
            codes.append("RAF_LINE_EXCEEDS_CAP")
            sink.append(Anomaly(oid, "RAF_LINE_EXCEEDS_CAP",
                                f"RAF line ${line.deduction_magnitude} exceeds ${cap}/SKU cap"))
            break
    # 2) order RAF above ~20% of referral (only meaningful when referral is present)
    referral = sum(
        (c.deduction_magnitude if c.is_deduction else abs(c.amount)
         for c in charges if c.charge_type is ChargeType.REFERRAL_FEE),
        Decimal("0.00"),
    )
    if referral > 0:
        raf_total = sum((l.deduction_magnitude for l in raf_lines), Decimal("0.00"))
        expected = min(referral * fee_schedule.referral_fee_rate, cap * max(len(raf_lines), 1))
        if raf_total > expected + Decimal("0.05"):
            codes.append("RAF_ABOVE_20PCT_REFERRAL")
            sink.append(Anomaly(oid, "RAF_ABOVE_20PCT_REFERRAL",
                                f"RAF ${raf_total} exceeds ~20% of referral (${expected})"))
    return codes


# ----------------------------- Gate-3 resolution (human/API) -----------------------------

_RECOVERY_HIGH = {"recovery": ConfidenceLevel.HIGH}


def resolve_finding(finding: Finding, raw: object, rule: Rule) -> Finding:
    """Pure: map a verified Gate-3 resolution to the updated finding.

    Classification goes THROUGH the rule's resolution_policy (the only resolution ->
    outcome path). A non-decisive value (empty / "other" / a buyer reason) is NEVER
    auto-resolved — the finding stays in ``needs_verification`` (recovery LOW). This is
    the single source of the classify->state mapping, shared by the in-memory
    ``apply_resolutions`` and the ledger verify flow.
    """
    if raw is None or not str(raw).strip():
        return finding
    policy = rule.resolution_policy
    outcome = policy.classify(raw)
    if outcome is policy.filable:
        return finding.model_copy(update={
            "state": ClaimState.FILABLE,
            "confidence": finding.confidence.model_copy(update=_RECOVERY_HIGH),
        })
    if outcome is policy.dismissed:
        return finding.model_copy(update={
            "state": ClaimState.DISMISSED,
            "tier2_appeal_candidate": "tier2_appeal_candidate" in outcome.flags,
        })
    return finding  # non-decisive -> stays needs_verification, never auto-resolved


def apply_resolutions(
    findings, resolutions: dict[str, str], rule: Rule
) -> list[Finding]:
    """In-memory convenience: resolve each finding by its order_id resolution."""
    return [
        resolve_finding(f, resolutions.get(f.credit_match_key.order_id), rule)
        for f in findings
    ]
