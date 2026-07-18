"""Sequential two-leg submission without compensation or position management."""

from decimal import Decimal

from app.domain.exceptions import OrderDataError, TradingRuleError
from app.domain.orders.order import OrderRequest, OrderStatus
from app.domain.orders.order_group import DualLegExecutionResult, DualLegStatus
from app.domain.orders.order_leg import (
    LegRole,
    failed_leg,
    successful_leg,
)
from app.exchanges.base.trading_client import TradingClient
from app.exchanges.base.exchange_errors import ExchangeRestError
from app.execution.order_recovery_service import (
    DuplicateOrderSubmissionError,
    IdempotentOrderService,
    OrderStateUnknownError,
)
from app.execution.preflight_validator import prepare_order


class DualLegExecutor:
    def __init__(self, service: IdempotentOrderService | None = None) -> None:
        self._service = service or IdempotentOrderService()

    def execute(
        self,
        first_client: TradingClient,
        first_request: OrderRequest,
        second_client: TradingClient,
        second_request: OrderRequest,
    ) -> DualLegExecutionResult:
        try:
            _compatible_legs(first_request, second_request)
            first_request = prepare_order(first_request)
            second_request = prepare_order(second_request)
        except (OrderDataError, TradingRuleError) as exc:
            return DualLegExecutionResult(
                DualLegStatus.PREFLIGHT_FAILED,
                failed_leg(
                    LegRole.FIRST,
                    first_request,
                    exc,
                    submitted=False,
                ),
                failed_leg(
                    LegRole.SECOND,
                    second_request,
                    exc,
                    submitted=False,
                ),
            )
        if _base_quantity(first_request) != _base_quantity(second_request):
            error = OrderDataError(
                "two legs have different normalized base quantities"
            )
            return DualLegExecutionResult(
                DualLegStatus.QUANTITY_MISMATCH,
                failed_leg(
                    LegRole.FIRST,
                    first_request,
                    error,
                    submitted=False,
                ),
                failed_leg(
                    LegRole.SECOND,
                    second_request,
                    error,
                    submitted=False,
                ),
            )
        try:
            first_order = self._service.submit(first_client, first_request)
        except _EXPECTED_FAILURES as exc:
            return DualLegExecutionResult(
                DualLegStatus.FIRST_FAILED,
                failed_leg(LegRole.FIRST, first_request, exc),
                None,
            )
        first = successful_leg(LegRole.FIRST, first_request, first_order)
        if _failed(first_order.status):
            return DualLegExecutionResult(DualLegStatus.FIRST_FAILED, first, None)
        if first_order.status is not OrderStatus.FILLED:
            return DualLegExecutionResult(DualLegStatus.FIRST_INCOMPLETE, first, None)

        try:
            second_order = self._service.submit(second_client, second_request)
        except _EXPECTED_FAILURES as exc:
            return DualLegExecutionResult(
                DualLegStatus.SECOND_FAILED,
                first,
                failed_leg(LegRole.SECOND, second_request, exc),
            )
        second = successful_leg(LegRole.SECOND, second_request, second_order)
        if _failed(second_order.status):
            return DualLegExecutionResult(DualLegStatus.SECOND_FAILED, first, second)
        if second_order.status is not OrderStatus.FILLED:
            return DualLegExecutionResult(
                DualLegStatus.SECOND_INCOMPLETE, first, second
            )
        if first_order.filled_base_quantity != second_order.filled_base_quantity:
            return DualLegExecutionResult(
                DualLegStatus.QUANTITY_MISMATCH, first, second
            )
        return DualLegExecutionResult(DualLegStatus.COMPLETED, first, second)


def _failed(status: OrderStatus) -> bool:
    return status in {
        OrderStatus.CANCELED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
    }


def _compatible_legs(first: OrderRequest, second: OrderRequest) -> None:
    if first.instrument.exchange is second.instrument.exchange:
        raise OrderDataError("two legs must use different exchanges")
    if first.side is second.side:
        raise OrderDataError("two legs must use opposite order sides")
    fields = ("base_asset", "quote_asset", "settlement_asset")
    if any(
        getattr(first.instrument, field) != getattr(second.instrument, field)
        for field in fields
    ):
        raise OrderDataError("two legs use incompatible assets")


def _base_quantity(request: OrderRequest) -> Decimal:
    return request.quantity * request.instrument.rules.contract_multiplier


_EXPECTED_FAILURES = (
    ExchangeRestError,
    OrderStateUnknownError,
    DuplicateOrderSubmissionError,
    OrderDataError,
    TradingRuleError,
)
