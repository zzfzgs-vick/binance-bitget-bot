"""Normalized order request and order state."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from app.domain.enums import MarketType
from app.domain.exceptions import OrderDataError
from app.domain.instruments.instrument import Instrument
from app.domain.orders.client_order_id import ClientOrderId
from app.domain.orders.fill import Fill


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    LIMIT = "limit"
    MARKET = "market"


class TimeInForce(str, Enum):
    GTC = "gtc"
    IOC = "ioc"
    FOK = "fok"


class FuturesPositionSide(str, Enum):
    BOTH = "both"
    LONG = "long"
    SHORT = "short"


class OrderStatus(str, Enum):
    SUBMITTED = "submitted"
    NEW = "new"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    UNKNOWN = "unknown"

    @property
    def is_terminal(self) -> bool:
        return self in {
            OrderStatus.FILLED,
            OrderStatus.CANCELED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        }


def _positive(value: object, field: str) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field} must be Decimal")
    if not value.is_finite() or value <= 0:
        raise OrderDataError(f"{field} must be a positive finite Decimal")


def _non_negative(value: object, field: str) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field} must be Decimal")
    if not value.is_finite() or value < 0:
        raise OrderDataError(f"{field} must be a non-negative finite Decimal")


@dataclass(frozen=True, slots=True)
class OrderRequest:
    instrument: Instrument
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    client_order_id: ClientOrderId
    price: Decimal | None = None
    reference_price: Decimal | None = None
    time_in_force: TimeInForce = TimeInForce.GTC
    position_side: FuturesPositionSide | None = None
    reduce_only: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, Instrument):
            raise TypeError("instrument must be Instrument")
        if not isinstance(self.side, OrderSide):
            raise TypeError("side must be OrderSide")
        if not isinstance(self.order_type, OrderType):
            raise TypeError("order_type must be OrderType")
        if not isinstance(self.client_order_id, ClientOrderId):
            raise TypeError("client_order_id must be ClientOrderId")
        if not isinstance(self.time_in_force, TimeInForce):
            raise TypeError("time_in_force must be TimeInForce")
        if self.position_side is not None and not isinstance(
            self.position_side, FuturesPositionSide
        ):
            raise TypeError("position_side must be FuturesPositionSide")
        if not isinstance(self.reduce_only, bool):
            raise TypeError("reduce_only must be bool")
        _positive(self.quantity, "quantity")
        if self.order_type is OrderType.LIMIT:
            if self.price is None:
                raise OrderDataError("limit order requires price")
            _positive(self.price, "price")
        elif self.price is not None:
            raise OrderDataError("market order must not contain price")
        if self.reference_price is not None:
            _positive(self.reference_price, "reference_price")
        if (
            self.instrument.market_type is MarketType.SPOT
            and self.position_side is not None
        ):
            raise OrderDataError("position_side is only valid for futures orders")
        if self.instrument.market_type is MarketType.SPOT and self.reduce_only:
            raise OrderDataError("reduce_only is only valid for futures orders")


@dataclass(frozen=True, slots=True)
class Order:
    instrument: Instrument
    client_order_id: ClientOrderId
    exchange_order_id: str
    side: OrderSide
    order_type: OrderType
    time_in_force: TimeInForce
    original_quantity: Decimal
    price: Decimal | None
    status: OrderStatus
    cumulative_filled_quantity: Decimal
    average_price: Decimal
    cumulative_fee: Decimal
    fee_asset: str | None
    fills: tuple[Fill, ...]
    updated_time: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, Instrument):
            raise TypeError("instrument must be Instrument")
        if not isinstance(self.client_order_id, ClientOrderId):
            raise TypeError("client_order_id must be ClientOrderId")
        if not isinstance(self.exchange_order_id, str) or not self.exchange_order_id.strip():
            raise OrderDataError("exchange_order_id must be a non-empty string")
        for field, expected in (
            ("side", OrderSide),
            ("order_type", OrderType),
            ("time_in_force", TimeInForce),
            ("status", OrderStatus),
        ):
            if not isinstance(getattr(self, field), expected):
                raise TypeError(f"{field} must be {expected.__name__}")
        _positive(self.original_quantity, "original_quantity")
        if self.price is not None:
            _positive(self.price, "price")
        _non_negative(self.cumulative_filled_quantity, "cumulative_filled_quantity")
        _non_negative(self.average_price, "average_price")
        if not isinstance(self.cumulative_fee, Decimal):
            raise TypeError("cumulative_fee must be Decimal")
        if not self.cumulative_fee.is_finite():
            raise OrderDataError("cumulative_fee must be finite")
        if (
            self.order_type is OrderType.LIMIT
            and self.cumulative_filled_quantity > self.original_quantity
        ):
            raise OrderDataError("cumulative fill exceeds original_quantity")
        if self.cumulative_filled_quantity == 0 and self.average_price != 0:
            raise OrderDataError("unfilled order must have zero average_price")
        if self.cumulative_filled_quantity > 0 and self.average_price <= 0:
            raise OrderDataError("filled order requires positive average_price")
        if self.status is OrderStatus.FILLED and self.cumulative_filled_quantity <= 0:
            raise OrderDataError("FILLED order requires a positive fill quantity")
        if (
            self.status is OrderStatus.FILLED
            and self.order_type is OrderType.LIMIT
            and self.cumulative_filled_quantity != self.original_quantity
        ):
            raise OrderDataError("FILLED order must fill original_quantity")
        if self.status is OrderStatus.PARTIALLY_FILLED and (
            self.cumulative_filled_quantity <= 0
            or (
                self.order_type is OrderType.LIMIT
                and self.cumulative_filled_quantity >= self.original_quantity
            )
        ):
            raise OrderDataError("PARTIALLY_FILLED order requires a partial quantity")
        if self.fee_asset is not None and (
            not isinstance(self.fee_asset, str) or not self.fee_asset.strip()
        ):
            raise OrderDataError("fee_asset must be a non-empty string")
        if self.cumulative_fee != 0 and self.fee_asset is None:
            raise OrderDataError("non-zero cumulative_fee requires fee_asset")
        if not isinstance(self.fills, tuple) or not all(
            isinstance(fill, Fill) for fill in self.fills
        ):
            raise TypeError("fills must be a tuple of Fill")
        if len({fill.fill_id for fill in self.fills}) != len(self.fills):
            raise OrderDataError("fills contain duplicate fill_id values")
        if sum((fill.quantity for fill in self.fills), Decimal(0)) > self.cumulative_filled_quantity:
            raise OrderDataError("fill details exceed cumulative_filled_quantity")
        fill_assets = {fill.fee_asset for fill in self.fills}
        if len(fill_assets) > 1:
            raise OrderDataError("fills use incompatible fee assets")
        if fill_assets and self.fee_asset not in fill_assets:
            raise OrderDataError("fee_asset does not match fills")
        if not isinstance(self.updated_time, datetime):
            raise TypeError("updated_time must be datetime")
        if self.updated_time.tzinfo is None:
            raise OrderDataError("updated_time must be timezone-aware")

    @property
    def is_terminal(self) -> bool:
        return self.status.is_terminal

    @property
    def filled_base_quantity(self) -> Decimal:
        return (
            self.cumulative_filled_quantity
            * self.instrument.rules.contract_multiplier
        )
