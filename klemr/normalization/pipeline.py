"""Ingestion + normalization pipeline.

Wires the TikTok file adapter -> normalization -> entity resolution into one
deterministic call returning the joined canonical set. No detection, no policy.

Determinism: the engine never invents ``ingested_at``; the caller passes the real
run clock (or ``None``). :func:`stable_dump` gives a canonical serialization so
"same inputs -> identical output" is byte-checkable.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from klemr.canonical.charges import Charge
from klemr.canonical.events import CancellationEvent
from klemr.ingestion.tiktok_files import RawExport, SourceFile, TikTokFileConnector
from klemr.normalization.entity import OrderRecord, resolve
from klemr.normalization.tiktok import (
    NormalizationIssue,
    normalize_cancellations,
    normalize_charges,
)


@dataclass(frozen=True)
class CanonicalDataset:
    """The Step-2 deliverable: canonical events + charges, joined, with provenance."""

    events: tuple[CancellationEvent, ...]
    charges: tuple[Charge, ...]
    by_order: dict[str, OrderRecord]
    sources: tuple[SourceFile, ...]
    issues: tuple[NormalizationIssue, ...]


def settlement_order_ids(export: RawExport) -> set[str]:
    """Every cleaned order id present in settlement (any row, incl. zero-fee).

    Used for the period-alignment diagnostic: cancellation orders absent from this set
    settled no RAF and cannot be recovered. Independent of which charges were emitted.
    """
    from klemr.normalization.ids import clean_order_id

    ids: set[str] = set()
    for table in export.settlements:
        col = table.columns["order_id"]
        ids.update(clean_order_id(v) for v in table.frame[col])
    ids.discard("")
    return ids


def fetch_tiktok(settlement_paths, cancellation_path) -> RawExport:
    """The (slow) ingestion step: read the files into raw rows + content hashes.

    Separated from normalization so callers can read once and normalize many times;
    reading is a pure function of the file bytes (the recorded SHA-256 proves it),
    so determinism of the whole pipeline reduces to determinism of normalization.
    """
    return TikTokFileConnector(settlement_paths, cancellation_path).fetch()


def normalize_export(
    export: RawExport, *, ingested_at: datetime | None = None
) -> CanonicalDataset:
    """The (fast, deterministic) step: raw export -> joined canonical dataset."""
    events, event_issues = normalize_cancellations(export, ingested_at=ingested_at)
    order_ids = {e.order_id for e in events}
    charges, charge_issues = normalize_charges(
        export, restrict_to_orders=order_ids, ingested_at=ingested_at
    )
    by_order = resolve(events, charges)

    return CanonicalDataset(
        events=tuple(events),
        charges=tuple(charges),
        by_order=by_order,
        sources=export.sources,
        issues=tuple(event_issues) + tuple(charge_issues),
    )


def ingest_tiktok(
    settlement_paths,
    cancellation_path,
    *,
    ingested_at: datetime | None = None,
) -> CanonicalDataset:
    """Read TikTok exports -> canonical dataset (cancellation-scoped charge join)."""
    export = fetch_tiktok(settlement_paths, cancellation_path)
    return normalize_export(export, ingested_at=ingested_at)


def _charge_sort_key(c: Charge):
    src = c.provenance.sources[0] if c.provenance.sources else None
    return (
        c.order_id,
        c.charge_type.value,
        str(c.sku_id),
        str(c.amount),
        src.row_indices if src else (),
    )


def stable_dump(dataset: CanonicalDataset) -> str:
    """Deterministic JSON of the canonical output (order-independent input -> same string)."""
    events = sorted(dataset.events, key=lambda e: e.order_id)
    charges = sorted(dataset.charges, key=_charge_sort_key)
    payload = {
        "events": [e.model_dump(mode="json") for e in events],
        "charges": [c.model_dump(mode="json") for c in charges],
        "sources": [
            {"basename": s.basename, "kind": s.kind, "sheet": s.sheet,
             "content_sha256": s.content_sha256}
            for s in sorted(dataset.sources, key=lambda s: s.basename)
        ],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
