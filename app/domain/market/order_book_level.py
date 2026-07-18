"""One normalized order-book price level."""

from dataclasses import dataclass
from decimal import Decimal

from app.domain.exceptions import MarketDataError


@dataclass(frozen=True, slots=True)
class OrderBookLevel:
    price: Decimal
    quantity: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.price, Decimal):
            raise TypeError("price must be Decimal")
        if not isinstance(self.quantity, Decimal):
            raise TypeError("quantity must be Decimal")
        if not self.price.is_finite() or self.price <= 0:
            raise MarketDataError("price must be a positive finite Decimal")
        if not self.quantity.is_finite() or self.quantity < 0:
            raise MarketDataError("quantity must be a non-negative finite Decimal")
