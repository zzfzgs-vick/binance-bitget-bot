from datetime import datetime, timezone
from decimal import Decimal
import logging
import unittest
from unittest.mock import Mock

import requests

from app.domain.enums import Exchange, MarketType, TradingStatus
from app.domain.exceptions import OrderDataError
from app.domain.instruments.instrument import Instrument, TradingRules
from app.domain.orders.client_order_id import ClientOrderId
from app.domain.orders.fill import OrderFill
from app.domain.orders.order import (
    FuturesPositionSide,
    Order,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
)
from app.exchanges.base.exchange_errors import ExchangeApiError
from app.exchanges.binance.mappers.order_mapper import (
    parse_fills as parse_binance_fills,
    parse_private_message as parse_binance_private,
)
from app.exchanges.binance.rest.futures_trading_client import BinanceFuturesTradingClient
from app.exchanges.binance.rest.spot_trading_client import BinanceSpotTradingClient
from app.exchanges.bitget.mappers.order_mapper import (
    parse_fills as parse_bitget_fills,
    private_subscriptions,
    parse_private_message as parse_bitget_private,
)
from app.exchanges.bitget.rest.futures_trading_client import BitgetFuturesTradingClient
from app.exchanges.bitget.rest.spot_trading_client import BitgetSpotTradingClient
from app.infrastructure.security.credential_store import ApiCredentials


NOW = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)


class _Response:
    status_code = 200

    def __init__(self, payload: object) -> None:
        self._payload = payload

    def json(self) -> object:
        return self._payload


def _instrument(exchange: Exchange, market_type: MarketType) -> Instrument:
    return Instrument(
        exchange=exchange,
        market_type=market_type,
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
            Decimal("1"),
        ),
        status=TradingStatus.TRADING,
        raw_status="TRADING",
    )


def _request(exchange: Exchange, market_type: MarketType) -> OrderRequest:
    return OrderRequest(
        instrument=_instrument(exchange, market_type),
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.0109"),
        price=Decimal("62500.19"),
        client_order_id=ClientOrderId(f"stage9-{exchange.value[:3]}-{market_type.value[:3]}"),
        position_side=(
            FuturesPositionSide.LONG
            if market_type is MarketType.USDT_PERPETUAL
            else None
        ),
    )


def _binance_payload(request: OrderRequest, *, status: str = "NEW") -> dict[str, object]:
    return {
        "symbol": "BTCUSDT",
        "orderId": 123,
        "clientOrderId": str(request.client_order_id),
        "price": "62500.10",
        "origQty": "0.010",
        "executedQty": "0.000",
        "cummulativeQuoteQty": "0.000",
        "status": status,
        "timeInForce": "GTC",
        "type": "LIMIT",
        "side": "BUY",
        "updateTime": 1784462400000,
        "fills": [],
    }


def _bitget_query_payload(request: OrderRequest, *, status: str = "new") -> dict[str, object]:
    return {
        "code": "00000",
        "msg": "success",
        "requestTime": 1784462400000,
        "data": {
            "orderId": "456",
            "clientOid": str(request.client_order_id),
            "category": "SPOT" if request.instrument.market_type is MarketType.SPOT else "USDT-FUTURES",
            "symbol": "BTCUSDT",
            "price": "62500.10",
            "qty": "0.010",
            "amount": "625.001",
            "orderType": "limit",
            "side": "buy",
            "cumExecQty": "0",
            "cumExecValue": "0",
            "avgPrice": "0",
            "timeInForce": "gtc",
            "orderStatus": status,
            "feeDetail": [],
            "updatedTime": "1784462400000",
        },
    }


