"""Klemr audit engine — v7 reconciliation slice.

Governing principle, applied everywhere: **agent suggests, math decides**.
A deterministic core decides what is recoverable; agents and humans handle only
irreducible uncertainty; every finding carries provenance and is reproducible
from inputs.

Architecture lanes (each a subpackage):
    canonical/        normalized models: commerce events, charges, provenance
    rules/            versioned rule store (policy as data) + RAF-1a rule
    claims/           ClaimType plugin interface, registry, claim state machine
    gates/            confidence model + (later) the human-review gate
    ingestion/        file/connector intake            (Step 2)
    normalization/    raw -> canonical + entity resolution (Step 2)
    reconciliation/   the deterministic "accountant"   (Step 3)
    evidence/         Tier-1 evidence packet           (Step 5)
    ledger/           SQLite provenance / evidence ledger (Step 4)
    cli/              minimal CLI mirror of the engine (Step 7)

The Streamlit UI (`app.py`) is a thin shell that imports the engine; the engine
never imports the UI.
"""

__version__ = "0.1.0"
