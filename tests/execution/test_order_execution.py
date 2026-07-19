from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest
from unittest.mock import Mock
import threading
from pathlib import Path
from tempfile import TemporaryDirectory

from app.domain.enums import Exchange, MarketType, TradingStatus
from app.domain.exceptions import OrderDataError
from app.domain.instruments.instrument import Instrument, TradingRules
from app.domain.orders.client_order_id import ClientOrderId
from app.domain.orders.fill import Fill, OrderFill
from app.domain.orders.order import (
    Order,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from app.execution.dual_leg_executor import DualLegExecutor, DualLegStatus
from app.execution.client_order_id_factory import ClientOrderIdFactory
from app.execution.fill_tracker import OrderReconciler, ReconcileResult
from app.execution.order_recovery_service import (
    DuplicateOrderSubmissionError,
    IdempotentOrderService,
    OrderStateUnknownError,
)
from app.exchanges.base.exchange_errors import (
    ExchangeApiError,
    ExchangeResponseError,
    ExchangeTimeoutError,
)


NOW = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)


def _instrument(exchange: Exchange, *, multiplier: str = "1") -> Instrument:
    return Instrument(
        exchange=exchange,
        market_type=MarketType.SPOT,
        raw_symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        settlement_asset="USDT",
        rules=TradingRules(
            Decimal("0.1"),
            Decimal("0.001"),
            Decimal("0.001"),
            Decimal("100"),
            Decimal("5"),
            Decimal(multiplier),
        ),
        status=TradingStatus.TRADING,
        raw_status="TRADING",
    )


def _request(
    exchange: Exchange,
    side: OrderSide,
    client_id: str,
    *,
    quantity: str = "0.010",
) -> OrderRequest:
    return OrderRequest(
        instrument=_instrument(exchange),
        side=side,
        order_type=OrderType.LIMIT,
        quantity=Decimal(quantity),
        price=Decimal("62500.10"),
        client_order_id=ClientOrderId(client_id),
    )


def _order(
    request: OrderRequest,
    status: OrderStatus,
    *,
    cumulative: str,
    order_id: str = "100",
    updated_time: datetime = NOW,
    fills: tuple[Fill, ...] = (),
    fee: str = "0",
) -> Order:
    quantity = Decimal(cumulative)
    return Order(
        instrument=request.instrument,
        client_order_id=request.client_order_id,
        exchange_order_id=order_id,
        side=request.side,
        order_type=request.order_type,
        time_in_force=TimeInForce.GTC,
        original_quantity=request.quantity,
        price=request.price,
        status=status,
        cumulative_filled_quantity=quantity,
        average_price=Decimal("62500.10") if quantity else Decimal(0),
        cumulative_fee=Decimal(fee),
        fee_asset="USDT" if Decimal(fee) or fills else None,
        fills=fills,
        updated_time=updated_time,
    )


