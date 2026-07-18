"""Calculated two-leg arbitrage opportunity."""

from dataclasses import dataclass
from decimal import Decimal

from app.domain.arbitrage.arbitrage_route import ArbitrageLeg, LegSide
from app.domain.arbitrage.profitability import Profitability
from app.domain.exceptions import ArbitrageCalculationError, InstrumentMatchError
from app.domain.instruments.trading_pair import match_instruments


@dataclass(frozen=True, slots=True)
class ArbitrageOpportunity:
    buy_leg: ArbitrageLeg
    sell_leg: ArbitrageLeg
    quantity: Decimal
    profitability: Profitability

    def __post_init__(self) -> None:
        if not isinstance(self.quantity, Decimal):
            raise TypeError("quantity must be Decimal")
        if not self.quantity.is_finite() or self.quantity <= 0:
            raise ArbitrageCalculationError("quantity must be positive and finite")
        if self.buy_leg.side is not LegSide.BUY:
            raise ArbitrageCalculationError("buy_leg must have BUY side")
        if self.sell_leg.side is not LegSide.SELL:
            raise ArbitrageCalculationError("sell_leg must have SELL side")
        if (
            self.buy_leg.base_quantity != self.quantity
            or self.sell_leg.base_quantity != self.quantity
        ):
            raise ArbitrageCalculationError(
                "both legs must use the opportunity quantity"
            )
        try:
            match_instruments(
                self.buy_leg.instrument,
                self.sell_leg.instrument,
            )
        except InstrumentMatchError as exc:
            raise ArbitrageCalculationError(str(exc)) from None
        gross_profit = self.sell_leg.notional - self.buy_leg.notional
        total_fee = self.buy_leg.fee + self.sell_leg.fee
        slippage = self.buy_leg.slippage + self.sell_leg.slippage
        net_profit = gross_profit - total_fee
        expected = Profitability(
            gross_profit=gross_profit,
            total_fee=total_fee,
            slippage_cost=slippage,
            net_profit=net_profit,
            roi=net_profit / self.buy_leg.notional,
        )
        if self.profitability != expected:
            raise ArbitrageCalculationError(
                "profitability does not match the opportunity legs"
            )

    @property
    def direction(self) -> str:
        return (
            f"{self.buy_leg.instrument.exchange.value}_buy_"
            f"{self.sell_leg.instrument.exchange.value}_sell"
        )

    @property
    def gross_profit(self) -> Decimal:
        return self.profitability.gross_profit

    @property
    def total_fee(self) -> Decimal:
        return self.profitability.total_fee

    @property
    def slippage_cost(self) -> Decimal:
        return self.profitability.slippage_cost

    @property
    def net_profit(self) -> Decimal:
        return self.profitability.net_profit

    @property
    def roi(self) -> Decimal:
        return self.profitability.roi
