from decimal import Decimal
import threading
import unittest
from unittest.mock import Mock

from app.domain.enums import Exchange, MarketType
from app.domain.accounts.futures_position import PositionMode
from app.domain.orders.order import FuturesPositionSide, OrderSide
from app.domain.arbitrage.arbitrage_position import ArbitragePosition
from app.domain.orders.order_group import DualLegExecutionResult, DualLegStatus
from app.domain.orders.order_leg import LegRole, successful_leg
from app.workers.market_data_worker import LiveDataWorker
from tests.domain.test_arbitrage_positions import NOW, _filled
from tests.ui.test_stage10_integration import _instrument, _plan


def _binance_product():
    return {
        "symbols": [{
            "symbol": "BTCUSDT", "status": "TRADING",
            "baseAsset": "BTC", "quoteAsset": "USDT",
            "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                {"filterType": "LOT_SIZE", "minQty": "0.001", "maxQty": "100", "stepSize": "0.001"},
                {"filterType": "MIN_NOTIONAL", "minNotional": "5"},
            ],
        }]
    }


def _bitget_product():
    return {
        "code": "00000",
        "data": [{
            "symbol": "BTCUSDT", "category": "SPOT",
            "baseCoin": "BTC", "quoteCoin": "USDT",
            "minOrderQty": "0.001", "maxOrderQty": "100",
            "pricePrecision": "2", "quantityPrecision": "3",
            "minOrderAmount": "5", "status": "online",
        }],
    }


