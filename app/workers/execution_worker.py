"""Focused background runner for blocking LIVE order execution calls."""

from concurrent.futures import Future, ThreadPoolExecutor
from decimal import Decimal
import threading

from PySide6.QtCore import QObject, Signal

from app.application.dto.opportunity_dto import ExecutableOpportunity
from app.domain.arbitrage.arbitrage_position import ArbitragePosition
from app.domain.enums import Exchange, MarketType
from app.domain.orders.fill import OrderFill
from app.domain.orders.order import Order
from app.exchanges.base.trading_client import TradingClient
from app.execution.execution_coordinator import OpenExecutionCoordinator
from app.execution.position_close_executor import PositionCloseExecutor


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
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._open_executor = open_executor or OpenExecutionCoordinator()
        self._close_executor = close_executor or PositionCloseExecutor()
        self._trading_clients = trading_clients or {}
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="live-rest")
        self._lock = threading.Lock()
        self._is_shutdown = False

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
        self.status_changed.emit(f"正在提交双腿开仓：{plan.position_id}")
        first_client = self._client_for(plan.first_request.instrument)
        second_client = self._client_for(plan.second_request.instrument)
        future = self._submit(
            self._open_executor.start,
            plan,
            first_client,
            second_client,
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
        )
        future.add_done_callback(
            lambda completed: self._emit_close(position.position_id, completed)
        )
        return future

    def reconcile_close(
        self,
        position_id: str,
        event: Order | OrderFill,
    ) -> Future:
        future = self._submit(self._close_executor.reconcile, position_id, event)
        future.add_done_callback(
            lambda completed: self._emit_close(position_id, completed)
        )
        return future

    def retry_close(
        self,
        position: ArbitragePosition,
        *,
        first_reference_price: Decimal,
        second_reference_price: Decimal,
    ) -> Future:
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
        )
        future.add_done_callback(
            lambda completed: self._emit_close(position.position_id, completed)
        )
        return future

    def reconcile_open(
        self,
        position_id: str,
        event: Order | OrderFill,
    ) -> Future:
        future = self._submit(self._open_executor.reconcile, position_id, event)
        future.add_done_callback(
            lambda completed: self._emit_open(position_id, completed)
        )
        return future

    def resume_open(self, position_id: str) -> Future:
        future = self._submit(self._open_executor.resume, position_id)
        future.add_done_callback(
            lambda completed: self._emit_open(position_id, completed)
        )
        return future

    def resume_close(self, position_id: str) -> Future:
        future = self._submit(self._close_executor.resume, position_id)
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

    def can_execute(self, plan: ExecutableOpportunity) -> bool:
        return all(
            (request.instrument.exchange, request.instrument.market_type)
            in self._trading_clients
            for request in (plan.first_request, plan.second_request)
        )

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

    def _emit_open(self, position_id: str, future: Future) -> None:
        try:
            result = future.result()
        except Exception as exc:
            self.operation_failed.emit(position_id, str(exc))
            return
        self.open_completed.emit(position_id, result)
        self.status_changed.emit(f"双腿开仓结果：{result.status.value}")

    def _emit_close(self, position_id: str, future: Future) -> None:
        try:
            result = future.result()
        except Exception as exc:
            self.operation_failed.emit(position_id, str(exc))
            return
        self.close_completed.emit(position_id, result)
        self.status_changed.emit(f"双腿平仓结果：{result.status.value}")
