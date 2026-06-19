"""Ingestion — file intake (and, later, connector) seam.

Step 2 implements the file-intake path: settlement ``.xlsx`` + cancellation
``.csv``. OAuth / portal / email connectors are interface-only stubs for now.

The ``Connector`` protocol below is the seam those stubs (and the file uploader)
satisfy; no concrete connector is implemented in this slice beyond file intake.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Connector(Protocol):
    """Pulls raw source bytes/paths into the engine. Implemented in Step 2+."""

    #: Stable identifier, e.g. ``"file_upload"``, ``"oauth_settlement_api"``.
    name: str

    def fetch(self) -> object:  # pragma: no cover - interface only
        """Return raw inputs (paths/bytes/frames) for normalization."""
        ...


__all__ = ["Connector"]
