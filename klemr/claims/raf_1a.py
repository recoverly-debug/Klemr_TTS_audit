"""RAF-1a — the first claim-type plugin.

TikTok Shop Refund Administration Fee charged in error on buyer-initiated,
pre-shipment auto-cancellations. This module owns ALL RAF-specific policy: the
vocabulary ("Gate 1/2", "pre-shipment"), the scope predicates, and the fee schedule
that interprets the generic rule's ``payload``. The canonical and rule-envelope
layers stay claim-agnostic. Candidate building / evidence assembly are Steps 3 and 5.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from klemr.canonical.events import CancellationEvent, Party
from klemr.canonical.money import to_money
from klemr.claims.base import ClaimType
from klemr.rules.models import Rule
from klemr.rules.store import RuleStore

RAF_1A_RULE_ID = "raf.auto_cancel_exemption"
RAF_1A_LOGIC_ID = "raf.auto_cancel.v1"


class RafFeeSchedule(BaseModel):
    """RAF fee math as data: RAF = ``referral_fee_rate`` x referral, capped per SKU.

    This is RAF-specific policy and lives with the RAF plugin — the generic rule
    envelope carries it only as an opaque ``payload`` blob.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    referral_fee_rate: Decimal  # e.g. 0.20
    per_sku_cap: Decimal  # e.g. 5.00
    cap_effective_date: date
    cap_basis: Literal["sku"]
    currency: str = "USD"

    def raf_for_sku(self, referral_amount: Decimal | str | float) -> Decimal:
        """Theoretical RAF for ONE SKU: ``rate x |referral|`` capped at ``per_sku_cap``,
        quantized to cents.

        The *expected* fee, used for anomaly/sanity checks — NOT how recovery is sized
        (recovery is the RAF actually charged in settlement, summed from rows). ``abs``
        is used because referral/RAF lines are stored negative.
        """
        raw = to_money(abs(Decimal(str(referral_amount))) * self.referral_fee_rate)
        return min(raw, self.per_sku_cap)

    def raf_for_order(self, sku_referrals: Iterable[Decimal | str | float]) -> Decimal:
        """Cap PER SKU, THEN sum — at cent precision per SKU (policy_and_gates.md §7)."""
        total = Decimal("0.00")
        for referral in sku_referrals:
            total += self.raf_for_sku(referral)
        return total


class RafAutoCancelClaim(ClaimType):
    key = "raf-1a"
    title = "TikTok Shop RAF — Auto-Cancellation Exemption (Leakage 1a)"
    rule_id = RAF_1A_RULE_ID
    logic_id = RAF_1A_LOGIC_ID

    def rule(self, store: RuleStore) -> Rule:
        # Latest version by default; reconciliation may instead pick the version
        # effective on a settlement date via ``store.effective_on``.
        rule = store.latest(self.rule_id)
        self.assert_compatible(rule)  # FIX 3 — explicit rule->logic binding
        return rule

    def fee_schedule(self, rule: Rule) -> RafFeeSchedule:
        """Interpret the generic rule's payload into the RAF-typed fee schedule.

        Only valid after ``assert_compatible`` (logic_id match) — enforced here.
        """
        self.assert_compatible(rule)
        return RafFeeSchedule.model_validate(rule.payload["fee_schedule"])

    # ---- scope filter: the two data-derivable gates (Gates 1 & 2) ----
    # "Gate" / "pre-shipment" is RAF vocabulary and lives HERE, not on the canonical
    # event. A carrier-overcharge claim type has no Gate 1; it defines its own filter.
    @staticmethod
    def gate1_buyer_initiated(event: CancellationEvent) -> bool:
        """Gate 1 — the cancellation was initiated by the buyer."""
        return event.initiated_by is Party.BUYER

    @staticmethod
    def gate2_pre_shipment(event: CancellationEvent) -> bool:
        """Gate 2 — pre-shipment: no dispatch anchor preceded the cancellation.

        RAF-1a's definition of "shipped" is precisely the canonical neutral fact
        ``shipped_before_cancel`` (tracking uploaded *strictly before* the cancel —
        tracking at the exact cancel instant does not count as shipped); the
        *interpretation* that this disqualifies a claim is the plugin's, not the
        event's.
        """
        return not event.shipped_before_cancel

    def in_scope(self, event: CancellationEvent) -> bool:
        """Gates 1 AND 2 — the data-derivable scope for RAF-1a.

        Gate 3 (decisive: auto-approved vs seller-canceled) is deliberately absent:
        it is not in the data and must be resolved by a human or the Order API.
        """
        return self.gate1_buyer_initiated(event) and self.gate2_pre_shipment(event)
