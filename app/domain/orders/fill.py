"""Normalized individual execution fill."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.domain.exceptions import OrderDataError
from app.domain.instruments.instrument import Instrument
from app.domain.orders.client_order_id import ClientOrderId


def _decimal(value: object, field: str, *, positive: bool = False) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field} must be Decimal")
    if not value.is_finite() or (positive and value <= 0):
        raise OrderDataError(f"{field} has an invalid Decimal value")


@dataclass(frozen=True, slots=True)
class Fill:
    fill_id: str
    price: Decimal
    quantity: Decimal
    fee: Decimal
    fee_asset: str
    executed_time: datetime

    def __post_init__(self) -> None:
        for field in ("fill_id", "fee_asset"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise OrderDataError(f"{field} must be a non-empty string")
        _decimal(self.price, "price", positive=True)
        _decimal(self.quantity, "quantity", positive=True)
        _decimal(self.fee, "fee")
        if not isinstance(self.executed_time, datetime):
            raise TypeError("executed_time must be datetime")
        if self.executed_time.tzinfo is None:
            raise OrderDataError("executed_time must be timezone-aware")

    @property
    def notional(self) -> Decimal:
        return self.price * self.quantity


@dataclass(frozen=True, slots=True)
class OrderFill:
    instrument: Instrument
    client_order_id: ClientOrderId
    exchange_order_id: str
    fill: Fill

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, Instrument):
            raise TypeError("instrument must be Instrument")
        if not isinstance(self.client_order_id, ClientOrderId):
            raise TypeError("client_order_id must be ClientOrderId")
        if not isinstance(self.exchange_order_id, str) or not self.exchange_order_id.strip():
            raise OrderDataError("exchange_order_id must be a non-empty string")
        if not isinstance(self.fill, Fill):
            raise TypeError("fill must be Fill")
