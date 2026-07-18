"""Central order-rule normalization before any exchange submission."""

from dataclasses import replace

from app.domain.enums import TradingStatus
from app.domain.exceptions import TradingRuleError
from app.domain.orders.order import OrderRequest, OrderType


def prepare_order(request: OrderRequest) -> OrderRequest:
    if not isinstance(request, OrderRequest):
        raise TypeError("request must be OrderRequest")
    if request.instrument.status is not TradingStatus.TRADING:
        raise TradingRuleError("instrument is not tradable")
    validation_price = (
        request.price
        if request.order_type is OrderType.LIMIT
        else request.reference_price
    )
    if validation_price is None:
        raise TradingRuleError(
            "market order requires reference_price for minimum rule validation"
        )
    normalized_price, normalized_quantity = (
        request.instrument.rules.normalize_order(
            validation_price,
            request.quantity,
        )
    )
    return replace(
        request,
        quantity=normalized_quantity,
        price=(normalized_price if request.order_type is OrderType.LIMIT else None),
        reference_price=(
            normalized_price if request.order_type is OrderType.MARKET else None
        ),
    )
