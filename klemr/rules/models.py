"""Versioned rule model — **policy as data, never hardcoded constants**.

A ``Rule`` is an immutable, versioned record of a policy: the fee schedule (rate,
cap, effective date), the verbatim citation, the three-gate test, and the
resolution -> tier mapping. Findings reference a rule by ``rule_id`` + ``version``
+ ``content_hash`` so any result is reproducible and traceable to the exact policy
text that produced it.

Nothing here computes recoverable money or eligibility — those need charges/events
and live in reconciliation. This module is the *data* and the pure policy helpers
(maturity math, resolution classification) that operate only on the rule itself.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from klemr.canonical.money import to_money


def _norm(s: object) -> str:
    """Normalize a token for alias matching: lower, keep alphanumerics and ``_``.

    Mirrors the normalization in the reference ``build_packet.py`` so the engine
    classifies resolutions identically to the oracle.
    """
    return "".join(ch for ch in str(s).strip().lower() if ch.isalnum() or ch == "_")


class PolicyCitation(BaseModel):
    """Verbatim source of the policy, for the packet cover and re-verification."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str
    publisher: str
    url: str
    last_revised: date
    quote: str


class RafFeeSchedule(BaseModel):
    """The fee math as data: RAF = ``referral_fee_rate`` x referral, capped per SKU."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    referral_fee_rate: Decimal  # e.g. 0.20
    per_sku_cap: Decimal  # e.g. 5.00
    cap_effective_date: date
    cap_basis: Literal["sku"]
    currency: str = "USD"

    def raf_for_sku(self, referral_amount: Decimal | str | float) -> Decimal:
        """Theoretical RAF for ONE SKU: ``rate x |referral|`` capped at ``per_sku_cap``,
        quantized to cents.

        This is the *expected* fee, used for the anomaly/sanity checks. It is NOT how
        the recovery is sized: on the 1a path the amount recovered is the RAF that was
        actually charged in settlement, summed from the rows (never a re-derived
        figure). ``abs`` is used because referral/RAF lines are stored negative.
        """
        raw = to_money(abs(Decimal(str(referral_amount))) * self.referral_fee_rate)
        return min(raw, self.per_sku_cap)

    def raf_for_order(self, sku_referrals: Iterable[Decimal | str | float]) -> Decimal:
        """Cap PER SKU, THEN sum — at cent precision per SKU.

        Mirrors policy (policy_and_gates.md §7): each SKU's RAF is independently
        capped at $5 before the order total is taken; an order total is never capped
        as a whole.
        """
        total = Decimal("0.00")
        for referral in sku_referrals:
            total += self.raf_for_sku(referral)
        return total


class RuleParameters(BaseModel):
    """Operational, tunable knobs (not policy text). Drive maturity/freshness."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    maturity_days: int = 21
    fresh_days: int = 3

    def mature_cutoff(self, as_of: date) -> date:
        return as_of - timedelta(days=self.maturity_days)

    def fresh_cutoff(self, as_of: date) -> date:
        return as_of - timedelta(days=self.fresh_days)

    def is_mature(self, statement_date: date | None, as_of: date) -> bool:
        """Mature == settled on/before ``as_of - maturity_days`` (boundary is mature)."""
        if statement_date is None:
            return False
        return statement_date <= self.mature_cutoff(as_of)

    def is_fresh(self, statement_date: date | None, as_of: date) -> bool:
        """Fresh == settled strictly after ``as_of - fresh_days`` (file in 2nd wave)."""
        if statement_date is None:
            return False
        return statement_date > self.fresh_cutoff(as_of)


class Gate(BaseModel):
    """One condition in the three-gate test.

    ``in_data`` encodes the single most important invariant in the audit: Gate 3
    (``in_data == False``) cannot be read from the export files and must never be
    inferred — it is resolved only by a human or the Order API.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    number: int
    key: str
    name: str
    source: Literal["data", "seller_center"]
    in_data: bool
    decisive: bool
    description: str


class ResolutionOutcome(BaseModel):
    """A verified resolution and the claim tier it routes to."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    resolution: str  # canonical label, e.g. "auto_approved"
    tier: str  # e.g. "filable_tier1"
    aliases: tuple[str, ...] = ()


class ResolutionPolicy(BaseModel):
    """Maps a raw, human/API-supplied Gate-3 resolution to an outcome tier.

    This is the decision split as data. ``classify`` is the only place a resolution
    string becomes a tier; the buyer's cancel *reason* is never an input here
    (reason is noise).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    filable: ResolutionOutcome
    held: ResolutionOutcome
    review: ResolutionOutcome

    def classify(self, raw: object) -> ResolutionOutcome:
        n = _norm(raw)
        if n and n in {_norm(a) for a in self.filable.aliases}:
            return self.filable
        if n and n in {_norm(a) for a in self.held.aliases}:
            return self.held
        return self.review


class Rule(BaseModel):
    """An immutable, versioned policy rule. ``extra='forbid'`` catches schema drift
    in the JSON data files at load time."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: str
    version: str
    # Binds this rule's DATA to the engine LOGIC allowed to evaluate it. A claim-type
    # plugin asserts a rule's logic_id matches its own before it will touch the rule,
    # so a future plugin sharing the store can never silently mis-apply this policy.
    logic_id: str
    effective_date: date
    supersedes: str | None = None
    title: str
    description: str
    citation: PolicyCitation
    fee_schedule: RafFeeSchedule
    parameters: RuleParameters
    gates: tuple[Gate, ...]
    resolution_policy: ResolutionPolicy

    def content_hash(self) -> str:
        """Deterministic SHA-256 over the rule's canonical JSON.

        Stored on findings for reproducibility: same inputs + same rule hash =>
        same result, and any edit to the policy data changes the hash.
        """
        payload = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def decisive_gate(self) -> Gate:
        """The single gate that decides filability and is not in the data (Gate 3)."""
        return next(g for g in self.gates if g.decisive)