class IdempotentSubmissionTests(unittest.TestCase):
    def test_operation_recovery_context_survives_restart(self) -> None:
        first = _request(Exchange.BINANCE, OrderSide.BUY, "context-first")
        second = _request(Exchange.BITGET, OrderSide.SELL, "context-second")
        with TemporaryDirectory() as directory:
            journal = Path(directory) / "orders.json"
            service = IdempotentOrderService(journal_path=journal)
            service.register_context("position-1", "open", (first, second))

            restarted = IdempotentOrderService(journal_path=journal)

            (context,) = restarted.recovery_contexts
            self.assertEqual(context.operation_id, "position-1")
            self.assertEqual(context.kind, "open")
            self.assertEqual(context.requests, (first, second))

    def test_restart_queries_persisted_client_id_before_any_create(self) -> None:
        request = _request(Exchange.BINANCE, OrderSide.BUY, "restart-original")
        with TemporaryDirectory() as directory:
            journal = Path(directory) / "orders.json"
            first_client = Mock()
            first_client.create_order.side_effect = ExchangeTimeoutError("timeout")
            first_client.query_order.side_effect = ExchangeResponseError("offline")
            first = IdempotentOrderService(journal_path=journal)
            with self.assertRaises(OrderStateUnknownError):
                first.submit(first_client, request)

            second_client = Mock()
            second_client.query_order.return_value = _order(
                request, OrderStatus.FILLED, cumulative="0.010"
            )
            restarted = IdempotentOrderService(journal_path=journal)
            recovered = restarted.submit(second_client, request)

            self.assertEqual(recovered.status, OrderStatus.FILLED)
            second_client.create_order.assert_not_called()
            second_client.query_order.assert_called_once_with(request)
            self.assertEqual(restarted.pending_requests, ())

    def test_client_order_id_factory_is_short_and_unique_per_leg(self) -> None:
        factory = ClientOrderIdFactory(clock_ms=lambda: 1784462400000)
        first = factory.create("a")
        second = factory.create("b")
        self.assertNotEqual(first, second)
        self.assertLessEqual(len(str(first)), 32)

    def test_duplicate_submit_returns_known_order_without_second_create(self) -> None:
        request = _request(Exchange.BINANCE, OrderSide.BUY, "idem-known")
        client = Mock()
        client.create_order.return_value = _order(
            request, OrderStatus.NEW, cumulative="0"
        )
        service = IdempotentOrderService()

        first = service.submit(client, request)
        second = service.submit(client, request)

        self.assertIs(first, second)
        client.create_order.assert_called_once()
        client.query_order.assert_not_called()

    def test_concurrent_duplicate_is_claimed_before_network_submission(self) -> None:
        request = _request(Exchange.BINANCE, OrderSide.BUY, "idem-concurrent")
        client = Mock()
        started = threading.Event()
        release = threading.Event()

        def create_order(submitted: OrderRequest) -> Order:
            started.set()
            self.assertTrue(release.wait(timeout=2))
            return _order(submitted, OrderStatus.NEW, cumulative="0")

        client.create_order.side_effect = create_order
        service = IdempotentOrderService()
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(service.submit, client, request)
            self.assertTrue(started.wait(timeout=2))
            second = executor.submit(service.submit, client, request)
            with self.assertRaises(DuplicateOrderSubmissionError):
                second.result(timeout=2)
            release.set()
            self.assertEqual(first.result(timeout=2).status, OrderStatus.NEW)
        client.create_order.assert_called_once()

    def test_timeout_queries_by_same_client_id_and_never_blindly_resubmits(self) -> None:
        request = _request(Exchange.BITGET, OrderSide.BUY, "idem-timeout")
        client = Mock()
        client.create_order.side_effect = ExchangeTimeoutError("timeout")
        client.query_order.return_value = _order(
            request, OrderStatus.NEW, cumulative="0"
        )
        service = IdempotentOrderService()

        recovered = service.submit(client, request)
        duplicate = service.submit(client, request)

        self.assertEqual(recovered.status, OrderStatus.NEW)
        self.assertIs(recovered, duplicate)
        client.create_order.assert_called_once()
        client.query_order.assert_called_once_with(request)

    def test_unknown_after_timeout_stays_query_only_on_later_attempt(self) -> None:
        request = _request(Exchange.BINANCE, OrderSide.SELL, "idem-unknown")
        client = Mock()
        client.create_order.side_effect = ExchangeTimeoutError("timeout")
        client.query_order.side_effect = ExchangeResponseError("query unavailable")
        service = IdempotentOrderService()

        with self.assertRaisesRegex(OrderStateUnknownError, "must not be resubmitted"):
            service.submit(client, request)
        with self.assertRaises(OrderStateUnknownError):
            service.submit(client, request)

        client.create_order.assert_called_once()
        self.assertEqual(client.query_order.call_count, 2)

    def test_exchange_timeout_code_also_queries_instead_of_resubmitting(self) -> None:
        for code in ("25001", "40010", "40725", "45001"):
            with self.subTest(code=code):
                request = _request(
                    Exchange.BITGET,
                    OrderSide.BUY,
                    f"idem-api-{code}",
                )
                client = Mock()
                client.create_order.side_effect = ExchangeApiError(
                    "Bitget", code, "submission outcome unknown"
                )
                client.query_order.return_value = _order(
                    request, OrderStatus.NEW, cumulative="0"
                )
                order = IdempotentOrderService().submit(client, request)
                self.assertEqual(order.status, OrderStatus.NEW)
                client.create_order.assert_called_once()
                client.query_order.assert_called_once()

    def test_transport_failure_is_also_query_only(self) -> None:
        request = _request(Exchange.BINANCE, OrderSide.BUY, "idem-transport")
        client = Mock()
        client.create_order.side_effect = ExchangeResponseError("connection reset")
        client.query_order.return_value = _order(
            request, OrderStatus.NEW, cumulative="0"
        )
        order = IdempotentOrderService().submit(client, request)
        self.assertEqual(order.status, OrderStatus.NEW)
        client.create_order.assert_called_once()
        client.query_order.assert_called_once()

    def test_definite_rejection_still_blocks_a_second_create_with_same_id(self) -> None:
        request = _request(Exchange.BINANCE, OrderSide.BUY, "idem-rejected")
        client = Mock()
        client.create_order.side_effect = ExchangeApiError(
            "Binance", -2010, "order rejected"
        )
        service = IdempotentOrderService()
        with self.assertRaises(ExchangeApiError):
            service.submit(client, request)
        with self.assertRaises(DuplicateOrderSubmissionError):
            service.submit(client, request)
        client.create_order.assert_called_once()

    def test_reusing_client_id_for_different_request_is_rejected(self) -> None:
        original = _request(Exchange.BINANCE, OrderSide.BUY, "idem-conflict")
        client = Mock()
        client.create_order.return_value = _order(
            original, OrderStatus.NEW, cumulative="0"
        )
        service = IdempotentOrderService()
        service.submit(client, original)
        with self.assertRaisesRegex(OrderDataError, "different order request"):
            service.submit(client, replace(original, quantity=Decimal("0.020")))
        client.create_order.assert_called_once()


