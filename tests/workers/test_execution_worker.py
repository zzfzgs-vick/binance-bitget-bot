import os
import threading
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Slot
from PySide6.QtWidgets import QApplication

from app.domain.orders.order import OrderStatus
from app.workers.execution_worker import ExecutionWorker
from tests.domain.test_arbitrage_positions import _filled
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


if __name__ == "__main__":
    unittest.main()
