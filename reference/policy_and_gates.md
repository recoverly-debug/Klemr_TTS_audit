# RAF Auto-Cancellation Exemption — Policy, Gates, Schemas, Anomalies

Reference for `raf-auto-cancel-audit`. Read when running the audit or interpreting flags.

## Contents
1. Policy & citation
2. The three-gate test (and why Gate 3 isn't in the data)
3. Input file schemas
4. Anomaly / human-review catalog
5. Out-of-scope boundary
6. Maturity & freshness
7. Multi-SKU and the $5 cap

---

## 1. Policy & citation

Source: **TikTok Shop US — "Referral Fee Updates"**, TikTok Shop Academy,
`https://seller-us.tiktok.com/university/essay?knowledge_id=5982454398175018`
(last revised 05/08/2025). Re-fetch to confirm wording hasn't changed before a filing cycle.

Key terms:
- **RAF = 20% of the referral fee.**
- **Capped at $5 per SKU**, effective **May 15, 2025**, calculated at the **SKU level**.
- **Exemption (this audit):** *"If a refund is initiated by the buyer before the order is
  shipped and meets the auto-canceling criteria, no Refund Administration Fee will be charged."*
- **Other exemption (out of scope, 1b):** creator "buy now, refund later" sample orders.

Supporting cancellation behavior:
- A buyer cancellation requested while the order is **pending/unshipped** auto-approves
  on a **24-hour no-action SLA** if the seller takes no action (or on the post-SLA path).
- A cancellation the buyer requests and then the system **voids within ~1 hour** never
  settles — so it never carries a RAF and never appears as a flagged candidate (the
  "present in settlement with RAF > 0" gate excludes it automatically).

---

## 2. The three-gate test

A claim is filable only if **all three** are true:

| Gate | Condition | Source |
|------|-----------|--------|
| **1 — Buyer-initiated** | Order history shows "Cancellation request submitted by customer"; cancellation export `Cancel By = User`. | Data (cancellation export) |
| **2 — Before shipment** | No tracking upload / dispatch; `RTS Time` empty; order Canceled pre-ship. | Data (cancellation export) |
| **3 — Auto-cancel criteria met** | Order history resolution line = "...awaiting approval for too long, and has now been auto-approved" (24h SLA). | **Seller Center only — NOT in the data files** |

**Why Gate 3 cannot come from the exports:** the cancellation export records *that* an order
was cancelled and *when it completed* (`Cancelled Time`), but not the **request-initiation
time** nor the **approval path**. "Seller canceled the order" and "auto-approved" both end in
a Canceled status with a settled RAF and are indistinguishable in the data. The decisive
line is in **Seller Center → Orders → Manage orders → [order] → Order history**. Verify it
per order (screenshot) or via the Order API. This is the single most important rule in the
audit; a "high-confidence/deterministic" claim that skips it is over-claiming.

**Buyer reason is noise.** "Bought by mistake", "No longer needed", "Don't want to wait",
"Incorrect shipping address", "High shipping fee" all appear in *both* the auto-approved and
seller-canceled buckets. Do not infer the resolution from the reason.

**Decision split (Phase 2):**
- `auto_approved` → **Tier 1**, filable.
- `seller_canceled` → **Tier 2**, hold (contestable: one may argue any pre-shipment buyer
  cancel should be exempt regardless of approver, but it is not clean — keep it separate).
- `other` → human review.

---

## 3. Input file schemas

### Settlement — TikTok "income" .xlsx, sheet "Order details"
Join key and money columns (fuzzy-matched by the script):
- `Order/adjustment ID` — order id (join key).
- `Refund administration fee` — **negative** deduction; magnitude is the RAF. Summed per order.
- `Referral fee` — net referral (≈ $0 on fully-refunded rows); used only for the 20% sanity check.
- `Statement date` — finance-side settlement date; drives maturity/freshness.

### Cancellation — TikTok "Canceled_order...csv"
- `Order ID` — **may carry trailing tabs / zero-width chars**; cleaned before joining.
- `Cancel By` — `User` (buyer), `System`, `Seller`, `Operator`. Only `User` is 1a-eligible.
- `RTS Time` — Ready-to-Ship / tracking-upload anchor; **empty = pre-shipment**.
- `Cancelled Time` — completion timestamp (NOT the request-initiation time).
- `Cancel Reason` — buyer's stated reason (informational only).

Rows are at SKU level; the script collapses to order level.

---

## 4. Anomaly / human-review catalog

`detect.py` writes `anomalies.csv` (genuine issues) and separate informational files.

| Code (anomalies.csv) | Meaning | Action |
|---|---|---|
| `RAF_LINE_EXCEEDS_CAP` | A single RAF line > $5/SKU cap. | Verify SKU split in settlement; a legit multi-SKU order can have multiple ≤$5 lines summing higher, but one line >$5 is a policy anomaly worth its own note. |
| `RAF_ABOVE_20PCT_REFERRAL` | Order RAF exceeds ~20% of referral (beyond rounding). | Verify referral figure; may indicate a different fee mislabeled. |
| `MISSING_SETTLEMENT_DATE` | No statement date on a flagged order. | Maturity can't be assessed; verify manually before filing. |

Informational (not anomalies, separate files):
- **not_in_settlement.csv** — buyer-pre cancels absent from settlement. Causes: settlement-
  timing lag at the window edge, payment voided pre-capture, payment never captured. **No
  settled refund = no RAF = nothing to recover.** Don't chase these.
- **raf_out_of_scope_informational.csv** — RAF charged on `Cancel By` ≠ `User` or RTS-present
  (shipped) orders. **Correctly billed under 1a logic.** May belong to other leakage audits
  (post-ship returns, 1b creator samples) — not this one.

Build-time flags (`build_packet.py`, printed before the PDF):
- **NEEDS REVIEW** — candidate with blank/`other` resolution; excluded from totals until resolved.
- **Missing screenshot** — filable order without an exhibit; page renders "EXHIBIT PENDING".
- **Freshly settled** — settled within `--fresh-days` (default 3); file in a second wave once
  outside TikTok's reconciliation window.

---

## 5. Out-of-scope boundary

This skill handles **1a only**. Explicitly do NOT fold in:
- **1b — creator-sample RAF** ("buy now, refund later" affiliate samples). Different exemption;
  needs affiliate/sample data. Route to its own audit.
- **Post-ship returns / RTS-present orders** — RAF is generally chargeable.
- **FBT / 3PL fee rows** — not RAF; different reconciliation. (Haus is seller-fulfilled via
  FlexPort warehouse but ships itself — RAF applies; FBT does not.)
- **Other settlement leakage** (referral non-reversal, reserves, promo/affiliate funding) —
  separate rows, separate logic.

If a candidate looks like one of these, note it and exclude it; don't stretch 1a to cover it.

---

## 6. Maturity & freshness

- **Mature** = `Statement date ≤ as-of − maturity_days` (default 21). Mature claims are safely
  past TikTok's settlement reconciliation and ready to verify/file first.
- **Fresh** = settled within `fresh_days` (default 3) of as-of. File these in a second wave.
- Immature-but-not-fresh claims are real; just re-verify their resolution once they mature, as
  a very recent cancellation can still change state.

Tune with `--maturity-days` / `--fresh-days` if TikTok's reconciliation window shifts.

---

## 7. Multi-SKU and the $5 cap

RAF is per-SKU and capped at $5 per SKU. A multi-SKU order carries a RAF line per SKU; the
order's recoverable amount is the **sum of those lines** (each ≤ $5). `detect.py` reports
the order total (`recoverable_amount`), the line count (`raf_lines`), and the largest single
line (`raf_max_line`) so cap breaches surface. When describing a multi-SKU claim in the
packet, note that the figure is the order total across its SKU lines.
