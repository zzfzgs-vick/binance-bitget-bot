"""Idempotent sequential close execution for an existing arbitrage position."""

from dataclasses import dataclass, replace
from collections.abc import Callable
from decimal import Decimal
from enum import Enum

from app.domain.arbitrage.arbitrage_position import ArbitragePosition, PositionStatus
from app.domain.enums import MarketType
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
    RecoveryContext,
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
        before_submit: Callable[[tuple[object, ...]], None] | None = None,
        defer_not_ready: bool = False,
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
        requests = tuple(
            request for request in (first_request, second_request) if request is not None
        )
        if requests:
            self._service.register_context(
                position.position_id, "close", requests, position
            )
        return self._advance(context, before_submit, defer_not_ready)

    def restore(
        self,
        recovery: RecoveryContext,
        clients: dict,
        before_submit: Callable[[tuple[object, ...]], None] | None = None,
        defer_not_ready: bool = False,
    ) -> PositionCloseResult:
        if recovery.kind != "close" or recovery.position is None:
            raise PositionDataError("invalid close recovery context")
        known = self._results.get(recovery.operation_id)
        if known is not None and known.status not in {
            PositionCloseStatus.FIRST_PENDING,
            PositionCloseStatus.SECOND_PENDING,
            PositionCloseStatus.UNKNOWN,
        }:
            return known
        active = self._contexts.get(recovery.operation_id)
        if active is not None:
            return self._advance(active, before_submit, defer_not_ready)
        requests = recovery.requests
        if not requests:
            raise PositionDataError("close recovery context has no order request")
        first_request = next(
            (item for item in requests if item.instrument == recovery.position.first_leg.instrument),
            None,
        )
        second_request = next(
            (item for item in requests if item.instrument == recovery.position.second_leg.instrument),
            None,
        )
        first_instrument = recovery.position.first_leg.instrument
        second_instrument = recovery.position.second_leg.instrument
        context = _CloseContext(
            recovery.position,
            clients[(first_instrument.exchange, first_instrument.market_type)],
            clients[(second_instrument.exchange, second_instrument.market_type)],
            first_request,
            second_request,
            OrderReconciler(),
            PositionCloseResult(
                PositionCloseStatus.FIRST_PENDING,
                recovery.position,
                first_request,
                second_request,
            ),
            None if first_request is None else self._service.known_order(first_request),
            None if second_request is None else self._service.known_order(second_request),
        )
        for order in (context.first_order, context.second_order):
            if order is not None:
                context.reconciler.apply(order)
        self._contexts[recovery.operation_id] = context
        return self._advance(context, before_submit, defer_not_ready)

    def resume(
        self,
        position_id: str,
        before_submit: Callable[[tuple[object, ...]], None] | None = None,
        defer_not_ready: bool = False,
    ) -> PositionCloseResult:
        """Query an uncertain original order and continue; never create a replacement."""
        try:
            context = self._contexts[position_id]
        except KeyError:
            raise PositionDataError(f"unknown close operation {position_id!r}") from None
        confirm_deferred = self._service.confirmation_required(position_id)
        if (
            context.first_request is not None
            and context.first_order is not None
            and not context.first_order.is_terminal
        ):
            context.first_order = self._service.refresh(
                context.first_client, context.first_request
            )
        if (
            context.second_request is not None
            and context.second_order is not None
            and not context.second_order.is_terminal
        ):
            context.second_order = self._service.refresh(
                context.second_client, context.second_request
            )
        return self._advance(
            context, before_submit, defer_not_ready, confirm_deferred
        )

    def instruments_for(self, position_id: str) -> tuple[object, ...]:
        try:
            context = self._contexts[position_id]
        except KeyError:
            raise PositionDataError(
                f"unknown close operation {position_id!r}"
            ) from None
        return (
            context.original_position.first_leg.instrument,
            context.original_position.second_leg.instrument,
        )

    def operation_for(self, event: Order | OrderFill) -> str | None:
        for position_id, context in self._contexts.items():
            requests = tuple(
                request
                for request in (context.first_request, context.second_request)
                if request is not None
            )
            if any(event.client_order_id == request.client_order_id for request in requests):
                return position_id
        return None

    def retry(
        self,
        position: ArbitragePosition,
        first_client: TradingClient,
        second_client: TradingClient,
        *,
        first_reference_price: Decimal,
        second_reference_price: Decimal,
        before_submit: Callable[[tuple[object, ...]], None] | None = None,
        defer_not_ready: bool = False,
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
            before_submit=before_submit,
            defer_not_ready=defer_not_ready,
        )

    def reconcile(
        self,
        position_id: str,
        event: Order | OrderFill,
        before_submit: Callable[[tuple[object, ...]], None] | None = None,
        defer_not_ready: bool = False,
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
        return self._advance(context, before_submit, defer_not_ready)

    def _advance(
        self,
        context: _CloseContext,
        before_submit: Callable[[tuple[object, ...]], None] | None = None,
        defer_not_ready: bool = False,
        confirm_deferred: bool = False,
    ) -> PositionCloseResult:
        position = context.original_position
        first = context.first_order
        if context.first_request is not None:
            try:
                if (
                    first is None
                    and self._service.confirmation_required(position.position_id)
                    and not confirm_deferred
                ):
                    return self._confirmation_result(context, position, first)
                if first is None and before_submit is not None:
                    try:
                        before_submit(self.instruments_for(position.position_id))
                    except RuntimeError as exc:
                        if defer_not_ready:
                            raise
                        self._service.set_confirmation_required(
                            position.position_id, True
                        )
                        return self._confirmation_result(
                            context, position, first, error=exc
                        )
                confirmed_first = (
                    first is None
                    and confirm_deferred
                    and self._service.confirmation_required(position.position_id)
                )
                first = first or (
                    self._service.confirm_and_submit(
                        context.first_client,
                        context.first_request,
                        position.position_id,
                    )
                    if confirmed_first
                    else self._service.submit(
                        context.first_client, context.first_request
                    )
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
            if (
                context.second_order is None
                and self._service.confirmation_required(position.position_id)
                and not confirm_deferred
            ):
                return self._confirmation_result(context, position, first)
            if context.second_order is None and before_submit is not None:
                try:
                    before_submit(self.instruments_for(position.position_id))
                except RuntimeError as exc:
                    if defer_not_ready:
                        raise
                    self._service.set_confirmation_required(
                        position.position_id, True
                    )
                    return self._confirmation_result(
                        context, position, first, error=exc
                    )
            confirmed_second = (
                context.second_order is None
                and confirm_deferred
                and self._service.confirmation_required(position.position_id)
            )
            second = context.second_order or (
                self._service.confirm_and_submit(
                    context.second_client,
                    context.second_request,
                    position.position_id,
                )
                if confirmed_second
                else self._service.submit(
                    context.second_client, context.second_request
                )
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

    def _confirmation_result(
        self,
        context: _CloseContext,
        position: ArbitragePosition,
        first: Order | None,
        *,
        error: Exception | None = None,
    ) -> PositionCloseResult:
        updated = position.with_close_orders(
            first, None, PositionStatus.CLOSE_UNKNOWN
        )
        return self._store(
            context,
            _result(
                PositionCloseStatus.UNKNOWN,
                updated,
                context.first_request,
                context.second_request,
                first=first,
                error=error or RuntimeError("explicit confirmation is required"),
            ),
        )

    def _store(
        self,
        context: _CloseContext,
        result: PositionCloseResult,
    ) -> PositionCloseResult:
        context.result = result
        self._results[context.original_position.position_id] = result
        if result.status not in {
            PositionCloseStatus.FIRST_PENDING,
            PositionCloseStatus.SECOND_PENDING,
            PositionCloseStatus.UNKNOWN,
        }:
            self._service.complete_context(context.original_position.position_id)
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
            reduce_only=(
                leg.instrument.market_type is MarketType.USDT_PERPETUAL
            ),
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
