"""Step 2 acceptance: ingestion + normalization + entity resolution on the fixtures."""
from __future__ import annotations

import glob
from pathlib import Path

import pytest

from klemr.canonical.charges import ChargeType
from klemr.canonical.events import CancellationEvent, Party
from klemr.claims.raf_1a import RafAutoCancelClaim
from klemr.ingestion.tiktok_files import _sha256_file
from klemr.normalization.pipeline import (
    fetch_tiktok,
    normalize_export,
    stable_dump,
)

ROOT = Path(__file__).resolve().parent.parent
SETTLEMENTS = sorted(glob.glob(str(ROOT / "fixtures" / "raw" / "income_*.xlsx")))
CANCELLATION = str(ROOT / "fixtures" / "raw" / "Canceled order-2026-06-17-16_14.csv")


@pytest.fixture(scope="module")
def export():
    # The slow file read happens ONCE for the whole module (openpyxl is the cost).
    return fetch_tiktok(SETTLEMENTS, CANCELLATION)


@pytest.fixture(scope="module")
def dataset(export):
    # ingested_at left None -> deterministic, never fabricated.
    return normalize_export(export)


# ---- acceptance: funnel input ----
def test_exactly_1448_canonical_cancellation_events(dataset):
    assert len(dataset.events) == 1448
    assert all(isinstance(e, CancellationEvent) for e in dataset.events)
    # unique orders (entity resolution collapsed SKU rows to order level)
    assert len({e.order_id for e in dataset.events}) == 1448


def test_charge_rows_populated(dataset):
    # In the cancellation join domain: 276 RAF deduction lines; referral is $0 on
    # fully-refunded canceled orders, so no referral charges are emitted here.
    raf = [c for c in dataset.charges if c.charge_type is ChargeType.REFUND_ADMINISTRATION_FEE]
    referral = [c for c in dataset.charges if c.charge_type is ChargeType.REFERRAL_FEE]
    assert len(raf) == 276
    assert referral == []
    assert all(c.is_deduction and c.deduction_magnitude > 0 for c in raf)


def test_no_rows_failed_to_normalize(dataset):
    # Nothing silently dropped: surface any normalization issue.
    assert dataset.issues == (), [i.detail for i in dataset.issues]


# ---- shipped_before_cancel is DERIVED on hand-picked rows ----
def test_shipped_before_cancel_on_picked_rows(dataset):
    by_id = {e.order_id: e for e in dataset.events}

    # pre-shipment: no tracking anchor -> not shipped
    pre = next(e for e in dataset.events if e.tracking_uploaded_at is None)
    assert pre.shipped_before_cancel is False

    # post-shipment: a tracking anchor recorded strictly before the cancel -> shipped
    post = next(
        e for e in dataset.events
        if e.tracking_uploaded_at is not None and e.cancelled_at is not None
    )
    assert post.tracking_uploaded_at < post.cancelled_at
    assert post.shipped_before_cancel is True

    # "no tracking" is the same neutral fact -> False (distinct order from `pre`)
    no_track = [e for e in dataset.events if e.tracking_uploaded_at is None]
    assert len(no_track) >= 2
    assert no_track[1].shipped_before_cancel is False

    # it's computed, not stored: deleting the timestamps would change the result
    assert "shipped_before_cancel" not in CancellationEvent.model_fields


# ---- provenance carries the source content hash ----
def test_provenance_carries_source_sha256(dataset):
    for e in dataset.events[:5]:
        ref = e.provenance.sources[0]
        assert ref.content_sha256 is not None and len(ref.content_sha256) == 64
        assert ref.row_indices  # which raw rows produced this event
    # every source file recorded a hash
    assert all(s.content_sha256 and len(s.content_sha256) == 64 for s in dataset.sources)


# ---- idempotency: same inputs -> byte-identical canonical output ----
def test_idempotent_byte_identical(export, dataset):
    # Re-run normalization over the same fetched bytes -> byte-identical output.
    again = normalize_export(export)
    assert stable_dump(again) == stable_dump(dataset)

    # Read determinism: the file bytes hash the same as what rode into provenance,
    # so the (pure) read step would reproduce identical input.
    recomputed = {Path(p).name: _sha256_file(Path(p)) for p in [*SETTLEMENTS, CANCELLATION]}
    for s in dataset.sources:
        assert s.content_sha256 == recomputed[s.basename]


# ---- entity resolution join ----
def test_join_index_keyed_by_order(dataset):
    assert all(rec.order_id == oid for oid, rec in dataset.by_order.items())
    # every cancellation order appears in the join
    assert {e.order_id for e in dataset.events} <= set(dataset.by_order)
    # a charge's order is always present with its cancellation (charges were scoped
    # to the cancellation domain)
    for c in dataset.charges[:20]:
        assert c.order_id in dataset.by_order


# ---- integration smoke: exercises the EXISTING plugin seam, not new logic ----
def test_plugin_in_scope_yields_1156_buyer_preship(dataset):
    claim = RafAutoCancelClaim()
    in_scope = sum(1 for e in dataset.events if claim.in_scope(e))
    assert in_scope == 1156, f"expected 1156 buyer+pre-ship, got {in_scope}"

    # cross-check the two gates independently
    buyer = sum(1 for e in dataset.events if e.initiated_by is Party.BUYER)
    assert buyer == 1156  # all buyer cancels are pre-shipment in this fixture