class LiveDataWorkerTests(unittest.TestCase):
    def _worker(self):
        bridge = Mock()
        market_clients = {}
        trading_clients = {}
        websockets = {}
        for key, payload in (
            ((Exchange.BINANCE, MarketType.SPOT), _binance_product()),
            ((Exchange.BITGET, MarketType.SPOT), _bitget_product()),
        ):
            market = Mock()
            market.get_raw_product_info.return_value = payload
            if key[0] is Exchange.BINANCE:
                market.get_order_book.return_value = {
                    "lastUpdateId": 10,
                    "bids": [["59990", "1"]],
                    "asks": [["60000", "1"]],
                }
            market_clients[key] = market
            trading = Mock()
            trading.get_taker_fee_rate.return_value = Decimal("0.001")
            trading_clients[key] = trading
            websockets[key] = Mock()
        worker = LiveDataWorker(
            bridge=bridge,
            market_clients=market_clients,
            account_clients={},
            trading_clients=trading_clients,
            public_websockets=websockets,
        )
        return worker, bridge, websockets

    def test_product_to_order_book_to_gui_opportunity_chain(self) -> None:
        worker, bridge, websockets = self._worker()
        try:
            worker.refresh_products().result(timeout=1)
            worker.select_symbol("BTCUSDT", "600").result(timeout=1)
            worker.handle_market_message(
                (Exchange.BITGET, MarketType.SPOT),
                {
                    "arg": {"instType": "spot", "topic": "books", "symbol": "BTCUSDT"},
                    "action": "snapshot",
                    "data": [{
                        "a": [["60110", "1"]], "b": [["60100", "1"]],
                        "pseq": 0, "seq": 20, "ts": "1784400000000",
                    }],
                    "ts": 1784400000000,
                },
            )
            plans = bridge.publish_opportunities.call_args.args[0]
            self.assertEqual(len(plans), 2)
            self.assertEqual(plans[0].first_request.quantity, Decimal("0.010"))
            plan = plans[0]
            first_order = _filled(
                plan.first_request, "0.010", "60000", "0", "live-first"
            )
            second_order = _filled(
                plan.second_request, "0.010", "60100", "0", "live-second"
            )
            execution = DualLegExecutionResult(
                DualLegStatus.COMPLETED,
                successful_leg(LegRole.FIRST, plan.first_request, first_order),
                successful_leg(LegRole.SECOND, plan.second_request, second_order),
            )
            position = ArbitragePosition.from_execution(
                plan.position_id, execution, NOW
            )
            worker.track_positions((position,))
            worker.handle_market_message(
                (Exchange.BITGET, MarketType.SPOT),
                {
                    "arg": {"instType": "spot", "topic": "books", "symbol": "BTCUSDT"},
                    "action": "snapshot",
                    "data": [{
                        "a": [["60110", "1"]], "b": [["60100", "1"]],
                        "pseq": 0, "seq": 21, "ts": "1784400000001",
                    }],
                    "ts": 1784400000001,
                },
            )
            bridge.publish_position_prices.assert_called_with(
                plan.position_id, Decimal("59990"), Decimal("60110")
            )
            for websocket in websockets.values():
                websocket.subscribe.assert_called()
        finally:
            worker.shutdown()

    def test_start_and_shutdown_own_websocket_lifecycle(self) -> None:
        worker, _bridge, websockets = self._worker()
        initialization = worker.start()
        initialization.result(timeout=1)
        worker.shutdown()
        worker.shutdown()
        for websocket in websockets.values():
            websocket.start.assert_called_once()
            websocket.stop.assert_called_once()

    def test_bitget_private_batch_publishes_each_order_event(self) -> None:
        worker, bridge, _websockets = self._worker()
        try:
            worker.refresh_products().result(timeout=1)
            row = {
                "category": "spot",
                "symbol": "BTCUSDT",
                "orderId": "456",
                "clientOid": "live-private-order",
                "price": "62500.10",
                "qty": "0.010",
                "orderType": "limit",
                "timeInForce": "gtc",
                "side": "buy",
                "cumExecQty": "0.004",
                "cumExecValue": "250.0004",
                "avgPrice": "62500.10",
                "orderStatus": "partially_filled",
                "feeDetail": [],
                "updatedTime": "1784462400000",
            }
            second = dict(row, orderId="457", clientOid="live-private-order-2")

            worker.handle_private_message(
                Exchange.BITGET,
                {
                    "arg": {"instType": "UTA", "topic": "order"},
                    "action": "snapshot",
                    "ts": 1784462400000,
                    "data": [row, second],
                },
            )

            self.assertEqual(bridge.publish_private_order_event.call_count, 2)
        finally:
            worker.shutdown()

    def test_execution_readiness_uses_only_the_requested_private_streams(self) -> None:
        worker, _bridge, _websockets = self._worker()
        binance_spot = Mock(is_connected=True)
        bitget = Mock(is_connected=True)
        unrelated_futures = Mock(is_connected=False)
        worker._private_streams = {
            (Exchange.BINANCE, MarketType.SPOT): binance_spot,
            (Exchange.BINANCE, MarketType.USDT_PERPETUAL): unrelated_futures,
            (Exchange.BITGET, None): bitget,
        }
        worker._started = True
        plan = _plan()

        self.assertTrue(
            worker.is_execution_ready(
                (
                    plan.first_request.instrument,
                    _instrument(Exchange.BITGET, MarketType.SPOT),
                )
            )
        )
        self.assertFalse(
            worker.is_execution_ready(
                (
                    _instrument(Exchange.BINANCE, MarketType.USDT_PERPETUAL),
                    _instrument(Exchange.BITGET, MarketType.SPOT),
                )
            )
        )
        worker.shutdown()

    def test_hedge_mode_sets_explicit_futures_position_side(self) -> None:
        worker, _bridge, _websockets = self._worker()
        instrument = _plan().second_request.instrument
        worker._position_modes[Exchange.BITGET] = PositionMode.HEDGE

        self.assertIs(
            worker._position_side(instrument, OrderSide.BUY),
            FuturesPositionSide.LONG,
        )
        self.assertIs(
            worker._position_side(instrument, OrderSide.SELL),
            FuturesPositionSide.SHORT,
        )
        worker.shutdown()

    def test_bitget_flat_account_settings_supply_position_mode(self) -> None:
        worker, _bridge, _websockets = self._worker()
        account = Mock()
        account.get_settings.return_value = {
            "code": "00000",
            "data": {"holdMode": "one_way_mode"},
        }
        account.get_account.return_value = {
            "code": "00000",
            "requestTime": 1784400000000,
            "data": {"assets": []},
        }
        account.get_positions.return_value = {
            "code": "00000",
            "requestTime": 1784400000001,
            "data": {"list": []},
        }
        worker._account_clients = {(Exchange.BITGET, None): account}
        try:
            worker.refresh_accounts().result(timeout=1)
            self.assertIs(
                worker._position_modes[Exchange.BITGET], PositionMode.ONE_WAY
            )
        finally:
            worker.shutdown()

    def test_private_stream_stop_runs_outside_calling_thread(self) -> None:
        worker, _bridge, _websockets = self._worker()
        calling_thread = threading.get_ident()
        stop_threads: list[int] = []
        private_stream = Mock()
        private_stream.stop.side_effect = lambda: stop_threads.append(
            threading.get_ident()
        )
        worker._private_streams = {(Exchange.BINANCE, MarketType.USDT_PERPETUAL): private_stream}

        worker.shutdown()

        self.assertEqual(len(stop_threads), 1)
        self.assertNotEqual(stop_threads[0], calling_thread)

    def test_snapshot_buffer_has_a_fixed_capacity(self) -> None:
        worker, _bridge, _websockets = self._worker()
        instrument = _instrument(Exchange.BINANCE, MarketType.SPOT)
        try:
            for sequence in range(2_010):
                worker._buffer_update(
                    Mock(instrument=instrument, sequence=sequence)
                )
            buffered = worker._snapshot_buffers[instrument]
            self.assertEqual(len(buffered), 2_000)
            self.assertEqual(min(buffered), 10)
        finally:
            worker.shutdown()

    def test_binance_updates_buffer_while_snapshot_is_in_flight_then_replay(self) -> None:
        worker, _bridge, _websockets = self._worker()
        try:
            worker.refresh_products().result(timeout=1)
            instrument = next(
                item
                for item in worker.instruments
                if item.exchange is Exchange.BINANCE
            )
            with worker._lock:
                worker._selected = (instrument,)
                worker._retain_active_books((instrument,))
                worker._snapshots_pending.add(instrument)

            worker.handle_market_message(
                (Exchange.BINANCE, MarketType.SPOT),
                {
                    "e": "depthUpdate",
                    "E": 1784400000001,
                    "s": "BTCUSDT",
                    "U": 11,
                    "u": 11,
                    "b": [["59995", "2"]],
                    "a": [["60000", "1"]],
                },
            )
            self.assertIn(instrument, worker._snapshot_buffers)

            worker._load_snapshot(instrument)
            snapshot = worker._book(instrument).snapshot()

            self.assertTrue(snapshot.is_valid)
            self.assertEqual(snapshot.sequence, 11)
            self.assertEqual(snapshot.bids[0].price, Decimal("59995"))
            self.assertNotIn(instrument, worker._snapshot_buffers)
        finally:
            worker.shutdown()

    def test_bitget_increment_is_buffered_until_subscription_snapshot(self) -> None:
        worker, _bridge, _websockets = self._worker()
        try:
            worker.refresh_products().result(timeout=1)
            instrument = next(
                item
                for item in worker.instruments
                if item.exchange is Exchange.BITGET
            )
            with worker._lock:
                worker._selected = (instrument,)
                worker._retain_active_books((instrument,))
                worker._snapshots_pending.add(instrument)
            worker.handle_market_message(
                (Exchange.BITGET, MarketType.SPOT),
                {
                    "arg": {"instType": "spot", "topic": "books", "symbol": "BTCUSDT"},
                    "action": "update",
                    "data": [{
                        "a": [["60000", "1"]], "b": [["59995", "2"]],
                        "pseq": 20, "seq": 21, "ts": "1784400000001",
                    }],
                    "ts": 1784400000001,
                },
            )
            worker.handle_market_message(
                (Exchange.BITGET, MarketType.SPOT),
                {
                    "arg": {"instType": "spot", "topic": "books", "symbol": "BTCUSDT"},
                    "action": "snapshot",
                    "data": [{
                        "a": [["60000", "1"]], "b": [["59990", "1"]],
                        "pseq": 0, "seq": 20, "ts": "1784400000000",
                    }],
                    "ts": 1784400000000,
                },
            )
            snapshot = worker._book(instrument).snapshot()
            self.assertTrue(snapshot.is_valid)
            self.assertEqual(snapshot.sequence, 21)
            self.assertEqual(snapshot.bids[0].price, Decimal("59995"))
            self.assertNotIn(instrument, worker._snapshot_buffers)
            self.assertNotIn(instrument, worker._snapshots_pending)
        finally:
            worker.shutdown()


if __name__ == "__main__":
    unittest.main()
