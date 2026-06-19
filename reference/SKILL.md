---
name: raf-auto-cancel-audit
description: >
  Audit TikTok Shop settlement data for Refund Administration Fee (RAF) charged in
  error on buyer-initiated, pre-shipment auto-cancellations, and produce a filable
  evidence packet. Use this whenever Anwesha (Klemr) is auditing a merchant's TikTok
  Shop money for cancellation-related RAF leakage — e.g. she uploads a TikTok "income"
  / settlement export plus a "Canceled_order" export and asks to find RAF that should
  have been waived, to check whether a brand (Haus or any seller-fulfilled brand) is
  owed RAF refunds, to flag which cancellation RAFs are recoverable, or to build /
  regenerate the RAF evidence packet or claim list. Trigger even if she just says
  "run the RAF audit", "RAF exemption", "auto-cancel RAF", "refund admin fee refund",
  or names the two export files. Scope is the auto-cancellation exemption ONLY
  (Leakage 1a); it does NOT cover creator-sample RAF (1b) or any other leakage row.
---

# TikTok Shop RAF Auto-Cancellation Exemption Audit (Leakage 1a)

## What this audit recovers

TikTok Shop charges a **Refund Administration Fee (RAF)** = 20% of the referral fee,
capped at **$5 per SKU**, on refunds. But policy carves out an exemption:

> "If a refund is initiated by the buyer before the order is shipped and meets the
> auto-canceling criteria, no Refund Administration Fee will be charged."

When a buyer cancels a not-yet-shipped order and TikTok's **24-hour no-action SLA
auto-approves** the cancellation, the RAF should be **$0**. Sellers who instead
*manually* approve those cancellations (or where TikTok bills the RAF anyway) leak
money. This audit finds those leaks and packages them for filing.

**Scope guardrail:** this is the auto-cancellation exemption (1a) only. Creator
"buy now, refund later" sample orders (1b), post-ship returns, FBT/3PL fees, and other
settlement rows are out of scope — see `references/policy_and_gates.md`.

## The one rule that governs everything

**The data files cannot prove the exemption. A human (or the Order API) must.**

The settlement and cancellation exports tell you an order was *buyer-initiated* and
*pre-shipment* and *had a RAF charged* — Gates 1 and 2. They do **not** tell you whether
the cancellation was **auto-approved** (filable) or **seller-canceled** (not filable).
That decisive signal — **Gate 3** — lives only in the Seller Center **Order history**
resolution line. So this skill runs in two phases: detect candidates from data, then
build the packet only after the resolution of each candidate has been verified. Never
present a candidate ceiling as recoverable money, and never skip Gate 3.

## Inputs to collect

1. **Settlement export(s)** — TikTok "income" `.xlsx`, sheet **"Order details"**. One or
   more files (date ranges) are fine; they're concatenated. Key columns: `Order/adjustment ID`,
   `Refund administration fee` (stored negative), `Referral fee`, `Statement date`.
2. **Cancellation export** — TikTok `Canceled_order...csv`. Key columns: `Order ID`
   (often has trailing tabs — handled), `Cancel By` (`User` = buyer), `RTS Time`
   (Ready-to-Ship; empty = pre-shipment), `Cancelled Time`, `Cancel Reason`.
3. **(Phase 2) Order-history resolution** — per candidate, the Seller Center order page's
   Order history line, captured as a screenshot and/or recorded as `auto_approved` vs
   `seller_canceled`. This is what makes a claim filable.

If a file is missing or a column can't be located, say so and stop — don't guess.

## Workflow

### Phase 1 — Detect candidates (deterministic)

Run:

```bash
python scripts/detect.py \
  --settlement <income1.xlsx> [income2.xlsx ...] \
  --cancellations <Canceled_order.csv> \
  --asof <YYYY-MM-DD> \
  --out <out_dir>
```

This writes to `<out_dir>`:
- **candidates.csv** — every flagged order (buyer-initiated + pre-shipment + RAF charged),
  with `recoverable_amount`, `mature`, `fresh`, a `seller_center_url`, and three **blank**
  columns to fill in Phase 2: `resolution`, `resolution_timestamp`, `screenshot`.
