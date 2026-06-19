"""RAF-1a — the first claim-type plugin.

TikTok Shop Refund Administration Fee charged in error on buyer-initiated,
pre-shipment auto-cancellations. This module owns all RAF-specific vocabulary and
predicates ("Gate 1/2", "pre-shipment") so the canonical layer stays channel-free.
Candidate building / evidence assembly are added in Steps 3 and 5.
"""
from __future__ import annotations

from klemr.canonical.events import CancellationEvent, Party
from klemr.claims.base import ClaimType
from klemr.rules.models import Rule
from klemr.rules.store import RuleStore

RAF_1A_RULE_ID = "raf.auto_cancel_exemption"
RAF_1A_LOGIC_ID = "raf.auto_cancel.v1"


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
