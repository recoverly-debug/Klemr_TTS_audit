"""Entity resolution — join cancellations <-> charges on cleaned order id.

The cleaned ``order_id`` (see :func:`klemr.normalization.ids.clean_order_id`) is the
join key. The result is the joined canonical set: one ``OrderRecord`` per order,
carrying its cancellation event (if any) and its charges (if any).
"""
from __future__ import annotations

from dataclasses import dataclass

from klemr.canonical.charges import Charge
from klemr.canonical.events import CancellationEvent


@dataclass(frozen=True)
class OrderRecord:
    """One order's joined canonical view."""

    order_id: str
    cancellation: CancellationEvent | None
    charges: tuple[Charge, ...] = ()


def resolve(
    events: list[CancellationEvent], charges: list[Charge]
) -> dict[str, OrderRecord]:
    """Join events and charges by order id into a deterministic ``order_id`` index."""
    charges_by_order: dict[str, list[Charge]] = {}
    for charge in charges:
        charges_by_order.setdefault(charge.order_id, []).append(charge)

    events_by_order: dict[str, CancellationEvent] = {e.order_id: e for e in events}

    by_order: dict[str, OrderRecord] = {}
    for oid in sorted(set(events_by_order) | set(charges_by_order)):
        by_order[oid] = OrderRecord(
            order_id=oid,
            cancellation=events_by_order.get(oid),
            charges=tuple(charges_by_order.get(oid, ())),
        )
    return by_order