class TradingClientParameterTests(unittest.TestCase):
    def test_signature_and_credentials_are_redacted_from_failure_and_logs(self) -> None:
        session = Mock(spec=requests.Session)
        signatures: list[str] = []

        def response(method: str, url: str, **kwargs: object) -> _Response:
            params = kwargs["params"]
            signature = params["signature"]
            signatures.append(signature)
            return _Response(
                {
                    "code": -1022,
                    "msg": f"bad signature {signature} super-secret",
                }
            )

        session.request.side_effect = response
        logger = logging.getLogger("stage9.order.redaction")
        request = _request(Exchange.BINANCE, MarketType.SPOT)
        client = BinanceSpotTradingClient(
            credentials=ApiCredentials(
                binance_api_key="api-key",
                binance_api_secret="super-secret",
            ),
            session=session,
            clock_ms=lambda: 7,
            logger=logger,
        )
        with self.assertLogs(logger, level="DEBUG") as captured:
            with self.assertRaises(ExchangeApiError) as context:
                client.create_order(request)
        visible = str(context.exception) + "\n" + "\n".join(captured.output)
        self.assertNotIn("super-secret", visible)
        self.assertNotIn(signatures[0], visible)

    def test_binance_spot_create_query_cancel_are_signed_and_normalized(self) -> None:
        session = Mock(spec=requests.Session)
        request = _request(Exchange.BINANCE, MarketType.SPOT)
        session.request.return_value = _Response(_binance_payload(request))
        client = BinanceSpotTradingClient(
            credentials=ApiCredentials(binance_api_key="key", binance_api_secret="secret"),
            session=session,
            clock_ms=lambda: 7,
        )

        order = client.create_order(request)

        args = session.request.call_args
        self.assertEqual(args.args[:2], ("POST", "https://api.binance.com/api/v3/order"))
        params = args.kwargs["params"]
        self.assertEqual(params["quantity"], "0.010")
        self.assertEqual(params["price"], "62500.1")
        self.assertEqual(params["newClientOrderId"], str(request.client_order_id))
        self.assertEqual(params["newOrderRespType"], "FULL")
        self.assertIn("signature", params)
        self.assertEqual(order.status, OrderStatus.NEW)

        client.query_order(request)
        self.assertEqual(session.request.call_args.args[0], "GET")
        self.assertEqual(session.request.call_args.kwargs["params"]["origClientOrderId"], str(request.client_order_id))
        client.cancel_order(request)
        self.assertEqual(session.request.call_args.args[0], "DELETE")

    def test_binance_futures_parameters_include_position_side(self) -> None:
        session = Mock(spec=requests.Session)
        request = _request(Exchange.BINANCE, MarketType.USDT_PERPETUAL)
        session.request.return_value = _Response(_binance_payload(request))
        client = BinanceFuturesTradingClient(
            credentials=ApiCredentials(binance_api_key="key", binance_api_secret="secret"),
            session=session,
            clock_ms=lambda: 8,
        )
        client.create_order(request)
        args = session.request.call_args
        self.assertEqual(args.args[1], "https://fapi.binance.com/fapi/v1/order")
        self.assertEqual(args.kwargs["params"]["positionSide"], "LONG")
        self.assertEqual(args.kwargs["params"]["newOrderRespType"], "RESULT")

    def test_bitget_spot_and_futures_use_uta_order_endpoints(self) -> None:
        credentials = ApiCredentials(
            bitget_api_key="key",
            bitget_api_secret="secret",
            bitget_api_passphrase="passphrase",
        )
        for client_type, market_type, category in (
            (BitgetSpotTradingClient, MarketType.SPOT, "SPOT"),
            (BitgetFuturesTradingClient, MarketType.USDT_PERPETUAL, "USDT-FUTURES"),
        ):
            with self.subTest(market_type=market_type):
                session = Mock(spec=requests.Session)
                request = _request(Exchange.BITGET, market_type)
                session.request.side_effect = [
                    _Response({"code": "00000", "msg": "success", "requestTime": 1784462400000, "data": {"clientOid": str(request.client_order_id), "orderId": "456"}}),
                    _Response(_bitget_query_payload(request)),
                    _Response(_bitget_query_payload(request)),
                    _Response({"code": "00000", "msg": "success", "requestTime": 1784462400001, "data": {"clientOid": str(request.client_order_id), "orderId": "456"}}),
                ]
                client = client_type(credentials=credentials, session=session, clock_ms=lambda: 9)
                submitted = client.create_order(request)
                args = session.request.call_args_list[0]
                self.assertEqual(args.args[1], "https://api.bitget.com/api/v3/trade/place-order")
                self.assertIn('"category":"' + category + '"', args.kwargs["data"])
                self.assertIn('"clientOid":"' + str(request.client_order_id) + '"', args.kwargs["data"])
                self.assertIn('"qty":"0.010"', args.kwargs["data"])
                self.assertEqual(submitted.status, OrderStatus.SUBMITTED)

                queried = client.query_order(request)
                self.assertEqual(session.request.call_args.args[1], "https://api.bitget.com/api/v3/trade/order-info")
                self.assertEqual(queried.status, OrderStatus.NEW)
                client.cancel_order(request)
                self.assertEqual(session.request.call_args.args[1], "https://api.bitget.com/api/v3/trade/cancel-order")

    def test_bitget_spot_market_buy_converts_base_quantity_to_quote_quantity(self) -> None:
        session = Mock(spec=requests.Session)
        request = OrderRequest(
            instrument=_instrument(Exchange.BITGET, MarketType.SPOT),
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.0109"),
            reference_price=Decimal("62500.19"),
            client_order_id=ClientOrderId("stage9-bit-market"),
        )
        session.request.return_value = _Response(
            {"code": "00000", "msg": "success", "requestTime": 1784462400000, "data": {"clientOid": str(request.client_order_id), "orderId": "457"}}
        )
        client = BitgetSpotTradingClient(
            credentials=ApiCredentials(bitget_api_key="key", bitget_api_secret="secret", bitget_api_passphrase="passphrase"),
            session=session,
            clock_ms=lambda: 9,
        )
        client.create_order(request)
        self.assertIn('"qty":"625.0010"', session.request.call_args_list[0].kwargs["data"])
        self.assertEqual(session.request.call_count, 1)

    def test_futures_close_sends_reduce_only_in_one_way_mode(self) -> None:
        credentials = ApiCredentials(
            binance_api_key="key", binance_api_secret="secret",
            bitget_api_key="key", bitget_api_secret="secret", bitget_api_passphrase="pass",
        )
        for client_type, exchange, expected in (
            (BinanceFuturesTradingClient, Exchange.BINANCE, 'true'),
            (BitgetFuturesTradingClient, Exchange.BITGET, 'yes'),
        ):
            with self.subTest(exchange=exchange):
                session = Mock(spec=requests.Session)
                request = OrderRequest(
                    instrument=_instrument(exchange, MarketType.USDT_PERPETUAL),
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    quantity=Decimal("0.01"),
                    reference_price=Decimal("62500"),
                    client_order_id=ClientOrderId(f"close-{exchange.value}"),
                    reduce_only=True,
                )
                if exchange is Exchange.BINANCE:
                    session.request.return_value = _Response(_binance_payload(request))
                else:
                    session.request.return_value = _Response(
                        {"code":"00000","msg":"success","data":{"orderId":"9","clientOid":str(request.client_order_id)}}
                    )
                client_type(credentials=credentials, session=session, clock_ms=lambda: 9).create_order(request)
                first = session.request.call_args_list[0]
                visible = str(first.kwargs.get("params")) + str(first.kwargs.get("data"))
                self.assertIn("reduceOnly", visible)
                self.assertIn(expected, visible)


