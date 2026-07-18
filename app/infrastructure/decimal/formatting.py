"""Exact decimal text used in exchange request payloads."""

from decimal import Decimal


def decimal_text(value: Decimal) -> str:
    if not isinstance(value, Decimal):
        raise TypeError("value must be Decimal")
    if not value.is_finite():
        raise ValueError("value must be finite")
    return format(value, "f")
