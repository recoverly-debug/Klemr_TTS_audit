# Klemr Audit Engine

First vertical slice of the v7 reconciliation engine. One claim type, end to end,
with clean seams for the rest of v7 to plug in.

**Governing principle: _agent suggests, math decides._** A deterministic core decides
what is recoverable; agents/humans handle only irreducible uncertainty; every finding
carries provenance and is reproducible from inputs.

**Claim type in scope (only this one):** TikTok Shop Refund Administration Fee (RAF)
charged in error on buyer-initiated, pre-shipment auto-cancellations — _Leakage 1a_.

## Layout (by architecture lane)

```
app.py                 Streamlit review UI — thin shell over the engine (Step 6)
klemr/
  canonical/           normalized models: commerce events, charges, money, provenance
  rules/               versioned rule store — POLICY AS DATA + the RAF-1a rule JSON
  claims/              ClaimType plugin interface, registry, claim state machine
  gates/               per-finding confidence model + human-review gate (Step 4)
  ingestion/           file/connector intake seam (Step 2)
  normalization/       raw -> canonical + entity resolution (order-ID cleaner)
  reconciliation/      the deterministic "accountant" (Step 3)
  evidence/            Tier-1 evidence packet PDF (Step 5)
  ledger/              SQLite evidence/provenance ledger (Step 4)
  cli/                 minimal typer CLI (Step 7)
tests/                 engine tests (not the UI)
fixtures/              acceptance-test oracle (raw exports, resolutions, screenshots)
reference/             the spec to MATCH (detect.py, build_packet.py, *.md) — do not modify
```

The UI imports the engine; the engine never imports the UI.

## Rule store — policy as data

The RAF policy is **not** hardcoded. It lives in a versioned JSON rule
(`klemr/rules/data/raf_auto_cancel_exemption.v2025-05-15.json`) loaded by `RuleStore`:
fee schedule (20% / $5-per-SKU / effective 2025-05-15), verbatim citation, the
three-gate test, and the resolution→tier mapping. Each rule has a deterministic
`content_hash()` so findings are reproducible and traceable to exact policy text.

The most important fact is encoded structurally: **Gate 3 (`auto_approved`) has
`in_data: false`** — it cannot be read from the exports and must never be inferred.

## Develop

```bash
uv sync                 # core engine + dev (pydantic, pytest); Python pinned to 3.12
uv run pytest           # run the engine tests

# heavier lanes install their deps on demand, per build step:
uv sync --extra ingest  # pandas + openpyxl  (Step 2)
uv sync --extra packet  # reportlab + pillow (Step 5)
uv sync --extra ui      # streamlit          (Step 6)
```

## Build order

1. **Skeleton + canonical models + versioned rule store + tests.** ← this slice
2. Ingestion + normalization into commerce/charge ledgers + entity resolution.
3. Reconciliation → candidates + confidence gate + anomaly split + provenance ledger
   (reproduce the detection funnel).
4. Human gate: review queue + resolution writes to ledger + claim state machine.
5. Evidence assembly: Tier-1 packet PDF.
6. Streamlit `app.py` wiring steps 1–5 into the 4-step UI flow.
7. Minimal CLI; full end-to-end run on the fixtures.
