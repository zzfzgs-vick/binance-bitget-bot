"""Idempotent sequential close execution for an existing arbitrage position."""

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import Enum

from app.domain.arbitrage.arbitrage_position import ArbitragePosition, PositionStatus
from app.domain.exceptions import OrderDataError, PositionDataError, TradingRuleError
from app.domain.orders.fill import OrderFill
from app.domain.orders.order import Order, OrderRequest, OrderSide, OrderStatus, OrderType
from app.exchanges.base.exchange_errors import ExchangeRestError
from app.exchanges.base.trading_client import TradingClient
from app.execution.client_order_id_factory import ClientOrderIdFactory
from app.execution.fill_tracker import OrderReconciler, ReconcileResult
from app.execution.order_recovery_service import (
    DuplicateOrderSubmissionError,
    IdempotentOrderService,
    OrderStateUnknownError,
)
from app.execution.preflight_validator import prepare_order


class PositionCloseStatus(str, Enum):
    PREFLIGHT_FAILED = "preflight_failed"
    FIRST_PENDING = "first_pending"
    FIRST_FAILED = "first_failed"
    SECOND_PENDING = "second_pending"
    SECOND_FAILED = "second_failed"
    COMPLETED = "completed"
    QUANTITY_MISMATCH = "quantity_mismatch"
    REMAINING_QUANTITY = "remaining_quantity"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PositionCloseResult:
    status: PositionCloseStatus
    position: ArbitragePosition
    first_request: OrderRequest | None
    second_request: OrderRequest | None
    first_order: Order | None = None
    second_order: Order | None = None
    error: str | None = None

    @property
    def requires_attention(self) -> bool:
        return self.status not in {
            PositionCloseStatus.COMPLETED,
            PositionCloseStatus.REMAINING_QUANTITY,
        }

    @property
    def can_retry(self) -> bool:
        return self.status in _RETRYABLE_RESULTS


@dataclass(slots=True)
class _CloseContext:
    original_position: ArbitragePosition
    first_client: TradingClient
    second_client: TradingClient
    first_request: OrderRequest | None
    second_request: OrderRequest | None
    reconciler: OrderReconciler
    result: PositionCloseResult
    first_order: Order | None = None
    second_order: Order | None = None


