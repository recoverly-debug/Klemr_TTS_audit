"""TikTok-specific normalization: raw export rows -> canonical models.

This layer turns the adapter's raw TikTok strings into typed canonical models. It
absorbs TikTok's value quirks (trailing tabs on ids/timestamps, ``MM/DD/YYYY`` vs
``YYYY/MM/DD`` formats, ``Cancel By = User`` meaning the buyer) so that none of them
reach the canonical field names or values. When a second marketplace arrives, it
gets its own ``normalization/<channel>.py``; the canonical models do not change.

Normalization failures are collected as :class:`NormalizationIssue` and surfaced —
never silently dropped.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from klemr.canonical.charges import Charge, ChargeType
from klemr.canonical.events import CancellationEvent, Party
from klemr.canonical.money import to_money
from klemr.canonical.provenance import Provenance, SourceRef
from klemr.ingestion.tiktok_files import RawExport, RawTable
from klemr.normalization.ids import clean_order_id

# TikTok's cancel-party vocabulary -> canonical Party. "User" is the buyer.
_PARTY_MAP = {
    "user": Party.BUYER,
    "system": Party.SYSTEM,
    "seller": Party.SELLER,
    "operator": Party.OPERATOR,
}

_TS_FORMAT = "%m/%d/%Y %I:%M:%S %p"  # e.g. "06/16/2026 7:54:44 PM"
_DATE_FORMAT = "%Y/%m/%d"  # e.g. "2026/03/31"
_ZERO_WIDTH = "​"


@dataclass(frozen=True)
class NormalizationIssue:
    """A raw row/value that could not be normalized. Reported, not dropped."""

    source_file: str
    order_id: str
    field: str
    raw_value: str
    detail: str


def _clean_cell(value: object) -> str:
    return str(value).replace("\t", "").replace(_ZERO_WIDTH, "").strip()


def _is_blank(value: object) -> bool:
    return _clean_cell(value).lower() in ("", "nan", "none")


def _party(raw: str) -> Party:
    return _PARTY_MAP.get(_clean_cell(raw).lower(), Party.OTHER)


def _first_nonblank(values) -> str:
    """Collapse SKU-level rows: first non-blank (cleaned) value, else ''."""
    for v in values:
        if not _is_blank(v):
            return _clean_cell(v)
    return ""


def _parse_dt(raw: str) -> datetime | None:
    cleaned = _clean_cell(raw)
    if cleaned.lower() in ("", "nan", "none"):
        return None
    return datetime.strptime(cleaned, _TS_FORMAT)


def _parse_date(raw: str) -> date | None:
    cleaned = _clean_cell(raw)
    if cleaned.lower() in ("", "nan", "none"):
        return None
    return datetime.strptime(cleaned, _DATE_FORMAT).date()


def normalize_cancellations(
    export: RawExport, *, ingested_at: datetime | None = None
) -> tuple[list[CancellationEvent], list[NormalizationIssue]]:
    """Collapse SKU-level cancellation rows to one ``CancellationEvent`` per order.

    Marketplace-scoped note: for TikTok, the dispatch anchor is ``RTS Time`` and the
    buyer is ``Cancel By = User``; ``shipped_before_cancel`` is then DERIVED on the
    canonical event from ``tracking_uploaded_at`` and ``cancelled_at`` (strict ``<``)
    — it is never read from a column. A second marketplace that defines "shipped"
    differently would map its own anchor here, in its channel normalizer; the
    canonical derivation stays put. (Do not build for that now.)
    """
    table = export.cancellations
    cols = table.columns
    frame = table.frame
    src = table.source
    issues: list[NormalizationIssue] = []

    has_rts = "rts_time" in cols
    has_when = "cancelled_time" in cols
    has_reason = "reason" in cols

    # Group raw row positions by cleaned order id (entity-resolution key).
    order_rows: dict[str, list[int]] = {}
    cleaned_ids = frame[cols["order_id"]].map(clean_order_id)
    for row_idx, oid in zip(frame.index, cleaned_ids):
        order_rows.setdefault(oid, []).append(int(row_idx))

    events: list[CancellationEvent] = []
    for oid, rows in order_rows.items():
        sub = frame.loc[rows]
        by_raw = _first_nonblank(sub[cols["cancel_by"]])
        rts_raw = _first_nonblank(sub[cols["rts_time"]]) if has_rts else ""
        when_raw = _first_nonblank(sub[cols["cancelled_time"]]) if has_when else ""
        reason = _first_nonblank(sub[cols["reason"]]) if has_reason else ""

        try:
            tracking_uploaded_at = _parse_dt(rts_raw)
        except ValueError:
            tracking_uploaded_at = None
            issues.append(NormalizationIssue(src.basename, oid, "rts_time", rts_raw,
                                             "unparseable RTS timestamp"))
        try:
            cancelled_at = _parse_dt(when_raw)
        except ValueError:
            cancelled_at = None
            issues.append(NormalizationIssue(src.basename, oid, "cancelled_time", when_raw,
                                             "unparseable cancelled timestamp"))

        provenance = Provenance(
            sources=(
                SourceRef(
                    source_file=src.basename,
                    sheet=src.sheet,
                    row_indices=tuple(rows),
                    content_sha256=src.content_sha256,
                ),
            ),
            ingested_at=ingested_at,
        )
        events.append(
            CancellationEvent(
                order_id=oid,
                initiated_by=_party(by_raw),
                initiated_by_raw=by_raw,
                tracking_uploaded_at=tracking_uploaded_at,
                cancelled_at=cancelled_at,
                reason=reason or None,
                provenance=provenance,
            )
        )
    return events, issues


# Settlement money column -> canonical charge type.
_CHARGE_TYPES = {
    "raf": ChargeType.REFUND_ADMINISTRATION_FEE,
    "referral": ChargeType.REFERRAL_FEE,
}


def normalize_charges(
    export: RawExport,
    *,
    restrict_to_orders: set[str] | None = None,
    ingested_at: datetime | None = None,
) -> tuple[list[Charge], list[NormalizationIssue]]:
    """Emit canonical ``Charge`` rows from settlement.

    A money cell becomes a Charge only when it is a present, non-zero number — a
    blank or $0.00 line is not a charge, so we never fabricate one. ``restrict_to_orders``
    scopes emission to the entity-resolution domain (the cancellation universe);
    settlement lines for unrelated orders are out of this join and not materialized.
    """
    charges: list[Charge] = []
    issues: list[NormalizationIssue] = []

    for table in export.settlements:
        charges_from, table_issues = _charges_from_table(
            table, restrict_to_orders, ingested_at
        )
        charges.extend(charges_from)
        issues.extend(table_issues)
    return charges, issues


def _to_decimal_or_none(raw: object) -> Decimal | None:
    cleaned = _clean_cell(raw)
    if cleaned.lower() in ("", "nan", "none"):
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _charges_from_table(
    table: RawTable, restrict: set[str] | None, ingested_at: datetime | None
) -> tuple[list[Charge], list[NormalizationIssue]]:
    cols = table.columns
    frame = table.frame
    src = table.source
    charges: list[Charge] = []
    issues: list[NormalizationIssue] = []

    money_keys = [k for k in ("raf", "referral") if k in cols]
    has_sku = "sku_id" in cols
    has_date = "statement_date" in cols

    # Clean ids vectorized, then iterate only the in-domain rows (the join scope).
    oids = frame[cols["order_id"]].map(clean_order_id)
    if restrict is not None:
        row_index = list(frame.index[oids.isin(restrict)])
    else:
        row_index = list(frame.index)

    for row_idx in row_index:
        row = frame.loc[row_idx]
        oid = oids.loc[row_idx]

        sku_id = _clean_cell(row[cols["sku_id"]]) if has_sku else None
        sku_id = sku_id or None
        statement_date: date | None = None
        if has_date:
            raw_date = row[cols["statement_date"]]
            try:
                statement_date = _parse_date(raw_date)
            except ValueError:
                issues.append(NormalizationIssue(src.basename, oid, "statement_date",
                                                 _clean_cell(raw_date), "unparseable date"))

        provenance = Provenance(
            sources=(
                SourceRef(
                    source_file=src.basename,
                    sheet=src.sheet,
                    row_indices=(int(row_idx),),
                    content_sha256=src.content_sha256,
                ),
            ),
            ingested_at=ingested_at,
        )
        for key in money_keys:
            value = _to_decimal_or_none(row[cols[key]])
            if value is None or value == 0:
                continue  # blank / $0.00 is not a charge
            charges.append(
                Charge(
                    order_id=oid,
                    charge_type=_CHARGE_TYPES[key],
                    amount=to_money(value),
                    sku_id=sku_id,
                    statement_date=statement_date,
                    provenance=provenance,
                )
            )
    return charges, issues
