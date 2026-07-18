from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import unittest
from unittest.mock import Mock

from app.domain.orders.order import OrderStatus
from app.domain.orders.order_group import DualLegStatus
from app.exchanges.base.exchange_errors import ExchangeResponseError, ExchangeTimeoutError
from app.execution.execution_coordinator import OpenExecutionCoordinator
from tests.domain.test_arbitrage_positions import NOW, _filled
from tests.ui.test_stage10_integration import _plan


class OpenExecutionCoordinatorTests(unittest.TestCase):
    def test_partial_rest_result_advances_after_private_order_update(self) -> None:
        plan = _plan()
        first_client = Mock()
        second_client = Mock()
        partial = replace(
            _filled(plan.first_request, "0.004", "60000", "0.24", "open-1"),
            status=OrderStatus.PARTIALLY_FILLED,
        )
        first_client.create_order.return_value = partial
        second_client.create_order.side_effect = lambda request: _filled(
            request, "0.009", "60100", "0.5409", "open-2"
        )
        coordinator = OpenExecutionCoordinator()

        pending = coordinator.start(plan, first_client, second_client)
        self.assertEqual(pending.status, DualLegStatus.FIRST_INCOMPLETE)
        second_client.create_order.assert_not_called()

        completed_first = replace(
            partial,
            status=OrderStatus.FILLED,
            cumulative_filled_quantity=Decimal("0.009"),
            cumulative_fee=Decimal("0.54"),
            updated_time=NOW + timedelta(milliseconds=1),
        )
        completed = coordinator.reconcile(plan.position_id, completed_first)

        self.assertEqual(completed.status, DualLegStatus.COMPLETED)
        second_client.create_order.assert_called_once()

    def test_unknown_open_submission_only_queries_original_id_on_resume(self) -> None:
        plan = _plan()
        first_client = Mock()
        second_client = Mock()
        first_client.create_order.side_effect = ExchangeTimeoutError("timeout")
        query_count = 0

        def query(request):
            nonlocal query_count
            query_count += 1
            if query_count == 1:
                raise ExchangeResponseError("still unknown")
            return _filled(request, "0.009", "60000", "0.54", "open-1")

        first_client.query_order.side_effect = query
        second_client.create_order.side_effect = lambda request: _filled(
            request, "0.009", "60100", "0.5409", "open-2"
        )
        coordinator = OpenExecutionCoordinator()

        unknown = coordinator.start(plan, first_client, second_client)
        recovered = coordinator.resume(plan.position_id)

        self.assertEqual(unknown.status, DualLegStatus.FIRST_UNKNOWN)
        self.assertEqual(recovered.status, DualLegStatus.COMPLETED)
        first_client.create_order.assert_called_once()
        self.assertEqual(first_client.query_order.call_count, 2)


if __name__ == "__main__":
    unittest.main()
