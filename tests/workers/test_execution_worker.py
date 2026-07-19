import os
import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Slot
from PySide6.QtWidgets import QApplication

from app.domain.orders.order import OrderStatus
from app.domain.orders.order_group import DualLegStatus
from app.domain.enums import Exchange, MarketType
from app.execution.execution_coordinator import OpenExecutionCoordinator
from app.execution.order_recovery_service import IdempotentOrderService
from app.execution.position_close_executor import PositionCloseExecutor
from app.workers.execution_worker import ExecutionWorker
from tests.domain.test_arbitrage_positions import NOW, _filled
from tests.ui.test_stage10_integration import _plan


class _Receiver(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.position_id = None
        self.result = None
        self.thread_id = None

    @Slot(str, object)
    def receive(self, position_id, result) -> None:
        self.position_id = position_id
        self.result = result
        self.thread_id = threading.get_ident()


class ExecutionWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_rest_execution_runs_off_gui_thread_and_returns_by_qt_signal(self) -> None:
        main_thread = threading.get_ident()
        call_threads = []
        plan = _plan()
        first_client = Mock()
        second_client = Mock()

        def first(request):
            call_threads.append(threading.get_ident())
            return _filled(request, "0.009", "60000", "0.54", "open-1")

        def second(request):
            call_threads.append(threading.get_ident())
            return _filled(request, "0.009", "60100", "0.5409", "open-2")

        first_client.create_order.side_effect = first
        second_client.create_order.side_effect = second
        worker = ExecutionWorker(
            trading_clients={
                (
                    plan.first_request.instrument.exchange,
                    plan.first_request.instrument.market_type,
                ): first_client,
                (
                    plan.second_request.instrument.exchange,
                    plan.second_request.instrument.market_type,
                ): second_client,
            }
        )
        receiver = _Receiver()
        worker.open_completed.connect(receiver.receive)

        future = worker.submit_open(plan)
        result = future.result(timeout=2)
        for _ in range(10):
            self.app.processEvents()
            if receiver.result is not None:
                break

        self.assertEqual(result.status.value, "completed")
        self.assertTrue(call_threads)
        self.assertTrue(all(thread_id != main_thread for thread_id in call_threads))
        self.assertEqual(receiver.thread_id, main_thread)
        self.assertEqual(receiver.position_id, plan.position_id)
        self.assertEqual(receiver.result.first.order.status, OrderStatus.FILLED)

        worker.shutdown()
        worker.shutdown()
        self.assertTrue(worker.is_shutdown)

    def test_expired_live_opportunity_cannot_be_submitted(self) -> None:
        plan = replace(
            _plan(),
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        worker = ExecutionWorker(trading_clients={})

        self.assertFalse(worker.can_execute(plan))
        with self.assertRaisesRegex(RuntimeError, "expired"):
            worker.submit_open(plan)

        worker.shutdown()

    def test_startup_rehydrates_persisted_open_context_before_new_orders(self) -> None:
        plan = _plan()
        first_client = Mock()
        second_client = Mock()
        first_fill = _filled(
            plan.first_request, "0.008", "60000", "0.48", "restored-first"
        )
        first_client.create_order.return_value = first_fill
        second_client.create_order.side_effect = lambda request: _filled(
            request, str(request.quantity), "60100", "0.4808", "restored-second"
        )
        clients = {
            (Exchange.BINANCE, MarketType.SPOT): first_client,
            (Exchange.BITGET, MarketType.USDT_PERPETUAL): second_client,
        }

        with TemporaryDirectory() as directory:
            path = Path(directory) / "orders.json"
            original = IdempotentOrderService(journal_path=path)
            original.register_context(
                plan.position_id,
                "open",
                (plan.first_request, plan.second_request),
            )
            original.submit(first_client, plan.first_request)

            recovered = IdempotentOrderService(journal_path=path)
            first_client.reset_mock()
            first_client.query_order.return_value = first_fill
            worker = ExecutionWorker(
                trading_clients=clients,
                recovery_service=recovered,
                open_executor=OpenExecutionCoordinator(recovered),
                close_executor=PositionCloseExecutor(recovered),
            )
            future = worker.recover_pending()
            self.assertIsNotNone(future)
            future.result(timeout=2)
            worker.shutdown()

        first_client.create_order.assert_not_called()
        first_client.query_order.assert_called_once_with(plan.first_request)
        second_client.create_order.assert_called_once()
        self.assertEqual(recovered.pending_requests, ())
        self.assertEqual(recovered.recovery_contexts, ())

    def test_recovery_queries_original_then_waits_and_auto_continues_when_ready(self) -> None:
        plan = _plan()
        first_client = Mock()
        second_client = Mock()
        first_fill = _filled(
            plan.first_request, "0.008", "60000", "0.48", "restored-first"
        )
        first_client.create_order.return_value = first_fill
        with TemporaryDirectory() as directory:
            path = Path(directory) / "orders.json"
            original = IdempotentOrderService(journal_path=path)
            original.register_context(
                plan.position_id,
                "open",
                (plan.first_request, plan.second_request),
            )
            original.submit(first_client, plan.first_request)
            recovered = IdempotentOrderService(journal_path=path)
            first_client.reset_mock()
            queried = threading.Event()
            def query_original(request):
                queried.set()
                return first_fill
            first_client.query_order.side_effect = query_original
            private_ready = threading.Event()
            second_client.create_order.side_effect = lambda request: _filled(
                request, str(request.quantity), "60100", "0.4808", "restored-second"
            )
            worker = ExecutionWorker(
                trading_clients={
                    (Exchange.BINANCE, MarketType.SPOT): first_client,
                    (Exchange.BITGET, MarketType.USDT_PERPETUAL): second_client,
                },
                recovery_service=recovered,
                open_executor=OpenExecutionCoordinator(recovered),
                close_executor=PositionCloseExecutor(recovered),
            )
            worker.set_readiness_check(lambda _instruments: private_ready.is_set())

            future = worker.recover_pending()
            self.assertTrue(queried.wait(timeout=1))
            second_client.create_order.assert_not_called()
            self.assertEqual(
                worker._submit(lambda: "available").result(timeout=1),
                "available",
            )
            private_ready.set()
            future.result(timeout=2)
            worker.shutdown()

        first_client.query_order.assert_called_once_with(plan.first_request)
        second_client.create_order.assert_called_once()

    def test_manual_resume_queries_original_before_private_stream_gate(self) -> None:
        plan = _plan()
        submitted = replace(
            _filled(plan.first_request, "0.009", "60000", "0", "pending"),
            status=OrderStatus.NEW,
            cumulative_filled_quantity=Decimal("0"),
            average_price=Decimal("0"),
        )
        first_client = Mock()
        second_client = Mock()
        first_client.create_order.return_value = submitted
        first_client.query_order.return_value = _filled(
            plan.first_request, "0.009", "60000", "0", "pending"
        )
        worker = ExecutionWorker(
            trading_clients={
                (Exchange.BINANCE, MarketType.SPOT): first_client,
                (Exchange.BITGET, MarketType.USDT_PERPETUAL): second_client,
            },
        )
        worker.submit_open(plan).result(timeout=2)
        worker.set_readiness_check(lambda _instruments: False)

        future = worker.resume_open(plan.position_id)
        result = future.result(timeout=2)

        first_client.query_order.assert_called_once_with(plan.first_request)
        self.assertEqual(result.status, DualLegStatus.SECOND_DEFERRED)
        second_client.create_order.assert_not_called()
        worker.set_readiness_check(lambda _instruments: True)
        second_client.create_order.side_effect = lambda request: _filled(
            request, str(request.quantity), "60100", "0", "resumed-second"
        )
        completed = worker.resume_open(plan.position_id).result(timeout=2)
        self.assertEqual(completed.status, DualLegStatus.COMPLETED)
        second_client.create_order.assert_called_once()
        worker.shutdown()


if __name__ == "__main__":
    unittest.main()
