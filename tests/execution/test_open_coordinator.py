from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from app.domain.orders.order import OrderRequest, OrderSide, OrderStatus, OrderType
from app.domain.orders.client_order_id import ClientOrderId
from app.domain.enums import Exchange, MarketType
from app.application.dto.opportunity_dto import ExecutableOpportunity
from app.exchanges.bitget.mappers.order_mapper import parse_order as parse_bitget_order
from app.strategy.opportunity_engine import OpportunityRequest, calculate_opportunity
from app.domain.orders.order_group import DualLegStatus
from app.exchanges.base.exchange_errors import ExchangeResponseError, ExchangeTimeoutError
from app.execution.execution_coordinator import OpenExecutionCoordinator
from app.execution.order_recovery_service import IdempotentOrderService
from tests.domain.test_arbitrage_positions import NOW, _filled
from tests.ui.test_stage10_integration import _book, _instrument, _plan


class OpenExecutionCoordinatorTests(unittest.TestCase):
    def test_restart_queries_filled_first_leg_then_submits_only_second_leg(self) -> None:
        plan = _plan()
        first_client = Mock()
        second_client = Mock()
        filled_first = _filled(
            plan.first_request, "0.008", "60000", "0.48", "persisted-first"
        )
        first_client.create_order.return_value = filled_first
        second_client.create_order.side_effect = lambda request: _filled(
            request, str(request.quantity), "60100", "0.4808", "recovered-second"
        )

        with TemporaryDirectory() as directory:
            path = Path(directory) / "orders.json"
            original = IdempotentOrderService(journal_path=path)
            original.register_context(
                plan.position_id,
                "open",
                (plan.first_request, plan.second_request),
            )
            original.submit(first_client, plan.first_request)

            restarted = IdempotentOrderService(journal_path=path)
            first_client.reset_mock()
            first_client.query_order.return_value = filled_first
            clients = {
                (Exchange.BINANCE, MarketType.SPOT): first_client,
                (Exchange.BITGET, MarketType.USDT_PERPETUAL): second_client,
            }
            restarted.recover_pending(clients)
            result = OpenExecutionCoordinator(restarted).restore(
                restarted.recovery_contexts[0], clients
            )

        self.assertEqual(result.status, DualLegStatus.COMPLETED)
        first_client.create_order.assert_not_called()
        first_client.query_order.assert_called_once_with(plan.first_request)
        second_client.create_order.assert_called_once()
        self.assertEqual(
            second_client.create_order.call_args.args[0].quantity,
            Decimal("0.008"),
        )
        self.assertEqual(restarted.pending_requests, ())
        self.assertEqual(restarted.recovery_contexts, ())

    def test_nonterminal_bitget_ack_advances_by_querying_original_order(self) -> None:
        plan = _plan()
        first_client = Mock()
        second_client = Mock()
        submitted = replace(
            _filled(plan.first_request, "0.009", "60000", "0", "pending"),
            status=OrderStatus.NEW,
            cumulative_filled_quantity=Decimal("0"),
            average_price=Decimal("0"),
        )
        first_client.create_order.return_value = submitted
        first_client.query_order.return_value = _filled(
            plan.first_request, "0.009", "60000", "0", "pending"
        )
        second_client.create_order.side_effect = lambda request: _filled(
            request, "0.009", "60100", "0", "second"
        )
        coordinator = OpenExecutionCoordinator()

        pending = coordinator.start(plan, first_client, second_client)
        completed = coordinator.resume(plan.position_id)

        self.assertEqual(pending.status, DualLegStatus.FIRST_INCOMPLETE)
        self.assertEqual(completed.status, DualLegStatus.COMPLETED)
        first_client.query_order.assert_called_once_with(plan.first_request)

    def test_nonterminal_query_does_not_require_private_stream_or_submit_second(self) -> None:
        plan = _plan()
        first_client = Mock()
        second_client = Mock()
        submitted = replace(
            _filled(plan.first_request, "0.009", "60000", "0", "pending"),
            status=OrderStatus.NEW,
            cumulative_filled_quantity=Decimal("0"),
            average_price=Decimal("0"),
        )
        first_client.create_order.return_value = submitted
        first_client.query_order.return_value = submitted
        readiness = Mock(side_effect=RuntimeError("must not be called"))
        coordinator = OpenExecutionCoordinator()
        coordinator.start(plan, first_client, second_client)

        result = coordinator.resume(plan.position_id, readiness)

        self.assertEqual(result.status, DualLegStatus.FIRST_INCOMPLETE)
        readiness.assert_not_called()
        first_client.query_order.assert_called_once_with(plan.first_request)
        second_client.create_order.assert_not_called()

    def test_recovery_keeps_waiting_after_duplicate_first_leg_event(self) -> None:
        plan = _plan()
        service = IdempotentOrderService()
        coordinator = OpenExecutionCoordinator(service)
        first_client = Mock()
        second_client = Mock()
        first = _filled(
            plan.first_request, "0.009", "60000", "0", "recovery-first"
        )
        first_client.create_order.return_value = first
        second_client.create_order.side_effect = lambda request: _filled(
            request, "0.009", "60100", "0", "recovery-second"
        )
        readiness = Mock(side_effect=(None, RuntimeError("stream lost")))

        with self.assertRaisesRegex(RuntimeError, "stream lost"):
            coordinator.start(
                plan,
                first_client,
                second_client,
                readiness,
                True,
            )
        with self.assertRaisesRegex(RuntimeError, "stream still lost"):
            coordinator.reconcile(
                plan.position_id,
                first,
                Mock(side_effect=RuntimeError("stream still lost")),
                True,
            )
        recovered = coordinator.restore(
            service.recovery_contexts[0],
            {
                (plan.first_request.instrument.exchange, plan.first_request.instrument.market_type): first_client,
                (plan.second_request.instrument.exchange, plan.second_request.instrument.market_type): second_client,
            },
            Mock(),
            True,
        )

        self.assertEqual(recovered.status, DualLegStatus.COMPLETED)
        first_client.create_order.assert_called_once()
        second_client.create_order.assert_called_once()

    def test_deferred_second_leg_requires_confirmation_after_restart(self) -> None:
        plan = _plan()
        first_client = Mock()
        second_client = Mock()
        first = _filled(
            plan.first_request, "0.009", "60000", "0", "deferred-first"
        )
        first_client.create_order.return_value = first
        journal_at_create = []
        with TemporaryDirectory() as directory:
            path = Path(directory) / "orders.json"
            def create_second(request):
                journal_at_create.append(
                    json.loads(path.read_text(encoding="utf-8"))
                )
                return _filled(
                    request, "0.009", "60100", "0", "deferred-second"
                )
            second_client.create_order.side_effect = create_second
            service = IdempotentOrderService(journal_path=path)
            coordinator = OpenExecutionCoordinator(service)
            readiness = Mock(side_effect=(None, RuntimeError("stream lost")))
            deferred = coordinator.start(
                plan, first_client, second_client, readiness
            )

            restarted = IdempotentOrderService(journal_path=path)
            first_client.query_order.return_value = first
            clients = {
                (plan.first_request.instrument.exchange, plan.first_request.instrument.market_type): first_client,
                (plan.second_request.instrument.exchange, plan.second_request.instrument.market_type): second_client,
            }
            restarted.recover_pending(clients)
            after_restart = OpenExecutionCoordinator(restarted)
            should_not_check = Mock(side_effect=RuntimeError("must confirm first"))
            still_deferred = after_restart.restore(
                restarted.recovery_contexts[0],
                clients,
                should_not_check,
                True,
            )

            self.assertEqual(deferred.status, DualLegStatus.SECOND_DEFERRED)
            self.assertEqual(
                still_deferred.status, DualLegStatus.SECOND_DEFERRED
            )
            should_not_check.assert_not_called()
            second_client.create_order.assert_not_called()

            completed = after_restart.resume(plan.position_id, Mock())

        self.assertEqual(completed.status, DualLegStatus.COMPLETED)
        second_client.create_order.assert_called_once()
        persisted = journal_at_create[0]
        self.assertFalse(
            persisted["contexts"][0]["requires_confirmation"]
        )
        self.assertIn(
            str(plan.second_request.client_order_id),
            {item["client_order_id"] for item in persisted["orders"]},
        )

    def test_second_leg_uses_first_leg_actual_base_fill(self) -> None:
        plan = _plan()
        first_client = Mock()
        second_client = Mock()
        first_client.create_order.side_effect = lambda request: _filled(
            request, "0.008", "60000", "0.48", "open-actual"
        )
        second_client.create_order.side_effect = lambda request: _filled(
            request, str(request.quantity), "60100", "0.4808", "open-second"
        )

        result = OpenExecutionCoordinator().start(plan, first_client, second_client)

        self.assertEqual(result.status, DualLegStatus.COMPLETED)
        request = second_client.create_order.call_args.args[0]
        self.assertEqual(request.quantity, Decimal("0.008"))

    def test_bitget_spot_buy_fill_quantity_drives_binance_second_leg(self) -> None:
        buy = _instrument(Exchange.BITGET, MarketType.SPOT)
        sell = _instrument(Exchange.BINANCE, MarketType.USDT_PERPETUAL)
        opportunity = calculate_opportunity(
            _book(
                buy,
                bids=(("59990", "1"),),
                asks=(("60000", "1"),),
                received_time=NOW,
            ),
            _book(
                sell,
                bids=(("60100", "1"),),
                asks=(("60110", "1"),),
                received_time=NOW,
            ),
            OpportunityRequest(
                base_quantity=Decimal("0.009"),
                quote_amount=None,
                buy_fee_rate=Decimal("0.001"),
                sell_fee_rate=Decimal("0.001"),
                now=NOW,
                max_age=timedelta(seconds=2),
            ),
        )
        first = OrderRequest(
            buy,
            OrderSide.BUY,
            OrderType.MARKET,
            opportunity.buy_leg.order_quantity,
            ClientOrderId("bitget-actual-first"),
            reference_price=opportunity.buy_leg.average_price,
        )
        second = OrderRequest(
            sell,
            OrderSide.SELL,
            OrderType.MARKET,
            opportunity.sell_leg.order_quantity,
            ClientOrderId("binance-actual-second"),
            reference_price=opportunity.sell_leg.average_price,
        )
        plan = ExecutableOpportunity("bitget-actual", opportunity, first, second)
        first_client = Mock()
        second_client = Mock()
        first_client.create_order.return_value = parse_bitget_order(
            {
                "category": "SPOT",
                "symbol": "BTCUSDT",
                "orderId": "bitget-fill",
                "clientOid": str(first.client_order_id),
                "price": "0",
                "qty": "540",
                "orderType": "market",
                "timeInForce": "gtc",
                "side": "buy",
                "cumExecQty": "0.008",
                "cumExecValue": "480",
                "avgPrice": "60000",
                "orderStatus": "filled",
                "feeDetail": [],
                "updatedTime": "1784400000000",
            },
            buy,
            NOW,
            first,
        )
        second_client.create_order.side_effect = lambda request: _filled(
            request, str(request.quantity), "60100", "0", "binance-fill"
        )

        result = OpenExecutionCoordinator().start(
            plan, first_client, second_client
        )

        self.assertEqual(result.status, DualLegStatus.COMPLETED)
        self.assertEqual(
            second_client.create_order.call_args.args[0].quantity,
            Decimal("0.008"),
        )

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