- **anomalies.csv** — genuine data issues that need human eyes (cap breaches, RAF above
  20% of referral, missing settlement date). Empty is good.
- **not_in_settlement.csv** — buyer-pre cancels with no settled RAF (no refund = nothing
  to recover; informational).
- **raf_out_of_scope_informational.csv** — RAF charged on post-ship/non-buyer cancels.
  Correctly billed, NOT 1a; ignore for this audit (may feed other leakage audits).
- **summary.txt / summary.json** — the funnel.

Report the funnel to Anwesha and state plainly that the flagged total is a **ceiling, not
a claim**. Then walk through anything in `anomalies.csv`. See the anomaly catalog in
`references/policy_and_gates.md` for what each code means and how to handle it.

### Phase 2 — Verify Gate 3 (human / API)

For each candidate, open the `seller_center_url` and read the **Order history** line:
- **"...awaiting approval for too long, and has now been auto-approved"** → `auto_approved`
  → FILABLE. Record the timestamp; save an order-history screenshot.
- **"Seller canceled the order"** → `seller_canceled` → HOLD (Tier 2, contestable).
- anything else → `other` → human review.

The **buyer reason is noise** — "bought by mistake", "no longer needed", etc. appear in
both buckets. Only the resolution line decides. Fill `resolution`,
`resolution_timestamp`, and `screenshot` (filename) in candidates.csv.

If the merchant grants Order API access, the resolution line can be pulled programmatically
instead of by screenshot — same field, same logic.

### Phase 3 — Build the evidence packet

Run:

```bash
python scripts/build_packet.py \
  --candidates <out_dir>/candidates.csv \
  --screenshots <dir_of_order_history_screenshots> \
  --client "<Merchant Name>" --brand "Klemr" \
  --asof "<Month D, YYYY>" \
  --out <out_dir>/RAF_Tier1_Evidence_Packet.pdf
```

It splits claims by `resolution`, **recomputes every total from scratch** (never trusts a
running tally — see "Math decides" below), and produces a polished PDF: cover with policy
basis and the three-gate test, a claim-summary table, and **one evidence page per filable
claim** (navy header with order ID + RAF, fact grid, three green gate chips, conclusion,
and the embedded Seller Center screenshot). Screenshots match by the `screenshot` filename
or by order-ID substring in the screenshots directory.

The build prints flags **before** writing the PDF — resolve these before filing:
- **NEEDS REVIEW** rows (blank/`other` resolution) — totals aren't final until cleared.
- **Missing screenshot** for a filable order — the page renders "EXHIBIT PENDING".
- **Freshly-settled** orders (`fresh`) — file in a second wave once outside TikTok's
  reconciliation window (~a few days).

Present the PDF with `present_files`.

## When to flag the human instead of proceeding

Stop and surface the issue (don't silently proceed) when:
- A required input file or column is missing/unrecognized → ask for the right export.
- `anomalies.csv` is non-empty → walk through each before counting those orders.
- Any candidate still has a blank/`other` resolution at build time → it's excluded and
  flagged NEEDS REVIEW; tell Anwesha which ones and why.
- A filable order lacks a screenshot → packet marks it EXHIBIT PENDING.
- The cancellation set contains `Cancel By` values other than `User` that carried a RAF, or
  RTS-present (shipped) orders with RAF → these are out of 1a scope; note, don't claim.
- Settlement and cancellation files clearly cover mismatched date ranges → the join will
  undercount; tell her.

## Math decides

This audit's principle is **"agent suggests, math decides."** Always recompute totals
from the underlying rows; never carry forward a hand-summed subtotal (a $0.50 error crept
in exactly that way during the first Haus run). `build_packet.py` re-sums from scratch by
design — trust its printed totals over anything stated earlier in conversation.

## Reference

Read `references/policy_and_gates.md` for: the verbatim policy citation and source URL,
the full three-gate definitions, exact file/column schemas, the anomaly-code catalog,
and the out-of-scope boundary (1b / post-ship / 3PL).