class OrderReconciliationTests(unittest.TestCase):
    def test_fill_newer_than_snapshot_adds_its_full_quantity(self) -> None:
        request = _request(Exchange.BITGET, OrderSide.BUY, "fill-after-snapshot")
        store = OrderReconciler()
        store.apply(
            _order(
                request,
                OrderStatus.PARTIALLY_FILLED,
                cumulative="0.004",
                updated_time=NOW,
            )
        )
        result = store.apply(
            OrderFill(
                request.instrument,
                request.client_order_id,
                "100",
                Fill(
                    "new-fill",
                    Decimal("62500.10"),
                    Decimal("0.006"),
                    Decimal("0.375"),
                    "USDT",
                    NOW + timedelta(milliseconds=1),
                ),
            )
        )
        self.assertEqual(result, ReconcileResult.APPLIED)
        current = store.get(request)
        self.assertEqual(current.cumulative_filled_quantity, Decimal("0.010"))
        self.assertEqual(current.status, OrderStatus.FILLED)

    def test_market_fill_does_not_infer_terminal_status_without_order_update(self) -> None:
        request = OrderRequest(
            instrument=_instrument(Exchange.BITGET),
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.010"),
            reference_price=Decimal("62500.10"),
            client_order_id=ClientOrderId("market-not-terminal"),
        )
        store = OrderReconciler()
        store.apply(_order(request, OrderStatus.SUBMITTED, cumulative="0"))
        store.apply(
            OrderFill(
                request.instrument,
                request.client_order_id,
                "100",
                Fill(
                    "market-fill",
                    Decimal("62500.10"),
                    Decimal("0.010"),
                    Decimal("0.625001"),
                    "USDT",
                    NOW + timedelta(milliseconds=1),
                ),
            )
        )
        self.assertEqual(store.get(request).status, OrderStatus.PARTIALLY_FILLED)

    def test_fill_fee_is_added_when_status_update_omitted_its_fee(self) -> None:
        request = _request(Exchange.BITGET, OrderSide.BUY, "late-fee")
        store = OrderReconciler()
        store.apply(
            _order(
                request,
                OrderStatus.PARTIALLY_FILLED,
                cumulative="0.004",
                fee="0",
            )
        )
        event = OrderFill(
            request.instrument,
            request.client_order_id,
            "100",
            Fill(
                "late-fill",
                Decimal("62500.10"),
                Decimal("0.004"),
                Decimal("0.25"),
                "USDT",
                NOW + timedelta(milliseconds=1),
            ),
        )
        self.assertEqual(store.apply(event), ReconcileResult.APPLIED)
        self.assertEqual(store.get(request).cumulative_fee, Decimal("0.25"))

    def test_rest_snapshot_and_websocket_partial_full_updates_merge_once(self) -> None:
        request = _request(Exchange.BITGET, OrderSide.BUY, "reconcile")
        store = OrderReconciler()
        rest = _order(request, OrderStatus.NEW, cumulative="0")
        self.assertEqual(store.apply(rest), ReconcileResult.APPLIED)

        partial_fill = Fill(
            "fill-1",
            Decimal("62500.10"),
            Decimal("0.004"),
            Decimal("0.25"),
            "USDT",
            NOW + timedelta(milliseconds=1),
        )
        partial = _order(
            request,
            OrderStatus.PARTIALLY_FILLED,
            cumulative="0.004",
            updated_time=NOW + timedelta(milliseconds=1),
            fee="0.25",
        )
        self.assertEqual(store.apply(partial), ReconcileResult.APPLIED)
        event = OrderFill(
            request.instrument,
            request.client_order_id,
            "100",
            partial_fill,
        )
        self.assertEqual(store.apply(event), ReconcileResult.APPLIED)
        self.assertEqual(store.apply(event), ReconcileResult.DUPLICATE)
        self.assertEqual(store.get(request).cumulative_fee, Decimal("0.25"))

        final_fill = Fill(
            "fill-2",
            Decimal("62500.20"),
            Decimal("0.006"),
            Decimal("0.375"),
            "USDT",
            NOW + timedelta(milliseconds=2),
        )
        self.assertEqual(
            store.apply(
                OrderFill(
                    request.instrument,
                    request.client_order_id,
                    "100",
                    final_fill,
                )
            ),
            ReconcileResult.APPLIED,
        )
        current = store.get(request)
        self.assertEqual(current.status, OrderStatus.FILLED)
        self.assertEqual(current.cumulative_filled_quantity, Decimal("0.010"))
        self.assertEqual(current.cumulative_fee, Decimal("0.625"))
        self.assertEqual(current.average_price, Decimal("62500.16"))

    def test_fee_coverage_survives_same_quantity_snapshot_without_fee_field(self) -> None:
        request = _request(Exchange.BITGET, OrderSide.BUY, "fee-boundary")
        store = OrderReconciler()
        store.apply(
            _order(
                request,
                OrderStatus.PARTIALLY_FILLED,
                cumulative="0.004",
                fee="0.25",
                updated_time=NOW,
            )
        )
        store.apply(
            _order(
                request,
                OrderStatus.PARTIALLY_FILLED,
                cumulative="0.004",
                fee="0",
                updated_time=NOW + timedelta(milliseconds=2),
            )
        )
        store.apply(
            OrderFill(
                request.instrument,
                request.client_order_id,
                "100",
                Fill(
                    "covered-fill",
                    Decimal("62500.10"),
                    Decimal("0.004"),
                    Decimal("0.25"),
                    "USDT",
                    NOW + timedelta(milliseconds=1),
                ),
            )
        )
        self.assertEqual(store.get(request).cumulative_fee, Decimal("0.25"))

    def test_out_of_order_regression_and_unknown_fill_are_not_applied(self) -> None:
        request = _request(Exchange.BINANCE, OrderSide.SELL, "out-of-order")
        store = OrderReconciler()
        partial = _order(
            request,
            OrderStatus.PARTIALLY_FILLED,
            cumulative="0.004",
            updated_time=NOW + timedelta(seconds=1),
        )
        store.apply(partial)
        older = _order(request, OrderStatus.NEW, cumulative="0", updated_time=NOW)
        self.assertEqual(store.apply(older), ReconcileResult.OUT_OF_ORDER)

        filled = _order(
            request,
            OrderStatus.FILLED,
            cumulative="0.010",
            updated_time=NOW + timedelta(seconds=2),
        )
        store.apply(filled)
        canceled = _order(
            request,
            OrderStatus.CANCELED,
            cumulative="0.010",
            updated_time=NOW + timedelta(seconds=3),
        )
        self.assertEqual(store.apply(canceled), ReconcileResult.OUT_OF_ORDER)

        unknown_request = _request(Exchange.BINANCE, OrderSide.BUY, "unknown-fill")
        fill = Fill("fill", Decimal("1"), Decimal("0.001"), Decimal("0"), "USDT", NOW)
        self.assertEqual(
            store.apply(OrderFill(unknown_request.instrument, unknown_request.client_order_id, "2", fill)),
            ReconcileResult.SNAPSHOT_REQUIRED,
        )


