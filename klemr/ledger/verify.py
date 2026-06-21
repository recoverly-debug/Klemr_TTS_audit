"""The Gate-3 human/agent verification flow, written through the evidence ledger.

This is the decisive gate: it records a resolution (append-only) and, when that
resolution changes the finding's state, writes a linked transition — going through
``rule.resolution_policy.classify`` (the only resolution->tier path) and
``assert_transition`` (illegal transitions raise, never silently no-op). It never
auto-resolves: a non-decisive value records the human action but leaves the finding
in ``needs_verification``.

Lives in ledger/ (the system of record) and imports the Finding it verifies;
reconciliation never imports ledger, so there is no cycle.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from klemr.claims.state import assert_transition
from klemr.reconciliation.engine import resolve_finding
from klemr.reconciliation.finding import Finding
from klemr.ledger.storage import EvidenceLedger
from klemr.rules.models import Rule


@dataclass(frozen=True)
class VerifyResult:
    finding: Finding  # the (possibly) updated finding
    resolution_id: int | None
    transition_id: int | None
    no_op: bool = False


def _gate_id(rule: Rule) -> str:
    g = rule.decisive_gate
    return f"gate{g.number}_{g.key}"  # e.g. "gate3_auto_approved"


def verify_finding(
    ledger: EvidenceLedger,
    finding: Finding,
    resolved_value: str,
    *,
    rule: Rule,
    reviewer: str,
    resolved_at: datetime,
    source: str = "seller_center",
    evidence_ref: str | None = None,
    actor: str | None = None,
    reason: str | None = None,
) -> VerifyResult:
    """Record a verified Gate-3 resolution and apply the resulting state transition.

    Idempotent only over the FULL evidentiary act — value + evidence_ref + source. A
    true duplicate (same value, same evidence, same source) is a no-op; the SAME
    decision with NEW evidence (e.g. a screenshot attached later) appends a new row so
    evidence can be augmented (it just doesn't re-transition, since the state is
    unchanged). A different value is an append-only correction (latest wins). An illegal
    resulting transition raises before anything is written.
    """
    if not str(resolved_value).strip():
        raise ValueError("resolved_value is required (verification is a recorded action)")

    latest = ledger.latest_resolution(finding.finding_id)
    is_exact_duplicate = (
        latest is not None
        and latest.resolved_value == resolved_value
        and latest.evidence_ref == evidence_ref
        and latest.source == source
    )
    if is_exact_duplicate:
        return VerifyResult(finding, None, None, no_op=True)  # nothing new to record

    updated = resolve_finding(finding, resolved_value, rule)
    changed = updated.state != finding.state
    if changed:
        assert_transition(finding.state, updated.state)  # raises before any DB write

    resolution_id = ledger.record_resolution(
        finding_id=finding.finding_id,
        gate=_gate_id(rule),
        resolved_value=resolved_value,
        source=source,
        reviewer=reviewer,
        resolved_at=resolved_at,
        rule_id=finding.rule_id,
        rule_content_hash=finding.rule_content_hash,
        evidence_ref=evidence_ref,
    )
    transition_id = None
    if changed:
        transition_id = ledger.record_transition(
            finding_id=finding.finding_id,
            from_state=finding.state.value,
            to_state=updated.state.value,
            actor=actor or reviewer,
            at=resolved_at,
            resolution_id=resolution_id,
            reason=reason or f"gate3:{resolved_value}",
        )
    return VerifyResult(updated, resolution_id, transition_id)


def replay(ledger: EvidenceLedger, findings, rule: Rule) -> list[Finding]:
    """Reconstruct final finding states from detection + the ledger's latest resolutions.

    Deterministic: detection is recomputable and ``latest_resolution`` is stable, so
    detection-rerun + ledger-replay always yields identical states/amounts.

    Semantics — **append order wins**, not wall-clock ``resolved_at``: a correction is a
    new row, and the most recently *recorded* resolution (highest ``resolution_id``)
    supersedes earlier ones. This is intentional (an analyst recording a correction now
    overrides what was recorded before, regardless of the event time they enter). A
    backfilled resolution carrying an older ``resolved_at`` will still win if it was
    appended later — by design.
    """
    out: list[Finding] = []
    for finding in findings:
        latest = ledger.latest_resolution(finding.finding_id)
        if latest is None:
            out.append(finding)  # unresolved -> stays needs_verification
        else:
            out.append(resolve_finding(finding, latest.resolved_value, rule))
    return out
