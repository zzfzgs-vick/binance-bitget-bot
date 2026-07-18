"""Normalized trading instrument and trading rules."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from math import lcm

from app.domain.enums import Exchange, MarketType, TradingStatus
from app.domain.exceptions import InstrumentDataError, TradingRuleError


def _positive_decimal(
    value: Decimal,
    field: str,
    error_type: type[ValueError] = InstrumentDataError,
) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field} must be Decimal")
    if not value.is_finite() or value <= 0:
        raise error_type(f"{field} must be a positive finite Decimal")


def _round_to_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def _decimal_lcm(left: Decimal, right: Decimal) -> Decimal:
    exponent = min(left.as_tuple().exponent, right.as_tuple().exponent, 0)
    scale = Decimal(10) ** -exponent
    return Decimal(lcm(int(left * scale), int(right * scale))) / scale


@dataclass(frozen=True, slots=True)
class TradingRules:
    tick_size: Decimal
    quantity_step: Decimal
    minimum_quantity: Decimal
    maximum_quantity: Decimal | None
    minimum_notional: Decimal
    contract_multiplier: Decimal

    def __post_init__(self) -> None:
        for field in (
            "tick_size",
            "quantity_step",
            "minimum_quantity",
            "minimum_notional",
            "contract_multiplier",
        ):
            _positive_decimal(getattr(self, field), field)
        if self.maximum_quantity is not None:
            _positive_decimal(self.maximum_quantity, "maximum_quantity")
            if self.maximum_quantity < self.minimum_quantity:
                raise InstrumentDataError(
                    "maximum_quantity cannot be less than minimum_quantity"
                )

    def normalize_order(
        self, price: Decimal, quantity: Decimal
    ) -> tuple[Decimal, Decimal]:
        _positive_decimal(price, "price", TradingRuleError)
        _positive_decimal(quantity, "quantity", TradingRuleError)
        normalized_price = _round_to_step(price, self.tick_size)
        normalized_quantity = _round_to_step(quantity, self.quantity_step)
        self._validate_values(normalized_price, normalized_quantity)
        return normalized_price, normalized_quantity

    def validate_execution(
        self, average_price: Decimal, quantity: Decimal
    ) -> None:
        """Validate an exact filled quantity and its volume-weighted price."""
        _positive_decimal(average_price, "average_price", TradingRuleError)
        _positive_decimal(quantity, "quantity", TradingRuleError)
        if _round_to_step(quantity, self.quantity_step) != quantity:
            raise TradingRuleError("quantity does not match quantity_step")
        self._validate_values(average_price, quantity)

    def normalize_common_base_quantity(
        self,
        other: "TradingRules",
        requested: Decimal,
    ) -> Decimal:
        """Round a base quantity down to a step executable by both rules."""
        if not isinstance(other, TradingRules):
            raise TypeError("other must be TradingRules")
        _positive_decimal(requested, "requested", TradingRuleError)
        common_step = _decimal_lcm(
            self.quantity_step * self.contract_multiplier,
            other.quantity_step * other.contract_multiplier,
        )
        quantity = _round_to_step(requested, common_step)
        if quantity <= 0:
            raise TradingRuleError("quantity rounds down to zero")
        return quantity

    def _validate_values(self, price: Decimal, quantity: Decimal) -> None:
        if quantity < self.minimum_quantity:
            raise TradingRuleError("quantity is below minimum_quantity")
        if (
            self.maximum_quantity is not None
            and quantity > self.maximum_quantity
        ):
            raise TradingRuleError("quantity exceeds maximum_quantity")
        notional = price * quantity * self.contract_multiplier
        if notional < self.minimum_notional:
            raise TradingRuleError("order notional is below minimum_notional")


@dataclass(frozen=True, slots=True)
class Instrument:
    exchange: Exchange
    market_type: MarketType
    raw_symbol: str
    base_asset: str
    quote_asset: str
    settlement_asset: str
    rules: TradingRules
    status: TradingStatus
    raw_status: str

    def __post_init__(self) -> None:
        for field in (
            "raw_symbol",
            "base_asset",
            "quote_asset",
            "settlement_asset",
            "raw_status",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise InstrumentDataError(f"{field} must be a non-empty string")
