"""TikTok Shop file adapter — the first concrete ``Connector``.

This module is the ONLY place that knows TikTok's file shapes: the "income"
settlement ``.xlsx`` (sheet "Order details") and the "Canceled_order" ``.csv``. It
resolves TikTok's drifting column names by fuzzy alias match, computes a SHA-256 of
each source file's bytes, and returns the raw rows untouched (still strings, tabs
and all). It produces NO canonical models and embeds NO policy — quirk-cleaning and
typing happen one layer up, in ``klemr.normalization.tiktok``.

Requires the ``ingest`` optional dependency group (pandas + openpyxl).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


def _norm(s: object) -> str:
    """Case/space/punct-insensitive column key (matches reference detect.py)."""
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


def _find_col(columns, *aliases: str, required: bool = True, label: str | None = None):
    """Resolve a TikTok column by fuzzy alias (exact-normalized, then substring)."""
    norm = {_norm(c): c for c in columns}
    for alias in aliases:
        na = _norm(alias)
        if na in norm:
            return norm[na]
        for key, original in norm.items():
            if na and na in key:
                return original
    if required:
        raise KeyError(
            f"[tiktok adapter] could not find a column for {label or aliases[0]!r}. "
            f"Available: {list(columns)}"
        )
    return None


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


# Semantic key -> TikTok column aliases. The rest of the engine speaks the semantic
# keys; the actual TikTok header text never escapes this module.
_CANCEL_COLUMNS = {
    "order_id": ("Order ID", "Order/adjustment ID"),
    "cancel_by": ("Cancel By", "Canceled By", "Cancellation By"),
    "rts_time": ("RTS Time", "Ready to Ship Time"),
    "cancelled_time": ("Cancelled Time", "Canceled Time", "Cancellation Time"),
    "reason": ("Cancel Reason", "Cancellation Reason", "Reason"),
    "sku_id": ("SKU ID", "Seller SKU"),
}
_CANCEL_OPTIONAL = {"rts_time", "cancelled_time", "reason", "sku_id"}

_SETTLE_SHEET_ALIASES = ("Order details",)
_SETTLE_COLUMNS = {
    "order_id": ("Order/adjustment ID", "Order ID", "Order adjustment ID"),
    "raf": ("Refund administration fee", "Refund admin fee", "RAF"),
    "referral": ("Referral fee",),
    "statement_date": ("Statement date", "Settlement date", "Order settled time"),
    "sku_id": ("SKU ID", "Seller SKU"),
}
_SETTLE_OPTIONAL = {"referral", "statement_date", "sku_id"}


@dataclass(frozen=True)
class SourceFile:
    """Immutable identity + content hash of one ingested file."""

    path: str
    basename: str
    kind: str  # "cancellation" | "settlement"
    sheet: str | None
    content_sha256: str


@dataclass(frozen=True)
class RawTable:
    """Raw rows from one source, plus the resolved semantic->actual column map."""

    source: SourceFile
    frame: pd.DataFrame
    columns: dict[str, str]


@dataclass(frozen=True)
class RawExport:
    """Everything one ingestion run pulled in (raw, pre-normalization)."""

    cancellations: RawTable
    settlements: tuple[RawTable, ...]

    @property
    def sources(self) -> tuple[SourceFile, ...]:
        return (self.cancellations.source, *(s.source for s in self.settlements))


def _resolve_columns(columns, spec, optional) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for key, aliases in spec.items():
        col = _find_col(columns, *aliases, required=key not in optional, label=key)
        if col is not None:
            resolved[key] = col
    return resolved


class TikTokFileConnector:
    """A ``Connector`` that reads TikTok settlement + cancellation export files."""

    name = "tiktok_file_upload"

    def __init__(self, settlement_paths, cancellation_path) -> None:
        self._settlement_paths = [Path(p) for p in settlement_paths]
        self._cancellation_path = Path(cancellation_path)

    def fetch(self) -> RawExport:
        cancellations = self._load_cancellations(self._cancellation_path)
        settlements = tuple(self._load_settlement(p) for p in self._settlement_paths)
        return RawExport(cancellations=cancellations, settlements=settlements)

    def _load_cancellations(self, path: Path) -> RawTable:
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
        frame.columns = [str(c).strip() for c in frame.columns]
        frame = frame.reset_index(drop=True)
        source = SourceFile(
            path=str(path),
            basename=path.name,
            kind="cancellation",
            sheet=None,
            content_sha256=_sha256_file(path),
        )
        columns = _resolve_columns(frame.columns, _CANCEL_COLUMNS, _CANCEL_OPTIONAL)
        return RawTable(source=source, frame=frame, columns=columns)

    def _load_settlement(self, path: Path) -> RawTable:
        xl = pd.ExcelFile(path)
        sheet = next(
            (s for s in xl.sheet_names if _norm(s) in {_norm(a) for a in _SETTLE_SHEET_ALIASES}),
            None,
        )
        if sheet is None:
            sheet = next((s for s in xl.sheet_names if "order" in _norm(s)), xl.sheet_names[0])
        frame = xl.parse(sheet, dtype=str).reset_index(drop=True)
        source = SourceFile(
            path=str(path),
            basename=path.name,
            kind="settlement",
            sheet=sheet,
            content_sha256=_sha256_file(path),
        )
        columns = _resolve_columns(frame.columns, _SETTLE_COLUMNS, _SETTLE_OPTIONAL)
        return RawTable(source=source, frame=frame, columns=columns)
