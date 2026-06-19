"""Normalization — raw inputs into canonical events/charges, plus entity resolution.

Step 1 ships the order-ID cleaner (the entity-resolution join key). The raw ->
canonical mappers are implemented in Step 2.
"""
from klemr.normalization.ids import clean_order_id

__all__ = ["clean_order_id"]
