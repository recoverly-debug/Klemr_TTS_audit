"""Commerce event ledger.

Normalized, **channel- and policy-free** business events about orders. The model
carries only raw facts; what counts as "shipped", which party is "eligible", and
what a "gate" is are channel/claim-type concerns owned by the relevant plugin's
scope filter — never baked in here. This is what lets a future carrier-overcharge
or 3PL claim type reuse the event model unchanged.

The one derived value exposed, ``shipped_before_cancel``, is a neutral temporal
observation (did a dispatch anchor precede the cancel), not a policy verdict.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict

from klemr.canonical.provenance import Provenance


class EventType(str, Enum):
    CANCELLATION = "cancellation"


class Party(str, Enum):
    """Channel-agnostic actor that initiated an action.

    Normalization (Step 2) maps each channel's own vocabulary (e.g. TikTok's
    ``Cancel By = User``) onto these members; canonical never stores channel terms.
    """

    BUYER = "buyer"
    SELLER = "seller"
    SYSTEM = "system"
    OPERATOR = "operator"
    OTHER = "other"


class StatusTransition(BaseModel):
    """One raw fulfillment-status change as the channel reported it.

    ``label`` is the channel's own status string — canonical does not enumerate any
    channel's status set, keeping the model channel-agnostic.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str
    at: datetime | None = None


class CommerceEvent(BaseModel):
    """Base normalized event. Channel- and policy-agnostic."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_id: str
    event_type: EventType
    provenance: Provenance


class CancellationEvent(CommerceEvent):
    """A cancellation, collapsed from SKU-level rows to order level — raw facts only."""

    event_type: EventType = EventType.CANCELLATION
    # Who initiated the cancellation (normalized actor; raw value kept for provenance).
    initiated_by: Party
    initiated_by_raw: str = ""
    # Dispatch/tracking anchor. ``None`` == no anchor recorded by the channel.
    tracking_uploaded_at: datetime | None = None
    cancelled_at: datetime | None = None
    reason: str | None = None
    # Full lifecycle when available; the two fields above are the RAF-relevant subset.
    status_transitions: tuple[StatusTransition, ...] = ()

    @property
    def shipped_before_cancel(self) -> bool:
        """Neutral temporal fact, DERIVED (never ingested as a flag): was a dispatch
        anchor recorded *strictly before* the cancellation?

        ``= (tracking_uploaded_at is not None) and (tracking_uploaded_at < cancelled_at)``

        This carries no channel's *definition* of "shipped" and no eligibility
        verdict — the channel decides what populates ``tracking_uploaded_at`` and a
        claim-type plugin decides whether this fact disqualifies a claim. A missing
        tracking anchor (or missing cancel time) reads as not-shipped.
        """
        if self.tracking_uploaded_at is None or self.cancelled_at is None:
            return False
        return self.tracking_uploaded_at < self.cancelled_at
