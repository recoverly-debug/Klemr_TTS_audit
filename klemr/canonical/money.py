"""Money primitives.

The reference scripts use floats and round to 2 dp at the end. We use ``Decimal``
throughout the canonical layer so that totals recomputed from rows are exact to the
cent — this protects the "math decides" invariant (a $0.50 float-drift error crept
into the first Haus run exactly because of running float sums).

Settlement amounts are stored **signed** as TikTok exports them: a fee/deduction is
*negative*. We never flip the sign at rest; magnitude is derived on demand.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

CENTS = Decimal("0.01")


def to_money(value: object) -> Decimal:
    """Coerce a raw value to a cent-quantized ``Decimal``.

    Accepts ``Decimal``, ``int``, ``float`` or numeric ``str``. Floats are routed
    through ``str()`` first so that e.g. ``0.1 + 0.2`` artefacts never enter the
    ledger. Quantization is HALF_UP to match how settlement figures are displayed.
    """
    if isinstance(value, Decimal):
        d = value
    else:
        d = Decimal(str(value))
    return d.quantize(CENTS, rounding=ROUND_HALF_UP)
