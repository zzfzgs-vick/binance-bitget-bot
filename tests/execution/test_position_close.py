from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import unittest
from unittest.mock import Mock

from app.domain.arbitrage.arbitrage_position import ArbitragePosition, PositionStatus
from app.domain.orders.fill import Fill, OrderFill
from app.domain.orders.order import OrderSide, OrderStatus
from app.exchanges.base.exchange_errors import (
    ExchangeApiError,
    ExchangeResponseError,
    ExchangeTimeoutError,
)
from app.execution.position_close_executor import PositionCloseExecutor, PositionCloseStatus
from tests.domain.test_arbitrage_positions import NOW, _filled, _result


class PositionCloseExecutionTests(unittest.TestCase):
    def test_close_uses_reverse_orders_and_actual_remaining_quantities(self) -> None:
        position = ArbitragePosition.from_execution("position-close", _result(), NOW)
        first_client = Mock()
        second_client = Mock()

        def fill_first(request):
            return _filled(request, "0.009", "60200", "0.5418", "close-1")

        def fill_second(request):
            return _filled(request, "0.009", "59900", "0.5391", "close-2")

        first_client.create_order.side_effect = fill_first
        second_client.create_order.side_effect = fill_second

        result = PositionCloseExecutor().start(
            position,
            first_client,
            second_client,
            first_reference_price=Decimal("60200"),
            second_reference_price=Decimal("59900"),
        )

        self.assertEqual(result.status, PositionCloseStatus.COMPLETED)
        self.assertEqual(result.first_request.side, OrderSide.SELL)
        self.assertEqual(result.second_request.side, OrderSide.BUY)
        self.assertEqual(result.first_request.quantity, Decimal("0.009"))
        self.assertEqual(result.second_request.quantity, Decimal("0.009"))
        self.assertEqual(result.position.status, PositionStatus.CLOSED)
        self.assertEqual(result.position.first_leg.remaining_quantity, Decimal("0"))
        self.assertEqual(result.position.second_leg.remaining_quantity, Decimal("0"))
        self.assertEqual(result.position.realized_pnl, Decimal("1.4382"))

    def test_repeated_close_start_is_idempotent(self) -> None:
        position = ArbitragePosition.from_execution("position-idempotent", _result(), NOW)
        first_client = Mock()
        second_client = Mock()
        first_client.create_order.side_effect = lambda request: _filled(
            request, "0.009", "60200", "0.5418", "close-1"
        )
        second_client.create_order.side_effect = lambda request: _filled(
            request, "0.009", "59900", "0.5391", "close-2"
        )
        executor = PositionCloseExecutor()

        first = executor.start(
            position,
            first_client,
            second_client,
            first_reference_price=Decimal("60200"),
            second_reference_price=Decimal("59900"),
        )
        duplicate = executor.start(
            position,
            first_client,
            second_client,
            first_reference_price=Decimal("60200"),
            second_reference_price=Decimal("59900"),
        )

        self.assertIs(first, duplicate)
        first_client.create_order.assert_called_once()
        second_client.create_order.assert_called_once()

    def test_partial_first_leg_waits_for_reconciled_fill_before_second_leg(self) -> None:
        position = ArbitragePosition.from_execution("position-partial", _result(), NOW)
        first_client = Mock()
        second_client = Mock()
        partial = None

        def create_partial(request):
            nonlocal partial
            partial = replace(
                _filled(request, "0.004", "60200", "0.2408", "partial-close"),
                status=OrderStatus.PARTIALLY_FILLED,
            )
            return partial

        first_client.create_order.side_effect = create_partial
        second_client.create_order.side_effect = lambda request: _filled(
            request, "0.009", "59900", "0.5391", "close-2"
        )
        executor = PositionCloseExecutor()

        pending = executor.start(
            position,
            first_client,
            second_client,
            first_reference_price=Decimal("60200"),
            second_reference_price=Decimal("59900"),
        )
        self.assertEqual(pending.status, PositionCloseStatus.FIRST_PENDING)
        self.assertEqual(
            pending.position.first_leg.remaining_quantity, Decimal("0.005")
        )
        second_client.create_order.assert_not_called()

        fill_event = OrderFill(
            partial.instrument,
            partial.client_order_id,
            partial.exchange_order_id,
            Fill(
                "ws-close-fill",
                Decimal("60200"),
                Decimal("0.005"),
                Decimal("0.301"),
                "USDT",
                NOW + timedelta(milliseconds=1),
            ),
        )
        still_pending = executor.reconcile(position.position_id, fill_event)
        self.assertEqual(still_pending.status, PositionCloseStatus.FIRST_PENDING)
        duplicate = executor.reconcile(position.position_id, fill_event)
        self.assertEqual(duplicate.status, PositionCloseStatus.FIRST_PENDING)
        second_client.create_order.assert_not_called()

        completed_first = replace(
            partial,
            status=OrderStatus.FILLED,
            cumulative_filled_quantity=Decimal("0.009"),
            cumulative_fee=Decimal("0.5418"),
            updated_time=NOW + timedelta(milliseconds=2),
        )
        completed = executor.reconcile(position.position_id, completed_first)

        self.assertEqual(completed.status, PositionCloseStatus.COMPLETED)
        second_client.create_order.assert_called_once()

    def test_unknown_submission_resumes_by_querying_original_order(self) -> None:
        position = ArbitragePosition.from_execution("position-unknown", _result(), NOW)
        first_client = Mock()
        second_client = Mock()
        first_client.create_order.side_effect = ExchangeTimeoutError("timeout")
        query_count = 0

        def query(request):
            nonlocal query_count
            query_count += 1
            if query_count == 1:
                raise ExchangeResponseError("still unknown")
            return _filled(request, "0.009", "60200", "0.5418", "close-1")

        first_client.query_order.side_effect = query
        second_client.create_order.side_effect = lambda request: _filled(
            request, "0.009", "59900", "0.5391", "close-2"
        )
        executor = PositionCloseExecutor()

        unknown = executor.start(
            position,
            first_client,
            second_client,
            first_reference_price=Decimal("60200"),
            second_reference_price=Decimal("59900"),
        )
        self.assertEqual(unknown.status, PositionCloseStatus.UNKNOWN)
        recovered = executor.resume(position.position_id)

        self.assertEqual(recovered.status, PositionCloseStatus.COMPLETED)
        first_client.create_order.assert_called_once()
        self.assertEqual(first_client.query_order.call_count, 2)

    def test_quantity_rounding_reports_final_remaining_amount(self) -> None:
        position = ArbitragePosition.from_execution(
            "position-remainder", _result("0.0097", "0.0097"), NOW
        )
        first_client = Mock()
        second_client = Mock()
        first_client.create_order.side_effect = lambda request: _filled(
            request, "0.009", "60200", "0.5418", "close-1"
        )
        second_client.create_order.side_effect = lambda request: _filled(
            request, "0.009", "59900", "0.5391", "close-2"
        )

        result = PositionCloseExecutor().start(
            position,
            first_client,
            second_client,
            first_reference_price=Decimal("60200"),
            second_reference_price=Decimal("59900"),
        )

        self.assertEqual(result.status, PositionCloseStatus.REMAINING_QUANTITY)
        self.assertEqual(result.position.status, PositionStatus.PARTIALLY_CLOSED)
        self.assertEqual(
            result.position.first_leg.remaining_quantity, Decimal("0.0007")
        )
        self.assertEqual(
            result.position.second_leg.remaining_quantity, Decimal("0.0007")
        )

    def test_second_leg_failure_preserves_first_leg_close_and_reports_mismatch(self) -> None:
        position = ArbitragePosition.from_execution("position-failed", _result(), NOW)
        first_client = Mock()
        second_client = Mock()
        first_client.create_order.side_effect = lambda request: _filled(
            request, "0.009", "60200", "0.5418", "close-1"
        )
        second_client.create_order.side_effect = ExchangeApiError(
            "Bitget", "25202", "insufficient balance"
        )

        result = PositionCloseExecutor().start(
            position,
            first_client,
            second_client,
            first_reference_price=Decimal("60200"),
            second_reference_price=Decimal("59900"),
        )

        self.assertEqual(result.status, PositionCloseStatus.SECOND_FAILED)
        self.assertEqual(result.position.status, PositionStatus.CLOSE_FAILED)
        self.assertEqual(result.position.first_leg.remaining_quantity, Decimal("0"))
        self.assertEqual(result.position.second_leg.remaining_quantity, Decimal("0.009"))

    def test_second_leg_failure_can_retry_only_the_remaining_leg(self) -> None:
        position = ArbitragePosition.from_execution("position-asymmetric", _result(), NOW)
        first_client = Mock()
        second_client = Mock()
        first_client.create_order.side_effect = lambda request: _filled(
            request, "0.009", "60200", "0.5418", "close-1"
        )
        second_client.create_order.side_effect = [
            ExchangeApiError("Bitget", "25202", "insufficient balance"),
            None,
        ]
        executor = PositionCloseExecutor()
        failed = executor.start(
            position,
            first_client,
            second_client,
            first_reference_price=Decimal("60200"),
            second_reference_price=Decimal("59900"),
        )
        second_client.create_order.side_effect = lambda request: _filled(
            request, "0.009", "59900", "0.5391", "close-2"
        )

        marked = failed.position.mark_to_market(
            first_price=Decimal("60200"),
            second_price=Decimal("59900"),
        )
        self.assertNotEqual(marked.unrealized_pnl, failed.position.unrealized_pnl)

        completed = executor.retry(
            marked,
            first_client,
            second_client,
            first_reference_price=Decimal("60200"),
            second_reference_price=Decimal("59900"),
        )

        self.assertEqual(completed.status, PositionCloseStatus.COMPLETED)
        self.assertIsNone(completed.first_request)
        self.assertIsNotNone(completed.second_request)
        self.assertEqual(completed.second_request.quantity, Decimal("0.009"))
        self.assertEqual(completed.position.first_leg.remaining_quantity, Decimal("0"))
        self.assertEqual(completed.position.second_leg.remaining_quantity, Decimal("0"))
        first_client.create_order.assert_called_once()
        self.assertEqual(second_client.create_order.call_count, 2)

    def test_repeated_manual_retry_is_not_blocked_by_another_failure(self) -> None:
        position = ArbitragePosition.from_execution("position-retry-twice", _result(), NOW)
        first_client = Mock()
        second_client = Mock()
        first_client.create_order.side_effect = ExchangeApiError(
            "Binance", "-2010", "rejected"
        )
        executor = PositionCloseExecutor()
        first = executor.start(
            position,
            first_client,
            second_client,
            first_reference_price=Decimal("60200"),
            second_reference_price=Decimal("59900"),
        )
        second = executor.retry(
            first.position,
            first_client,
            second_client,
            first_reference_price=Decimal("60200"),
            second_reference_price=Decimal("59900"),
        )
        third = executor.retry(
            second.position,
            first_client,
            second_client,
            first_reference_price=Decimal("60200"),
            second_reference_price=Decimal("59900"),
        )

        self.assertEqual(third.status, PositionCloseStatus.FIRST_FAILED)
        self.assertEqual(first_client.create_order.call_count, 3)
        self.assertEqual(
            len(
                {
                    first.first_request.client_order_id,
                    second.first_request.client_order_id,
                    third.first_request.client_order_id,
                }
            ),
            3,
        )

    def test_manual_retry_uses_new_ids_and_only_current_remaining_quantity(self) -> None:
        position = ArbitragePosition.from_execution(
            "position-retry", _result("0.0097", "0.0097"), NOW
        )
        first_client = Mock()
        second_client = Mock()
        first_client.create_order.side_effect = lambda request: _filled(
            request, str(request.quantity), "60200", "0", f"first-{request.client_order_id}"
        )
        second_client.create_order.side_effect = lambda request: _filled(
            request, str(request.quantity), "59900", "0", f"second-{request.client_order_id}"
        )
        executor = PositionCloseExecutor()
        first_attempt = executor.start(
            position,
            first_client,
            second_client,
            first_reference_price=Decimal("60200"),
            second_reference_price=Decimal("59900"),
        )
        self.assertEqual(
            first_attempt.status, PositionCloseStatus.REMAINING_QUANTITY
        )

        second_attempt = executor.retry(
            first_attempt.position,
            first_client,
            second_client,
            first_reference_price=Decimal("60200"),
            second_reference_price=Decimal("59900"),
        )

        self.assertEqual(
            second_attempt.status, PositionCloseStatus.PREFLIGHT_FAILED
        )
        self.assertNotEqual(
            first_attempt.first_request.client_order_id,
            second_attempt.first_request.client_order_id,
        )
        self.assertEqual(second_attempt.first_request.quantity, Decimal("0.0007"))
        self.assertEqual(first_client.create_order.call_count, 1)


if __name__ == "__main__":
    unittest.main()
