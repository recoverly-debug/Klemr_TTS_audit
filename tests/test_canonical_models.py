"""Canonical model unit tests: id cleaning, RAF magnitude, money rounding, gate readings."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from klemr.canonical import (
    CancellationEvent,
    Charge,
    ChargeType,
    EventType,
    Party,
    Provenance,
    SourceRef,
    to_money,
)
from klemr.normalization import clean_order_id

PROV = Provenance(sources=(SourceRef(source_file="x.csv"),))


# ---- entity resolution: id cleaning ----
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("576478578200712737\t", "576478578200712737"),
        ("\t576478578200712737\t\t", "576478578200712737"),
        ("576478578200712737​", "576478578200712737"),
        ("  576478578200712737  ", "576478578200712737"),
        (576478578200712737, "576478578200712737"),
    ],
)
def test_clean_order_id(raw, expected):
    assert clean_order_id(raw) == expected


# ---- money: cent rounding, float artefacts kept out ----
def test_to_money_quantizes_and_avoids_float_drift():
    assert to_money("3.1") == Decimal("3.10")
    assert to_money(0.1) + to_money(0.2) == Decimal("0.30")
    assert to_money("2.345") == Decimal("2.35")  # HALF_UP


# ---- charge: RAF magnitude is the magnitude of the NEGATIVE deduction ----
def test_raf_magnitude_from_negative_deduction():
    raf = Charge(
        order_id="1",
        charge_type=ChargeType.REFUND_ADMINISTRATION_FEE,
        amount="-0.73",
        provenance=PROV,
    )
    assert raf.is_deduction is True
    assert raf.deduction_magnitude == Decimal("0.73")


def test_non_deduction_has_zero_magnitude():
    credit = Charge(
        order_id="1", charge_type=ChargeType.OTHER, amount="5.00", provenance=PROV
    )
    assert credit.is_deduction is False
    assert credit.deduction_magnitude == Decimal("0.00")


# ---- cancellation event: raw facts only, no policy verdicts ----
def test_cancellation_event_carries_raw_facts_only():
    ev = CancellationEvent(
        order_id="1",
        initiated_by=Party.BUYER,
        initiated_by_raw="User",
        tracking_uploaded_at=None,
        cancelled_at=datetime(2026, 5, 2, 9, 0),
        reason="bought by mistake",
        provenance=PROV,
    )
    assert ev.event_type is EventType.CANCELLATION
    assert ev.initiated_by is Party.BUYER
    # the canonical event exposes NO RAF/channel policy verdict — those moved to the
    # plugin scope filter (FIX 1 & 2).
    assert not hasattr(ev, "pre_shipment")
    assert not hasattr(ev, "buyer_initiated")


def test_shipped_before_cancel_is_a_neutral_temporal_fact():
    # no dispatch anchor -> not shipped
    no_track = CancellationEvent(
        order_id="1",
        initiated_by=Party.BUYER,
        tracking_uploaded_at=None,
        cancelled_at=datetime(2026, 5, 2),
        provenance=PROV,
    )
    assert no_track.shipped_before_cancel is False

    # tracking uploaded before the cancel -> shipped
    before = CancellationEvent(
        order_id="1",
        initiated_by=Party.BUYER,
        tracking_uploaded_at=datetime(2026, 5, 1),
        cancelled_at=datetime(2026, 5, 2),
        provenance=PROV,
    )
    assert before.shipped_before_cancel is True

    # tracking present but no cancel time -> cannot assert tracking precedes cancel
    # (strict-< definition, None-guarded) -> not shipped_before_cancel
    open_cancel = CancellationEvent(
        order_id="1",
        initiated_by=Party.BUYER,
        tracking_uploaded_at=datetime(2026, 5, 1),
        cancelled_at=None,
        provenance=PROV,
    )
    assert open_cancel.shipped_before_cancel is False

    # tracking AT the cancel instant is not strictly before -> not shipped
    simultaneous = CancellationEvent(
        order_id="1",
        initiated_by=Party.BUYER,
        tracking_uploaded_at=datetime(2026, 5, 2),
        cancelled_at=datetime(2026, 5, 2),
        provenance=PROV,
    )
    assert simultaneous.shipped_before_cancel is False


def test_canonical_models_are_immutable():
    raf = Charge(
        order_id="1",
        charge_type=ChargeType.REFUND_ADMINISTRATION_FEE,
        amount="-1.00",
        provenance=PROV,
    )
    with pytest.raises(Exception):
        raf.amount = Decimal("-2.00")  # frozen