class PrivateOrderMapperTests(unittest.TestCase):
    def test_bitget_private_control_error_is_not_silently_ignored(self) -> None:
        with self.assertRaisesRegex(OrderDataError, "control event 'error'"):
            parse_bitget_private(
                {"event": "error", "code": "30001", "msg": "bad subscription"},
                {},
                NOW,
            )

    def test_rest_fill_history_is_normalized_for_both_exchanges(self) -> None:
        binance = _instrument(Exchange.BINANCE, MarketType.SPOT)
        binance_fills = parse_binance_fills(
            [{"symbol": "BTCUSDT", "id": 77, "orderId": 123, "price": "62500.10", "qty": "0.004", "commission": "0.25", "commissionAsset": "USDT", "time": 1784462400000}],
            binance,
            ClientOrderId("stage9-bin-fill"),
            "123",
            NOW,
        )
        self.assertEqual(binance_fills[0].fill.quantity, Decimal("0.004"))

        bitget = _instrument(Exchange.BITGET, MarketType.USDT_PERPETUAL)
        bitget_fills = parse_bitget_fills(
            {"code": "00000", "msg": "success", "data": {"list": [{"category": "usdt-futures", "symbol": "BTCUSDT", "orderId": "456", "clientOid": "stage9-bit-fill", "execId": "fill-1", "execPrice": "62500.10", "execQty": "0.004", "feeDetail": [{"feeCoin": "USDT", "fee": "0.25"}], "createdTime": "1784462400000"}]}},
            {(MarketType.USDT_PERPETUAL, "BTCUSDT"): bitget},
        )
        self.assertEqual(bitget_fills[0].fill.fee, Decimal("0.25"))

    def test_binance_spot_and_futures_private_updates_map_status_and_fill(self) -> None:
        for market_type, event in (
            (
                MarketType.SPOT,
                {"subscriptionId": 0, "event": {"e": "executionReport", "E": 1784462400000, "s": "BTCUSDT", "c": "stage9-bin-ws", "S": "BUY", "o": "LIMIT", "f": "GTC", "q": "0.010", "p": "62500.10", "x": "TRADE", "X": "FILLED", "i": 123, "l": "0.010", "z": "0.010", "L": "62500.10", "n": "0.625001", "N": "USDT", "T": 1784462400000, "t": 77, "Z": "625.001"}},
            ),
            (
                MarketType.USDT_PERPETUAL,
                {"e": "ORDER_TRADE_UPDATE", "E": 1784462400000, "T": 1784462400000, "o": {"s": "BTCUSDT", "c": "stage9-bin-ws", "S": "BUY", "o": "LIMIT", "f": "GTC", "q": "0.010", "p": "62500.10", "x": "TRADE", "X": "FILLED", "i": 123, "l": "0.010", "z": "0.010", "L": "62500.10", "n": "0.625001", "N": "USDT", "T": 1784462400000, "t": 77, "ap": "62500.10"}},
            ),
        ):
            with self.subTest(market_type=market_type):
                instrument = _instrument(Exchange.BINANCE, market_type)
                order = parse_binance_private(
                    event,
                    {(market_type, "BTCUSDT"): instrument},
                    NOW,
                )
                self.assertIsInstance(order, Order)
                self.assertEqual(order.status, OrderStatus.FILLED)
                self.assertEqual(order.cumulative_filled_quantity, Decimal("0.010"))
                self.assertEqual(order.fills[0].price, Decimal("62500.10"))

    def test_bitget_order_and_fill_channels_are_normalized(self) -> None:
        self.assertEqual(
            private_subscriptions(),
            ({"instType": "UTA", "topic": "order"}, {"instType": "UTA", "topic": "fill"}),
        )
        instrument = _instrument(Exchange.BITGET, MarketType.USDT_PERPETUAL)
        spot_instrument = _instrument(Exchange.BITGET, MarketType.SPOT)
        instruments = {
            (MarketType.SPOT, "BTCUSDT"): spot_instrument,
            (MarketType.USDT_PERPETUAL, "BTCUSDT"): instrument,
        }
        (order,) = parse_bitget_private(
            {"arg": {"instType": "UTA", "topic": "order"}, "action": "snapshot", "ts": 1784462400000, "data": [{"category": "usdt-futures", "symbol": "BTCUSDT", "orderId": "456", "clientOid": "stage9-bit-ws", "price": "62500.10", "qty": "0.010", "orderType": "limit", "timeInForce": "gtc", "side": "sell", "cumExecQty": "0.004", "cumExecValue": "250.0004", "avgPrice": "62500.10", "orderStatus": "partially_filled", "feeDetail": [{"feeCoin": "USDT", "fee": "0.25"}], "updatedTime": "1784462400000"}]},
            instruments,
            NOW,
        )
        self.assertIsInstance(order, Order)
        self.assertIs(order.instrument, instrument)
        self.assertEqual(order.status, OrderStatus.PARTIALLY_FILLED)
        self.assertEqual(order.average_price, Decimal("62500.10"))

        (fill,) = parse_bitget_private(
            {"arg": {"instType": "UTA", "topic": "fill"}, "action": "snapshot", "ts": 1784462400001, "data": [{"category": "usdt-futures", "symbol": "BTCUSDT", "orderId": "456", "clientOid": "stage9-bit-ws", "execId": "fill-1", "execPrice": "62500.10", "execQty": "0.004", "feeDetail": [{"feeCoin": "USDT", "fee": "0.25"}], "execTime": "1784462400001"}]},
            instruments,
            NOW,
        )
        self.assertIsInstance(fill, OrderFill)
        self.assertEqual(fill.fill.quantity, Decimal("0.004"))

    def test_unknown_order_status_and_float_payload_are_rejected(self) -> None:
        instrument = _instrument(Exchange.BITGET, MarketType.SPOT)
        with self.assertRaisesRegex(OrderDataError, "unknown Bitget order status"):
            parse_bitget_private(
                {"arg": {"instType": "UTA", "topic": "order"}, "action": "snapshot", "ts": 1, "data": [{"category": "spot", "symbol": "BTCUSDT", "orderId": "1", "clientOid": "bad-status", "price": "1", "qty": "1", "orderType": "limit", "timeInForce": "gtc", "side": "buy", "cumExecQty": "0", "cumExecValue": "0", "avgPrice": "0", "orderStatus": "mystery", "feeDetail": [], "updatedTime": "1"}]},
                {(MarketType.SPOT, "BTCUSDT"): instrument},
                NOW,
            )
        with self.assertRaisesRegex(OrderDataError, "decimal string"):
            parse_bitget_private(
                {"arg": {"instType": "UTA", "topic": "fill"}, "action": "snapshot", "ts": 1, "data": [{"category": "spot", "symbol": "BTCUSDT", "orderId": "1", "clientOid": "bad-float", "execId": "fill", "execPrice": 1.1, "execQty": "1", "feeDetail": [{"feeCoin": "USDT", "fee": "0"}], "execTime": "1"}]},
                {(MarketType.SPOT, "BTCUSDT"): instrument},
                NOW,
            )


if __name__ == "__main__":
    unittest.main()