class PositionCloseExecutor:
    """Keep one immutable close plan per position and never replace its order ids."""

    def __init__(
        self,
        service: IdempotentOrderService | None = None,
        client_order_ids: ClientOrderIdFactory | None = None,
    ) -> None:
        self._service = service or IdempotentOrderService()
        self._client_order_ids = client_order_ids or ClientOrderIdFactory("close")
        self._results: dict[str, PositionCloseResult] = {}
        self._contexts: dict[str, _CloseContext] = {}

    def start(
        self,
        position: ArbitragePosition,
        first_client: TradingClient,
        second_client: TradingClient,
        *,
        first_reference_price: Decimal,
        second_reference_price: Decimal,
    ) -> PositionCloseResult:
        known = self._results.get(position.position_id)
        if known is not None:
            return known
        first_request = (
            self._close_request(position.first_leg, first_reference_price, "first")
            if position.first_leg.remaining_quantity > 0
            else None
        )
        second_request = (
            self._close_request(position.second_leg, second_reference_price, "second")
            if position.second_leg.remaining_quantity > 0
            else None
        )
        try:
            if first_request is not None:
                first_request = prepare_order(first_request)
            if second_request is not None:
                second_request = prepare_order(second_request)
            if (
                first_request is not None
                and second_request is not None
                and _base_quantity(first_request) != _base_quantity(second_request)
            ):
                raise PositionDataError(
                    "close legs have different normalized base quantities"
                )
        except (OrderDataError, PositionDataError, TradingRuleError) as exc:
            result = PositionCloseResult(
                PositionCloseStatus.PREFLIGHT_FAILED,
                position,
                first_request,
                second_request,
                error=str(exc),
            )
            self._results[position.position_id] = result
            return result
        closing = position.with_close_orders(None, None, PositionStatus.CLOSING)
        initial = PositionCloseResult(
            PositionCloseStatus.FIRST_PENDING,
            closing,
            first_request,
            second_request,
        )
        context = _CloseContext(
            position,
            first_client,
            second_client,
            first_request,
            second_request,
            OrderReconciler(),
            initial,
        )
        self._contexts[position.position_id] = context
        return self._advance(context)

    def resume(self, position_id: str) -> PositionCloseResult:
        """Query an uncertain original order and continue; never create a replacement."""
        try:
            context = self._contexts[position_id]
        except KeyError:
            raise PositionDataError(f"unknown close operation {position_id!r}") from None
        return self._advance(context)

    def retry(
        self,
        position: ArbitragePosition,
        first_client: TradingClient,
        second_client: TradingClient,
        *,
        first_reference_price: Decimal,
        second_reference_price: Decimal,
    ) -> PositionCloseResult:
        """Start a new user-requested attempt for a retryable terminal result."""
        known = self._results.get(position.position_id)
        if known is None or not known.can_retry:
            raise PositionDataError("close operation has no retryable result")
        reconciled = replace(
            position,
            unrealized_pnl=known.position.unrealized_pnl,
        )
        if reconciled != known.position:
            raise PositionDataError("close retry requires the latest reconciled position")
        self._results.pop(position.position_id, None)
        self._contexts.pop(position.position_id, None)
        return self.start(
            position,
            first_client,
            second_client,
            first_reference_price=first_reference_price,
            second_reference_price=second_reference_price,
        )

    def reconcile(
        self,
        position_id: str,
        event: Order | OrderFill,
    ) -> PositionCloseResult:
        """Apply a normalized REST/WS order event and advance sequential execution."""
        try:
            context = self._contexts[position_id]
        except KeyError:
            raise PositionDataError(f"unknown close operation {position_id!r}") from None
        outcome = context.reconciler.apply(event)
        if outcome is ReconcileResult.SNAPSHOT_REQUIRED:
            raise PositionDataError("close reconciliation requires an order snapshot")
        client_id = event.client_order_id
        if (
            context.first_request is not None
            and client_id == context.first_request.client_order_id
        ):
            current = context.reconciler.get(context.first_request)
            context.first_order = current
        elif (
            context.second_request is not None
            and client_id == context.second_request.client_order_id
        ):
            current = context.reconciler.get(context.second_request)
            context.second_order = current
        else:
            raise PositionDataError("order event does not belong to this close operation")
        self._service.record(current)
        return self._advance(context)

    def _advance(self, context: _CloseContext) -> PositionCloseResult:
        position = context.original_position
        first = context.first_order
        if context.first_request is not None:
            try:
                first = first or self._service.submit(
                    context.first_client, context.first_request
                )
            except OrderStateUnknownError as exc:
                updated = position.with_close_orders(None, None, PositionStatus.CLOSE_UNKNOWN)
                return self._store(context, _result(PositionCloseStatus.UNKNOWN, updated, context.first_request, context.second_request, error=exc))
            except _FAILURES as exc:
                updated = position.with_close_orders(None, None, PositionStatus.CLOSE_FAILED)
                return self._store(context, _result(PositionCloseStatus.FIRST_FAILED, updated, context.first_request, context.second_request, error=exc))
            context.first_order = first
            context.reconciler.apply(first)
            self._service.record(first)
            if _failed(first):
                updated = position.with_close_orders(first, None, PositionStatus.CLOSE_FAILED)
                return self._store(context, _result(PositionCloseStatus.FIRST_FAILED, updated, context.first_request, context.second_request, first=first))
            if first.status is not OrderStatus.FILLED:
                updated = position.with_close_orders(first, None, PositionStatus.PARTIALLY_CLOSED)
                return self._store(context, _result(PositionCloseStatus.FIRST_PENDING, updated, context.first_request, context.second_request, first=first))
        if context.second_request is None:
            updated = position.with_close_orders(first, None, PositionStatus.CLOSED)
            return self._store(context, _result(PositionCloseStatus.COMPLETED, updated, context.first_request, context.second_request, first=first))
        try:
            second = context.second_order or self._service.submit(
                context.second_client, context.second_request
            )
        except OrderStateUnknownError as exc:
            updated = position.with_close_orders(first, None, PositionStatus.CLOSE_UNKNOWN)
            return self._store(context, _result(PositionCloseStatus.UNKNOWN, updated, context.first_request, context.second_request, first=first, error=exc))
        except _FAILURES as exc:
            updated = position.with_close_orders(first, None, PositionStatus.CLOSE_FAILED)
            return self._store(context, _result(PositionCloseStatus.SECOND_FAILED, updated, context.first_request, context.second_request, first=first, error=exc))
        context.second_order = second
        context.reconciler.apply(second)
        self._service.record(second)
        if _failed(second):
            updated = position.with_close_orders(first, second, PositionStatus.CLOSE_FAILED)
            return self._store(context, _result(PositionCloseStatus.SECOND_FAILED, updated, context.first_request, context.second_request, first=first, second=second))
        if second.status is not OrderStatus.FILLED:
            updated = position.with_close_orders(first, second, PositionStatus.PARTIALLY_CLOSED)
            return self._store(context, _result(PositionCloseStatus.SECOND_PENDING, updated, context.first_request, context.second_request, first=first, second=second))
        if (
            first is not None
            and first.filled_base_quantity != second.filled_base_quantity
        ):
            updated = position.with_close_orders(first, second, PositionStatus.CLOSE_FAILED)
            return self._store(context, _result(PositionCloseStatus.QUANTITY_MISMATCH, updated, context.first_request, context.second_request, first=first, second=second))
        partial = position.with_close_orders(first, second, PositionStatus.PARTIALLY_CLOSED)
        if (
            partial.first_leg.remaining_quantity != 0
            or partial.second_leg.remaining_quantity != 0
        ):
            return self._store(context, _result(PositionCloseStatus.REMAINING_QUANTITY, partial, context.first_request, context.second_request, first=first, second=second))
        updated = position.with_close_orders(first, second, PositionStatus.CLOSED)
        return self._store(context, _result(PositionCloseStatus.COMPLETED, updated, context.first_request, context.second_request, first=first, second=second))

    def _store(
        self,
        context: _CloseContext,
        result: PositionCloseResult,
    ) -> PositionCloseResult:
        context.result = result
        self._results[context.original_position.position_id] = result
        return result

    def _close_request(
        self,
        leg,
        reference_price: Decimal,
        role: str,
    ) -> OrderRequest:
        return OrderRequest(
            instrument=leg.instrument,
            side=(OrderSide.SELL if leg.opening_side is OrderSide.BUY else OrderSide.BUY),
            order_type=OrderType.MARKET,
            quantity=(leg.remaining_quantity / leg.instrument.rules.contract_multiplier),
            reference_price=reference_price,
            client_order_id=self._client_order_ids.create(role),
            position_side=leg.position_side,
        )


def _base_quantity(request: OrderRequest) -> Decimal:
    return request.quantity * request.instrument.rules.contract_multiplier


def _failed(order: Order) -> bool:
    return order.status in {OrderStatus.CANCELED, OrderStatus.REJECTED, OrderStatus.EXPIRED}


def _result(
    status: PositionCloseStatus,
    position: ArbitragePosition,
    first_request: OrderRequest | None,
    second_request: OrderRequest | None,
    *,
    first: Order | None = None,
    second: Order | None = None,
    error: Exception | None = None,
) -> PositionCloseResult:
    return PositionCloseResult(
        status,
        position,
        first_request,
        second_request,
        first,
        second,
        str(error) if error is not None else None,
    )


_FAILURES = (ExchangeRestError, DuplicateOrderSubmissionError, OrderDataError, TradingRuleError)

_RETRYABLE_RESULTS = {
    PositionCloseStatus.FIRST_FAILED,
    PositionCloseStatus.SECOND_FAILED,
    PositionCloseStatus.QUANTITY_MISMATCH,
    PositionCloseStatus.REMAINING_QUANTITY,
}
