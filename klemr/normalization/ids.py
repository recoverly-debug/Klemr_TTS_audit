"""Order-ID normalization for entity resolution.

The cancellation export's ``Order ID`` frequently carries trailing tabs and
zero-width characters; the settlement export does not. Both sides are cleaned with
this single function before the order-ID join, mirroring ``detect.clean_id``.
"""
from __future__ import annotations

_ZERO_WIDTH = "​"  # zero-width space


def clean_order_id(value: object) -> str:
    """Strip tabs, zero-width spaces, and surrounding whitespace from an order id."""
    return str(value).replace("\t", "").replace(_ZERO_WIDTH, "").strip()
