"""Financial result of a two-leg arbitrage calculation."""

from dataclasses import dataclass
from decimal import Decimal

from app.domain.exceptions import ArbitrageCalculationError


@dataclass(frozen=True, slots=True)
class Profitability:
    gross_profit: Decimal
    total_fee: Decimal
    slippage_cost: Decimal
    net_profit: Decimal
    roi: Decimal

    def __post_init__(self) -> None:
        for field in (
            "gross_profit",
            "total_fee",
            "slippage_cost",
            "net_profit",
            "roi",
        ):
            value = getattr(self, field)
            if not isinstance(value, Decimal):
                raise TypeError(f"{field} must be Decimal")
            if not value.is_finite():
                raise ArbitrageCalculationError(f"{field} must be finite")
        if self.total_fee < 0:
            raise ArbitrageCalculationError("total_fee cannot be negative")
        if self.slippage_cost < 0:
            raise ArbitrageCalculationError("slippage_cost cannot be negative")
