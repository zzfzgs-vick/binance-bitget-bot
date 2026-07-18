"""One calculated side of a two-leg arbitrage route."""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from app.domain.exceptions import ArbitrageCalculationError
from app.domain.instruments.instrument import Instrument


class LegSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True, slots=True)
class ArbitrageLeg:
    instrument: Instrument
    side: LegSide
    order_quantity: Decimal
    base_quantity: Decimal
    average_price: Decimal
    notional: Decimal
    fee_rate: Decimal
    fee: Decimal
    slippage: Decimal

    def __post_init__(self) -> None:
        for field in (
            "order_quantity",
            "base_quantity",
            "average_price",
            "notional",
        ):
            value = getattr(self, field)
            _decimal(value, field)
            if value <= 0:
                raise ArbitrageCalculationError(f"{field} must be positive")
        for field in ("fee_rate", "fee", "slippage"):
            value = getattr(self, field)
            _decimal(value, field)
            if value < 0:
                raise ArbitrageCalculationError(f"{field} cannot be negative")
        if self.fee != self.notional * self.fee_rate:
            raise ArbitrageCalculationError(
                "fee must equal notional multiplied by fee_rate"
            )
        if (
            self.base_quantity
            != self.order_quantity * self.instrument.rules.contract_multiplier
        ):
            raise ArbitrageCalculationError(
                "base_quantity must equal order_quantity times contract_multiplier"
            )
        if self.average_price != self.notional / self.base_quantity:
            raise ArbitrageCalculationError(
                "average_price must equal notional divided by base_quantity"
            )


def _decimal(value: object, field: str) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field} must be Decimal")
    if not value.is_finite():
        raise ArbitrageCalculationError(f"{field} must be finite")
