"""Stateful REST/private-stream coordination for a two-leg opening plan."""

from dataclasses import dataclass

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
    prepare_dual_leg_requests,
)
from app.execution.fill_tracker import OrderReconciler, ReconcileResult
from app.execution.order_recovery_service import (
    DuplicateOrderSubmissionError,
    IdempotentOrderService,
    OrderStateUnknownError,
)


@dataclass(slots=True)
class _OpenContext:
    plan: ExecutableOpportunity
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
            plan,
            first_client,
            second_client,
            first_request,
            second_request,
            OrderReconciler(),
            initial,
        )
        self._contexts[plan.position_id] = context
        return self._advance(context)

    def resume(self, position_id: str) -> DualLegExecutionResult:
        return self._advance(self._context(position_id))

    def reconcile(
        self,
        position_id: str,
        event: Order | OrderFill,
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
        return self._advance(context)

    def _advance(self, context: _OpenContext) -> DualLegExecutionResult:
        try:
            first = context.first_order or self._service.submit(
                context.first_client, context.first_request
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
            second = context.second_order or self._service.submit(
                context.second_client, context.second_request
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
        self._results[context.plan.position_id] = result
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
