"""Coverage carry-forward — period-alignment notes, NOT findings.

Some cancellation orders are absent from settlement because they were cancelled
*after* the settlement files' latest statement date: their settlement simply hasn't
run yet. These are not "nothing to recover" — they are pending a future export. We
surface them as a queryable recheck list; they never enter the funnel or any finding.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class RecheckNote:
    order_id: str
    cancelled_at: datetime | None
    reason: str


def recheck_next_settlement(
    dataset, not_in_settlement, settlement_latest: date
) -> tuple[RecheckNote, ...]:
    """Orders absent from settlement whose cancellation post-dates the settlement window.

    (bucket "a" of the not-in-settlement analysis). Pure: a note, not a state change.
    """
    notes: list[RecheckNote] = []
    for oid in not_in_settlement:
        record = dataset.by_order.get(oid)
        event = record.cancellation if record else None
        cancelled_at = event.cancelled_at if event else None
        if cancelled_at is not None and cancelled_at.date() > settlement_latest:
            notes.append(RecheckNote(
                order_id=oid,
                cancelled_at=cancelled_at,
                reason="cancelled after latest settlement statement_date; pending a future export",
            ))
    return tuple(sorted(notes, key=lambda n: n.order_id))
