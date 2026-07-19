"""Stateful REST/private-stream coordination for a two-leg opening plan."""

from dataclasses import dataclass
from collections.abc import Callable

from app.application.dto.opportunity_dto import ExecutableOpportunity
from app.domain.exceptions import OrderDataError, TradingRuleError
from app.domain.orders.fill import OrderFill
from app.domain.orders.order import Order, OrderRequest, OrderStatus
from app.domain.orders.order_group import DualLegExecutionResult, DualLegStatus
from app.domain.orders.order_leg import (
    LegRole,
    failed_leg,
    successful_leg,
    unknown_leg,
)
from app.exchanges.base.exchange_errors import ExchangeRestError
from app.exchanges.base.trading_client import TradingClient
from app.execution.dual_leg_executor import (
    DualLegQuantityMismatchError,
    prepare_follow_up_request,
    prepare_dual_leg_requests,
)
from app.execution.fill_tracker import OrderReconciler, ReconcileResult
from app.execution.order_recovery_service import (
    DuplicateOrderSubmissionError,
    IdempotentOrderService,
    OrderStateUnknownError,
    RecoveryContext,
)


@dataclass(slots=True)
class _OpenContext:
    position_id: str
    first_client: TradingClient
    second_client: TradingClient
    first_request: OrderRequest
    second_request: OrderRequest
    reconciler: OrderReconciler
    result: DualLegExecutionResult
    first_order: Order | None = None
    second_order: Order | None = None


