"""The Finding — a deterministic, provenance-linked detection result.

Claim-agnostic. Lives in the reconciliation lane (not canonical/) on purpose: a
Finding *composes* lower lanes — ClaimState (claims), Confidence (gates), Provenance
(canonical), Decimal money — so hosting it in canonical/ would invert canonical's
leaf position and create an import cycle (canonical -> claims -> rules -> canonical).
reconciliation/ sits above all of them.

Key separations the model enforces:
- ``credit_match_key`` holds ONLY fields observable on both this claim and a future
  incoming credit line (order_id [+ sku_id if line-level] + charge_class). The rule
  version/hash are NOT in the key — they are separate provenance. Amount/date are
  fuzzy-confirm signals, not key components.
- ``ceiling_amount`` is recomputed from the contributing charge rows (never a stored
  hand-sum) and is a *ceiling*, not a claim, until a Gate-3 resolution is recorded.
- Maturity is carried as informational flags (``mature``/``fresh``), never as a state.
"""
from __future__ import annotations

import hashlib
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict

from klemr.canonical.provenance import Provenance
from klemr.claims.state import ClaimState
from klemr.gates.confidence import Confidence


class HoldReason(str, Enum):
    """Why a finding is held (not yet resolvable). Tier-2 appeal is carried instead by
    a dismissed finding's ``tier2_appeal_candidate`` flag, so it is not listed here."""

    IMMATURE = "immature"
    UNVERIFIED = "unverified"


class CreditMatchKey(BaseModel):
    """The minimal identity a future incoming credit line can be matched on.

    Deliberately excludes rule hash/version (provenance) and amount/date (fuzzy-confirm
    signals). RAF-1a is order-level, so ``sku_id`` is ``None``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_id: str
    charge_class: str  # e.g. "refund_administration_fee"
    sku_id: str | None = None

    def canonical(self) -> str:
        return "|".join((self.order_id, self.charge_class, self.sku_id or ""))


def make_finding_id(claim_key: str, order_id: str, rule_content_hash: str) -> str:
    """Stable, deterministic id: same (claim, order, rule content) -> same id."""
    digest = hashlib.sha256(
        f"{claim_key}|{order_id}|{rule_content_hash}".encode("utf-8")
    ).hexdigest()
    return f"{claim_key}:{digest[:16]}"


class Finding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    finding_id: str
    claim_key: str
    # --- provenance (NOT part of the match key) ---
    rule_id: str
    rule_version: str
    rule_content_hash: str
    provenance: Provenance
    # --- recovery sizing (recomputed from rows) ---
    ceiling_amount: Decimal
    credit_match_key: CreditMatchKey
    # --- gates / lifecycle ---
    confidence: Confidence
    state: ClaimState
    # maturity is an informational FLAG, never a state
    mature: bool
    fresh: bool
    hold_reason: HoldReason | None = None
    tier2_appeal_candidate: bool = False
    anomalies: tuple[str, ...] = ()