class DualLegExecutionTests(unittest.TestCase):
    def test_two_filled_legs_complete_in_explicit_order(self) -> None:
        first = _request(Exchange.BINANCE, OrderSide.BUY, "dual-first")
        second = _request(Exchange.BITGET, OrderSide.SELL, "dual-second")
        calls: list[str] = []
        first_client = Mock()
        second_client = Mock()
        first_client.create_order.side_effect = lambda request: (
            calls.append("first") or _order(request, OrderStatus.FILLED, cumulative="0.010")
        )
        second_client.create_order.side_effect = lambda request: (
            calls.append("second") or _order(request, OrderStatus.FILLED, cumulative="0.010", order_id="200")
        )

        result = DualLegExecutor().execute(
            first_client,
            first,
            second_client,
            second,
        )

        self.assertEqual(calls, ["first", "second"])
        self.assertEqual(result.status, DualLegStatus.COMPLETED)
        self.assertEqual(result.first.order.status, OrderStatus.FILLED)
        self.assertEqual(result.second.order.status, OrderStatus.FILLED)

    def test_first_failure_prevents_second_submission(self) -> None:
        first = _request(Exchange.BINANCE, OrderSide.BUY, "dual-fail-first")
        second = _request(Exchange.BITGET, OrderSide.SELL, "dual-never")
        first_client = Mock()
        second_client = Mock()
        first_client.create_order.side_effect = ExchangeApiError(
            "Binance", -2010, "rejected"
        )

        result = DualLegExecutor().execute(first_client, first, second_client, second)

        self.assertEqual(result.status, DualLegStatus.FIRST_FAILED)
        self.assertIsNone(result.second)
        second_client.create_order.assert_not_called()

    def test_second_failure_is_recorded_without_compensating_trade(self) -> None:
        first = _request(Exchange.BINANCE, OrderSide.BUY, "dual-ok-first")
        second = _request(Exchange.BITGET, OrderSide.SELL, "dual-fail-second")
        first_client = Mock()
        second_client = Mock()
        first_client.create_order.return_value = _order(first, OrderStatus.FILLED, cumulative="0.010")
        second_client.create_order.side_effect = ExchangeApiError(
            "Bitget", "25200", "rejected"
        )

        result = DualLegExecutor().execute(first_client, first, second_client, second)

        self.assertEqual(result.status, DualLegStatus.SECOND_FAILED)
        self.assertIsNotNone(result.second)
        self.assertIsNone(result.second.order)

    def test_partial_first_leg_stops_and_filled_quantity_mismatch_is_explicit(self) -> None:
        first = _request(Exchange.BINANCE, OrderSide.BUY, "dual-partial")
        second = _request(Exchange.BITGET, OrderSide.SELL, "dual-partial-second")
        first_client = Mock()
        second_client = Mock()
        first_client.create_order.return_value = _order(first, OrderStatus.PARTIALLY_FILLED, cumulative="0.004")
        partial = DualLegExecutor().execute(first_client, first, second_client, second)
        self.assertEqual(partial.status, DualLegStatus.FIRST_INCOMPLETE)
        second_client.create_order.assert_not_called()

    def test_actual_fill_quantity_mismatch_is_reported_after_both_legs(self) -> None:
        first = _request(Exchange.BINANCE, OrderSide.BUY, "actual-first")
        second = OrderRequest(
            instrument=_instrument(Exchange.BITGET),
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.010"),
            reference_price=Decimal("62500.10"),
            client_order_id=ClientOrderId("actual-second"),
        )
        first_client = Mock()
        second_client = Mock()
        first_client.create_order.return_value = _order(
            first, OrderStatus.FILLED, cumulative="0.010"
        )
        second_client.create_order.return_value = _order(
            second,
            OrderStatus.FILLED,
            cumulative="0.009",
            order_id="200",
        )
        result = DualLegExecutor().execute(
            first_client, first, second_client, second
        )
        self.assertEqual(result.status, DualLegStatus.QUANTITY_MISMATCH)
        first_client.create_order.assert_called_once()
        second_client.create_order.assert_called_once()

        mismatch_second = replace(second, quantity=Decimal("0.009"))
        first_client = Mock()
        second_client = Mock()
        mismatch = DualLegExecutor().execute(first_client, first, second_client, mismatch_second)
        self.assertEqual(mismatch.status, DualLegStatus.QUANTITY_MISMATCH)
        self.assertIsNone(mismatch.first.order)
        self.assertIsNone(mismatch.second.order)
        first_client.create_order.assert_not_called()
        second_client.create_order.assert_not_called()

    def test_second_leg_preflight_failure_happens_before_first_submission(self) -> None:
        first = _request(Exchange.BINANCE, OrderSide.BUY, "preflight-first")
        second = replace(
            _request(Exchange.BITGET, OrderSide.SELL, "preflight-second"),
            quantity=Decimal("0.0001"),
        )
        first_client = Mock()
        second_client = Mock()
        result = DualLegExecutor().execute(
            first_client, first, second_client, second
        )
        self.assertEqual(result.status, DualLegStatus.PREFLIGHT_FAILED)
        first_client.create_order.assert_not_called()
        second_client.create_order.assert_not_called()


if __name__ == "__main__":
    unittest.main()