class OpenExecutionCoordinator:
    def __init__(self, service: IdempotentOrderService | None = None) -> None:
        self._service = service or IdempotentOrderService()
        self._contexts: dict[str, _OpenContext] = {}
        self._results: dict[str, DualLegExecutionResult] = {}

    def start(
        self,
        plan: ExecutableOpportunity,
        first_client: TradingClient,
        second_client: TradingClient,
        before_submit: Callable[[tuple[object, ...]], None] | None = None,
        defer_not_ready: bool = False,
    ) -> DualLegExecutionResult:
        known = self._results.get(plan.position_id)
        if known is not None:
            return known
        try:
            first_request, second_request = prepare_dual_leg_requests(
                plan.first_request, plan.second_request
            )
        except DualLegQuantityMismatchError as exc:
            return self._store_preflight(plan, DualLegStatus.QUANTITY_MISMATCH, exc)
        except (OrderDataError, TradingRuleError) as exc:
            return self._store_preflight(plan, DualLegStatus.PREFLIGHT_FAILED, exc)
        initial = DualLegExecutionResult(
            DualLegStatus.FIRST_INCOMPLETE,
            failed_leg(LegRole.FIRST, first_request, RuntimeError("not submitted"), submitted=False),
            None,
        )
        context = _OpenContext(
            plan.position_id,
            first_client,
            second_client,
            first_request,
            second_request,
            OrderReconciler(),
            initial,
        )
        self._contexts[plan.position_id] = context
        self._service.register_context(
            plan.position_id, "open", (first_request, second_request)
        )
        return self._advance(context, before_submit, defer_not_ready)

    def restore(
        self,
        recovery: RecoveryContext,
        clients: dict,
        before_submit: Callable[[tuple[object, ...]], None] | None = None,
        defer_not_ready: bool = False,
    ) -> DualLegExecutionResult:
        if recovery.kind != "open" or len(recovery.requests) != 2:
            raise OrderDataError("invalid opening recovery context")
        known = self._results.get(recovery.operation_id)
        if known is not None and known.status in _TERMINAL_RESULTS:
            return known
        active = self._contexts.get(recovery.operation_id)
        if active is not None:
            return self._advance(active, before_submit, defer_not_ready)
        first_request, second_request = recovery.requests
        context = _OpenContext(
            recovery.operation_id,
            clients[(first_request.instrument.exchange, first_request.instrument.market_type)],
            clients[(second_request.instrument.exchange, second_request.instrument.market_type)],
            first_request,
            second_request,
            OrderReconciler(),
            DualLegExecutionResult(
                DualLegStatus.FIRST_INCOMPLETE,
                failed_leg(LegRole.FIRST, first_request, RuntimeError("recovering"), submitted=False),
                None,
            ),
            self._service.known_order(first_request),
            self._service.known_order(second_request),
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
    ) -> DualLegExecutionResult:
        context = self._context(position_id)
        confirm_deferred = self._service.confirmation_required(position_id)
        if context.first_order is not None and not context.first_order.is_terminal:
            context.first_order = self._service.refresh(
                context.first_client, context.first_request
            )
        if context.second_order is not None and not context.second_order.is_terminal:
            context.second_order = self._service.refresh(
                context.second_client, context.second_request
            )
        return self._advance(
            context, before_submit, defer_not_ready, confirm_deferred
        )

    def instruments_for(self, position_id: str) -> tuple[object, ...]:
        context = self._context(position_id)
        return (
            context.first_request.instrument,
            context.second_request.instrument,
        )

    def operation_for(self, event: Order | OrderFill) -> str | None:
        for position_id, context in self._contexts.items():
            if event.client_order_id in {
                context.first_request.client_order_id,
                context.second_request.client_order_id,
            }:
                return position_id
        return None

    def reconcile(
        self,
        position_id: str,
        event: Order | OrderFill,
        before_submit: Callable[[tuple[object, ...]], None] | None = None,
        defer_not_ready: bool = False,
    ) -> DualLegExecutionResult:
        context = self._context(position_id)
        outcome = context.reconciler.apply(event)
        if outcome is ReconcileResult.SNAPSHOT_REQUIRED:
            raise OrderDataError("open reconciliation requires an order snapshot")
        client_id = event.client_order_id
        if client_id == context.first_request.client_order_id:
            current = context.reconciler.get(context.first_request)
            context.first_order = current
        elif client_id == context.second_request.client_order_id:
            current = context.reconciler.get(context.second_request)
            context.second_order = current
        else:
            raise OrderDataError("order event does not belong to this opening plan")
        self._service.record(current)
        return self._advance(context, before_submit, defer_not_ready)

    def _advance(
        self,
        context: _OpenContext,
        before_submit: Callable[[tuple[object, ...]], None] | None = None,
        defer_not_ready: bool = False,
        confirm_deferred: bool = False,
    ) -> DualLegExecutionResult:
        confirmed_first = False
        try:
            if (
                context.first_order is None
                and self._service.confirmation_required(context.position_id)
                and not confirm_deferred
            ):
                return self._deferred(context, LegRole.FIRST)
            confirmed_first = (
                context.first_order is None
                and confirm_deferred
                and self._service.confirmation_required(context.position_id)
            )
            if context.first_order is None and before_submit is not None:
                try:
                    before_submit(self.instruments_for(context.position_id))
                except RuntimeError as exc:
                    if defer_not_ready:
                        raise
                    self._service.set_confirmation_required(
                        context.position_id, True
                    )
                    return self._deferred(context, LegRole.FIRST, error=exc)
            first = context.first_order or (
                self._service.confirm_and_submit(
                    context.first_client,
                    context.first_request,
                    context.position_id,
                )
                if confirmed_first
                else self._service.submit(
                    context.first_client, context.first_request
                )
            )
        except OrderStateUnknownError as exc:
            return self._store(
                context,
                DualLegExecutionResult(
                    DualLegStatus.FIRST_UNKNOWN,
                    unknown_leg(LegRole.FIRST, context.first_request, exc),
                    None,
                ),
            )
        except _FAILURES as exc:
            return self._store(
                context,
                DualLegExecutionResult(
                    DualLegStatus.FIRST_FAILED,
                    failed_leg(LegRole.FIRST, context.first_request, exc),
                    None,
                ),
            )
        context.first_order = first
        context.reconciler.apply(first)
        self._service.record(first)
        first_leg = successful_leg(LegRole.FIRST, context.first_request, first)
        if _failed(first):
            return self._store(context, DualLegExecutionResult(DualLegStatus.FIRST_FAILED, first_leg, None))
        if first.status is not OrderStatus.FILLED:
            return self._store(context, DualLegExecutionResult(DualLegStatus.FIRST_INCOMPLETE, first_leg, None))
        try:
            context.second_request = prepare_follow_up_request(
                first, context.second_request
            )
            self._service.register_context(
                context.position_id,
                "open",
                (context.first_request, context.second_request),
            )
            if (
                context.second_order is None
                and self._service.confirmation_required(context.position_id)
                and not confirm_deferred
            ):
                return self._deferred(
                    context, LegRole.SECOND, first_leg=first_leg
                )
            if context.second_order is None and before_submit is not None:
                try:
                    before_submit(self.instruments_for(context.position_id))
                except RuntimeError as exc:
                    if defer_not_ready:
                        raise
                    self._service.set_confirmation_required(
                        context.position_id, True
                    )
                    return self._deferred(
                        context,
                        LegRole.SECOND,
                        first_leg=first_leg,
                        error=exc,
                    )
            confirmed_second = (
                context.second_order is None
                and confirm_deferred
                and self._service.confirmation_required(context.position_id)
            )
            second = context.second_order or (
                self._service.confirm_and_submit(
                    context.second_client,
                    context.second_request,
                    context.position_id,
                )
                if confirmed_second
                else self._service.submit(
                    context.second_client, context.second_request
                )
            )
        except OrderStateUnknownError as exc:
            return self._store(
                context,
                DualLegExecutionResult(
                    DualLegStatus.SECOND_UNKNOWN,
                    first_leg,
                    unknown_leg(LegRole.SECOND, context.second_request, exc),
                ),
            )
        except _FAILURES as exc:
            return self._store(
                context,
                DualLegExecutionResult(
                    DualLegStatus.SECOND_FAILED,
                    first_leg,
                    failed_leg(LegRole.SECOND, context.second_request, exc),
                ),
            )
        context.second_order = second
        context.reconciler.apply(second)
        self._service.record(second)
        second_leg = successful_leg(LegRole.SECOND, context.second_request, second)
        if _failed(second):
            return self._store(context, DualLegExecutionResult(DualLegStatus.SECOND_FAILED, first_leg, second_leg))
        if second.status is not OrderStatus.FILLED:
            return self._store(context, DualLegExecutionResult(DualLegStatus.SECOND_INCOMPLETE, first_leg, second_leg))
        if first.filled_base_quantity != second.filled_base_quantity:
            return self._store(context, DualLegExecutionResult(DualLegStatus.QUANTITY_MISMATCH, first_leg, second_leg))
        return self._store(context, DualLegExecutionResult(DualLegStatus.COMPLETED, first_leg, second_leg))

    def _deferred(
        self,
        context: _OpenContext,
        role: LegRole,
        *,
        first_leg=None,
        error: Exception | None = None,
    ) -> DualLegExecutionResult:
        error = error or RuntimeError("explicit confirmation is required")
        if role is LegRole.FIRST:
            return self._store(
                context,
                DualLegExecutionResult(
                    DualLegStatus.FIRST_DEFERRED,
                    failed_leg(
                        role, context.first_request, error, submitted=False
                    ),
                    None,
                ),
            )
        return self._store(
            context,
            DualLegExecutionResult(
                DualLegStatus.SECOND_DEFERRED,
                first_leg,
                failed_leg(
                    role, context.second_request, error, submitted=False
                ),
            ),
        )

    def _context(self, position_id: str) -> _OpenContext:
        try:
            return self._contexts[position_id]
        except KeyError:
            raise OrderDataError(f"unknown opening plan {position_id!r}") from None

    def _store(
        self,
        context: _OpenContext,
        result: DualLegExecutionResult,
    ) -> DualLegExecutionResult:
        context.result = result
        self._results[context.position_id] = result
        if result.status in {
            DualLegStatus.COMPLETED,
            DualLegStatus.FIRST_FAILED,
            DualLegStatus.SECOND_FAILED,
            DualLegStatus.QUANTITY_MISMATCH,
            DualLegStatus.PREFLIGHT_FAILED,
        }:
            self._service.complete_context(context.position_id)
        return result

    def _store_preflight(
        self,
        plan: ExecutableOpportunity,
        status: DualLegStatus,
        error: Exception,
    ) -> DualLegExecutionResult:
        result = DualLegExecutionResult(
            status,
            failed_leg(LegRole.FIRST, plan.first_request, error, submitted=False),
            failed_leg(LegRole.SECOND, plan.second_request, error, submitted=False),
        )
        self._results[plan.position_id] = result
        return result


def _failed(order: Order) -> bool:
    return order.status in {
        OrderStatus.CANCELED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
    }


_FAILURES = (
    ExchangeRestError,
    DuplicateOrderSubmissionError,
    OrderDataError,
    TradingRuleError,
)

_TERMINAL_RESULTS = {
    DualLegStatus.COMPLETED,
    DualLegStatus.FIRST_FAILED,
    DualLegStatus.SECOND_FAILED,
    DualLegStatus.QUANTITY_MISMATCH,
    DualLegStatus.PREFLIGHT_FAILED,
}
