# Haus Apparel — RAF 1a Ground-Truth Fixture

Ground truth for acceptance-testing the Klemr audit engine (claim type: TikTok Shop
Refund Administration Fee on buyer-initiated, pre-shipment auto-cancellations — "1a").
Use alongside the two raw Haus exports (settlement `.xlsx` + cancellation `.csv`).

## Contents
- `resolutions_haus.csv` — the verified Gate-3 resolution for all 30 flagged orders
  (the part the data files cannot tell you), with the expected amount and tier.
- `screenshots/<order_id>.png` — the Seller Center order-history exhibit for each order,
  named by order ID so the packet builder auto-matches with no mapping step.

## resolutions_haus.csv columns
| column | meaning |
|---|---|
| `order_id` | TikTok order ID (join key) |
| `resolution` | `auto_approved` (filable) or `seller_canceled` (dismissed) — the Gate-3 truth |
| `resolution_timestamp` | order-history resolution line timestamp, as displayed |
| `expected_amount` | RAF deducted on that order (recoverable if auto_approved) |
| `screenshot` | exhibit filename in `screenshots/` |
| `expected_tier` | `filable_tier1` or `dismissed` |

## Expected results (the numbers the engine must reproduce)

Detection from the raw exports (data only):
- 1448 canceled orders → 1156 buyer-initiated & pre-shipment → **30 flagged**
- Flagged ceiling: **$20.61** (NOT a claim — Gate 3 unverified)
- 24 mature, 1 freshly-settled; 0 genuine anomalies; 206 out-of-scope informational

After applying these resolutions (engine state model: seller_canceled is decisively NOT
exempt under 1a, so it routes to terminal `dismissed` + `tier2_appeal_candidate`, not held):
- **Filable (auto_approved): 23 orders, $15.72**
- **Dismissed (seller_canceled, tier2_appeal_candidate): 7 orders, $4.89**
- 0 held, 0 needs-review; 23 + 7 + 0 = 30 reconciled; packet has 23 evidence pages
- Maturity is an informational flag, not a state: the 1 freshly-settled order
  (577433652962431469) is a *filable* finding flagged fresh (file in 2nd wave), so
  filable stays 23.

## How to use in the engine's acceptance test
1. Run detection on the raw exports → candidates. Assert the funnel numbers above.
2. Left-join `resolutions_haus.csv` on `order_id` to supply `resolution` /
   `resolution_timestamp`. Point the packet builder's screenshots dir at `screenshots/`.
3. Build the Tier-1 packet. Assert: 23 filable, total == $15.72 (recomputed from rows),
   7 held == $4.89, 0 review, 23 evidence pages.

Note: amounts are TikTok's displayed-to-the-cent settlement figures; recompute the
Tier totals from the row amounts (never a hand-sum) — that is the "math decides" check.
