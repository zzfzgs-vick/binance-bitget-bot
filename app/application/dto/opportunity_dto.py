"""GUI-facing executable opportunity plan with explicit leg ordering."""

from dataclasses import dataclass

from app.domain.arbitrage.arbitrage_opportunity import ArbitrageOpportunity
from app.domain.exceptions import OrderDataError
from app.domain.orders.order import OrderRequest, OrderSide


@dataclass(frozen=True, slots=True)
class ExecutableOpportunity:
    position_id: str
    opportunity: ArbitrageOpportunity
    first_request: OrderRequest
    second_request: OrderRequest

    def __post_init__(self) -> None:
        if not isinstance(self.position_id, str) or not self.position_id.strip():
            raise OrderDataError("position_id must be a non-empty string")
        if not isinstance(self.opportunity, ArbitrageOpportunity):
            raise TypeError("opportunity must be ArbitrageOpportunity")
        if not isinstance(self.first_request, OrderRequest) or not isinstance(
            self.second_request, OrderRequest
        ):
            raise TypeError("execution requests must be OrderRequest")
        requests = (self.first_request, self.second_request)
        expected = {
            (self.opportunity.buy_leg.instrument, OrderSide.BUY),
            (self.opportunity.sell_leg.instrument, OrderSide.SELL),
        }
        actual = {(request.instrument, request.side) for request in requests}
        if actual != expected:
            raise OrderDataError("execution requests do not match opportunity legs")
        quantities = {
            request.quantity * request.instrument.rules.contract_multiplier
            for request in requests
        }
        if quantities != {self.opportunity.quantity}:
            raise OrderDataError("execution requests do not match opportunity quantity")
