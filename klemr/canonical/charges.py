"""Canonical charge model.

A ``Charge`` is one money line tied to an order, classified by a generic
``charge_type`` — the engine never special-cases a marketplace column name, only a
charge class. Each marketplace's fee labels are mapped onto this taxonomy in its
normalizer. Amounts are stored signed (negative = deduction) exactly as settlement
reports them; magnitude is derived.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, field_validator

from klemr.canonical.money import to_money
from klemr.canonical.provenance import Provenance


class ChargeType(str, Enum):
    """Generic marketplace fee taxonomy (channel-agnostic). A normalizer maps each
    marketplace's own fee labels onto these classes; new classes are added here without
    touching the charge model.

    (Review note: these two named fee classes are common across marketplaces but the
    enum is still an enumerated vocabulary in the canonical layer. A fully open
    ``charge_type: str`` code — like ``CreditMatchKey.charge_class`` already is — would
    be even more channel-neutral; deferred as a model-shape decision.)
    """

    REFUND_ADMINISTRATION_FEE = "refund_administration_fee"
    REFERRAL_FEE = "referral_fee"
    OTHER = "other"


class Charge(BaseModel):
    """One signed money line from settlement, attributed to an order (+ optional SKU)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_id: str
    charge_type: ChargeType
    # Signed as reported by TikTok: a fee/deduction is negative.
    amount: Decimal
    sku_id: str | None = None
    statement_date: date | None = None
    provenance: Provenance

    @field_validator("amount", mode="before")
    @classmethod
    def _quantize(cls, v: object) -> Decimal:
        return to_money(v)

    @property
    def is_deduction(self) -> bool:
        """True when this line takes money from the seller (negative amount)."""
        return self.amount < 0

    @property
    def deduction_magnitude(self) -> Decimal:
        """Positive magnitude of a deduction; ``0`` for non-deductions.

        A claim recovers the magnitude of the negative fee lines it targets (summed per
        order); how a recovery uses it is the claim plugin's concern, not the model's.
        """
        return -self.amount if self.amount < 0 else Decimal("0.00")
