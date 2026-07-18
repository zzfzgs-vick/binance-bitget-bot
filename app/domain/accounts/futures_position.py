"""Normalized USDT perpetual position state."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from app.domain.enums import MarketType
from app.domain.exceptions import AccountDataError
from app.domain.instruments.instrument import Instrument


class PositionSide(str, Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


class PositionMode(str, Enum):
    ONE_WAY = "one_way"
    HEDGE = "hedge"


class MarginMode(str, Enum):
    CROSS = "cross"
    ISOLATED = "isolated"


def _value(value: Decimal, field: str, *, signed: bool = False) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field} must be Decimal")
    if not value.is_finite() or (not signed and value < 0):
        raise AccountDataError(f"{field} has an invalid Decimal value")


@dataclass(frozen=True, slots=True)
class FuturesPosition:
    instrument: Instrument
    quantity: Decimal
    side: PositionSide
    mode: PositionMode
    average_open_price: Decimal
    unrealized_pnl: Decimal
    margin_mode: MarginMode
    updated_time: datetime | None = None

    def __post_init__(self) -> None:
        if self.instrument.market_type is not MarketType.USDT_PERPETUAL:
            raise AccountDataError("futures position requires a USDT perpetual")
        if not isinstance(self.side, PositionSide):
            raise TypeError("side must be PositionSide")
        if not isinstance(self.mode, PositionMode):
            raise TypeError("mode must be PositionMode")
        if not isinstance(self.margin_mode, MarginMode):
            raise TypeError("margin_mode must be MarginMode")
        _value(self.quantity, "quantity")
        _value(self.average_open_price, "average_open_price")
        _value(self.unrealized_pnl, "unrealized_pnl", signed=True)
        if self.quantity > 0 and self.side is PositionSide.FLAT:
            raise AccountDataError("FLAT position must have zero quantity")
        if self.quantity > 0 and self.average_open_price <= 0:
            raise AccountDataError("open position requires average_open_price")
        if self.updated_time is not None and self.updated_time.tzinfo is None:
            raise AccountDataError("updated_time must be timezone-aware")

    @property
    def is_empty(self) -> bool:
        return self.quantity == 0
