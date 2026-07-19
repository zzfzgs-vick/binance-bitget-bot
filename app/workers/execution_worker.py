"""Focused background runner for blocking LIVE order execution calls."""

from concurrent.futures import Future, ThreadPoolExecutor
from decimal import Decimal
import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from app.application.dto.opportunity_dto import ExecutableOpportunity
from app.domain.arbitrage.arbitrage_position import ArbitragePosition
from app.domain.enums import Exchange, MarketType
from app.domain.orders.fill import OrderFill
from app.domain.orders.order import Order
from app.exchanges.base.trading_client import TradingClient
from app.execution.execution_coordinator import OpenExecutionCoordinator
from app.execution.position_close_executor import PositionCloseExecutor
from app.execution.order_recovery_service import IdempotentOrderService


class LiveReadinessError(RuntimeError):
    """The required authenticated private stream is not currently ready."""


class ExecutionWorker(QObject):
    """Run synchronous REST execution off the Qt GUI thread and emit results."""

    open_completed = Signal(str, object)
    close_completed = Signal(str, object)
    operation_failed = Signal(str, str)
    status_changed = Signal(str)

    def __init__(
        self,
        *,
        open_executor: OpenExecutionCoordinator | None = None,
        close_executor: PositionCloseExecutor | None = None,
        trading_clients: dict[
            tuple[Exchange, MarketType], TradingClient
        ] | None = None,
        recovery_service: IdempotentOrderService | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._open_executor = open_executor or OpenExecutionCoordinator()
        self._close_executor = close_executor or PositionCloseExecutor()
        self._trading_clients = trading_clients or {}
        self._recovery_service = recovery_service
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="live-rest")
        self._lock = threading.Lock()
        self._is_shutdown = False
        self._recovery_thread: threading.Thread | None = None
        self._recovery_completion: Future | None = None
        self._recovering_ids: set[str] = set()
        self._readiness_check: Callable[[tuple[object, ...]], bool] = (
            lambda _instruments: True
        )

    @property
    def is_shutdown(self) -> bool:
        with self._lock:
            return self._is_shutdown

    def submit_open(
        self,
        plan: ExecutableOpportunity,
    ) -> Future:
        if not isinstance(plan, ExecutableOpportunity):
            raise TypeError("plan must be ExecutableOpportunity")
        self._require_live_ready(
            (plan.first_request.instrument, plan.second_request.instrument)
        )
        if plan.is_expired():
            raise RuntimeError("selected LIVE opportunity has expired; refresh it")
        self._require_recovery_complete()
        self.status_changed.emit(f"正在提交双腿开仓：{plan.position_id}")
        first_client = self._client_for(plan.first_request.instrument)
        second_client = self._client_for(plan.second_request.instrument)
        future = self._submit(
            self._open_executor.start,
            plan,
            first_client,
            second_client,
            self._require_live_ready,
        )
        future.add_done_callback(
            lambda completed: self._emit_open(plan.position_id, completed)
        )
        return future

    def submit_close(
        self,
        position: ArbitragePosition,
        *,
        first_reference_price: Decimal,
        second_reference_price: Decimal,
    ) -> Future:
        self._require_live_ready(
            (position.first_leg.instrument, position.second_leg.instrument)
        )
        self._require_recovery_complete()
        self.status_changed.emit(f"正在提交双腿平仓：{position.position_id}")
        first_client = self._client_for(position.first_leg.instrument)
        second_client = self._client_for(position.second_leg.instrument)
        future = self._submit(
            self._close_executor.start,
            position,
            first_client,
            second_client,
            first_reference_price=first_reference_price,
            second_reference_price=second_reference_price,
            before_submit=self._require_live_ready,
        )
        future.add_done_callback(
            lambda completed: self._emit_close(position.position_id, completed)
        )
        return future

    def reconcile_private_order(self, event: Order | OrderFill) -> Future | None:
        if self.is_shutdown:
            return None
        future = self._submit(self._apply_private_order, event)
        future.add_done_callback(self._emit_private_order)
        return future

    def recover_pending(self) -> Future | None:
        if self._recovery_service is None or not (
            self._recovery_service.pending_requests
            or self._recovery_service.recovery_contexts
        ):
            return None
        with self._lock:
            active = self._recovery_completion
            if active is not None and not active.done():
                return active
            completion = Future()
            self._recovery_completion = completion
        query = self._submit(
            self._recovery_service.recover_pending,
            self._trading_clients,
        )
        query.add_done_callback(
            lambda done: self._start_recovery_monitor(done, completion)
        )
        completion.add_done_callback(self._emit_recovery_completion)
        return completion

    def retry_close(
        self,
        position: ArbitragePosition,
        *,
        first_reference_price: Decimal,
        second_reference_price: Decimal,
    ) -> Future:
        self._require_live_ready(
            (position.first_leg.instrument, position.second_leg.instrument)
        )
        self.status_changed.emit(f"正在重试剩余平仓：{position.position_id}")
        first_client = self._client_for(position.first_leg.instrument)
        second_client = self._client_for(position.second_leg.instrument)
        future = self._submit(
            self._close_executor.retry,
            position,
            first_client,
            second_client,
            first_reference_price=first_reference_price,
            second_reference_price=second_reference_price,
            before_submit=self._require_live_ready,
        )
        future.add_done_callback(
            lambda completed: self._emit_close(position.position_id, completed)
        )
        return future

    def resume_open(self, position_id: str) -> Future:
        future = self._submit(
            self._open_executor.resume,
            position_id,
            self._require_live_ready,
        )
        future.add_done_callback(
            lambda completed: self._emit_open(position_id, completed)
        )
        return future

    def resume_close(self, position_id: str) -> Future:
        future = self._submit(
            self._close_executor.resume,
            position_id,
            self._require_live_ready,
        )
        future.add_done_callback(
            lambda completed: self._emit_close(position_id, completed)
        )
        return future

    def shutdown(self) -> None:
        with self._lock:
            if self._is_shutdown:
                return
            self._is_shutdown = True
        self._pool.shutdown(wait=True, cancel_futures=True)
        thread = self._recovery_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5.0)
            if thread.is_alive():
                raise RuntimeError("order recovery monitor did not stop")

    def can_execute(self, plan: ExecutableOpportunity) -> bool:
        instruments = (
            plan.first_request.instrument,
            plan.second_request.instrument,
        )
        return self._readiness_check(instruments) and not plan.is_expired() and all(
            (request.instrument.exchange, request.instrument.market_type)
            in self._trading_clients
            for request in (plan.first_request, plan.second_request)
        )

    def set_readiness_check(
        self, check: Callable[[tuple[object, ...]], bool]
    ) -> None:
        if not callable(check):
            raise TypeError("readiness check must be callable")
        self._readiness_check = check

    def _client_for(self, instrument) -> TradingClient:
        try:
            return self._trading_clients[
                (instrument.exchange, instrument.market_type)
            ]
        except KeyError:
            raise RuntimeError(
                "no LIVE trading adapter is registered for "
                f"{instrument.exchange.value}/{instrument.market_type.value}"
            ) from None

    def _submit(self, function, *args, **kwargs) -> Future:
        with self._lock:
            if self._is_shutdown:
                raise RuntimeError("execution worker is shut down")
            return self._pool.submit(function, *args, **kwargs)

    def _require_recovery_complete(self) -> None:
        if self._recovery_service is not None and (
            self._recovery_service.pending_requests
            or self._recovery_service.recovery_contexts
        ):
            raise RuntimeError("persisted order recovery must complete before new orders")

    def _require_live_ready(self, instruments: tuple[object, ...]) -> None:
        if not self._readiness_check(instruments):
            raise LiveReadinessError(
                "LIVE private data streams are not authenticated"
            )

    def _start_recovery_monitor(
        self, query: Future, completion: Future
    ) -> None:
        if self.is_shutdown:
            completion.cancel()
            return
        try:
            query.result()
        except Exception as exc:
            completion.set_exception(exc)
            return
        thread = threading.Thread(
            target=self._monitor_recovery,
            args=(completion,),
            name="order-recovery-monitor",
            daemon=False,
        )
        with self._lock:
            self._recovery_thread = thread
        thread.start()

    def _monitor_recovery(self, completion: Future) -> None:
        assert self._recovery_service is not None
        outcomes = []
        pending = list(self._recovery_service.recovery_contexts)
        with self._lock:
            self._recovering_ids.update(
                context.operation_id for context in pending
            )
        while pending and not self.is_shutdown:
            waiting = []
            for context in pending:
                try:
                    future = self._submit(self._restore_context, context)
                    result = future.result()
                except LiveReadinessError:
                    waiting.append(context)
                    continue
                except RuntimeError as exc:
                    if self.is_shutdown:
                        break
                    if not completion.done():
                        completion.set_exception(exc)
                    return
                except Exception as exc:
                    if not completion.done():
                        completion.set_exception(exc)
                    return
                if self.is_shutdown:
                    break
                outcomes.append((context.kind, context.operation_id, result))
                with self._lock:
                    self._recovering_ids.discard(context.operation_id)
                if context.kind == "open":
                    self.open_completed.emit(context.operation_id, result)
                else:
                    self.close_completed.emit(context.operation_id, result)
            pending = waiting
            if pending and not self.is_shutdown:
                threading.Event().wait(0.1)
        if not completion.done():
            completion.set_result(tuple(outcomes))

    def _restore_context(self, context):
        if context.kind == "open":
            return self._open_executor.restore(
                context,
                self._trading_clients,
                self._require_live_ready,
                True,
            )
        return self._close_executor.restore(
            context,
            self._trading_clients,
            self._require_live_ready,
            True,
        )

    def _emit_recovery_completion(self, future: Future) -> None:
        if self.is_shutdown:
            return
        try:
            future.result()
        except Exception as exc:
            self.operation_failed.emit("recovery", str(exc))
            return
        pending = len(self._recovery_service.pending_requests)
        contexts = len(self._recovery_service.recovery_contexts)
        self.status_changed.emit(
            "订单恢复完成"
            if pending == 0 and contexts == 0
            else f"仍有 {pending} 个原订单、{contexts} 个执行上下文待处理"
        )

    def _apply_private_order(self, event: Order | OrderFill):
        open_id = self._open_executor.operation_for(event)
        if open_id is not None:
            with self._lock:
                recovering = open_id in self._recovering_ids
            try:
                result = self._open_executor.reconcile(
                    open_id,
                    event,
                    self._require_live_ready,
                    recovering,
                )
            except LiveReadinessError:
                if recovering:
                    return None
                raise
            return "open", open_id, result
        close_id = self._close_executor.operation_for(event)
        if close_id is not None:
            with self._lock:
                recovering = close_id in self._recovering_ids
            try:
                result = self._close_executor.reconcile(
                    close_id,
                    event,
                    self._require_live_ready,
                    recovering,
                )
            except LiveReadinessError:
                if recovering:
                    return None
                raise
            return "close", close_id, result
        if self._recovery_service is not None and isinstance(event, Order):
            self._recovery_service.record(event)
        return None

    def _emit_private_order(self, future: Future) -> None:
        if self.is_shutdown:
            return
        try:
            outcome = future.result()
        except Exception as exc:
            self.operation_failed.emit("private-order", str(exc))
            return
        if outcome is None:
            return
        kind, operation_id, result = outcome
        if kind == "open":
            self.open_completed.emit(operation_id, result)
        else:
            self.close_completed.emit(operation_id, result)

    def _emit_open(self, position_id: str, future: Future) -> None:
        if self.is_shutdown:
            return
        try:
            result = future.result()
        except Exception as exc:
            if not self.is_shutdown:
                self.operation_failed.emit(position_id, str(exc))
            return
        if self.is_shutdown:
            return
        self.open_completed.emit(position_id, result)
        self.status_changed.emit(f"双腿开仓结果：{result.status.value}")

    def _emit_close(self, position_id: str, future: Future) -> None:
        if self.is_shutdown:
            return
        try:
            result = future.result()
        except Exception as exc:
            if not self.is_shutdown:
                self.operation_failed.emit(position_id, str(exc))
            return
        if self.is_shutdown:
            return
        self.close_completed.emit(position_id, result)
        self.status_changed.emit(f"双腿平仓结果：{result.status.value}")
