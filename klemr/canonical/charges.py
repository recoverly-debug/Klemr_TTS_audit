"""Canonical charge model.

A ``Charge`` is one money line tied to an order. RAF and referral fees are both
charges, distinguished by ``charge_type`` — the engine never special-cases a column
name, only a charge type. Amounts are stored signed (negative = deduction) exactly
as settlement reports them; magnitude is derived.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, field_validator

from klemr.canonical.money import to_money
from klemr.canonical.provenance import Provenance


class ChargeType(str, Enum):
    """Kinds of settlement money lines the engine understands.

    Extensible: other leakage audits add members without touching the charge model.
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

        This is the value the RAF audit recovers: detect.py computes a per-order
        RAF as the magnitude of the negative ``Refund administration fee`` lines.
        """
        return -self.amount if self.amount < 0 else Decimal("0.00")
