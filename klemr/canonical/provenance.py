"""Provenance — where a canonical record came from.

Every canonical record (event, charge) and, later, every finding carries a
``Provenance`` so the whole audit is reproducible from inputs and auditable back
to specific source rows. Timestamps are never fabricated: ``ingested_at`` is set
only by a real ingestion run, and is ``None`` until then.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SourceRef(BaseModel):
    """A pointer back to the raw input rows that produced a canonical record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_file: str
    sheet: str | None = None
    # Row indices within the source file/sheet. SKU-level rows collapsed to an
    # order may reference several rows; hence a tuple.
    row_indices: tuple[int, ...] = ()
    # SHA-256 of the source file's raw bytes, so "same inputs -> identical output"
    # is verifiable: the hash rides every record derived from the file.
    content_sha256: str | None = None


class Provenance(BaseModel):
    """The set of sources behind one canonical record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sources: tuple[SourceRef, ...] = Field(default_factory=tuple)
    # Set by the ingestion lane from the actual run clock; never invented.
    ingested_at: datetime | None = None
