from __future__ import annotations

import asyncio
import io
import json
import logging
import threading
import time
import unittest
from collections.abc import Callable
from unittest.mock import Mock

from app.exchanges.binance.constants import BINANCE_SPOT_PUBLIC_WS_URL
from app.exchanges.binance.constants import (
    BINANCE_FUTURES_PRIVATE_WS_BASE_URL,
    BINANCE_FUTURES_PUBLIC_WS_URL,
    BINANCE_SPOT_PRIVATE_WS_URL,
)
from app.exchanges.binance.websocket.futures_public_ws import (
    BinanceFuturesPublicWebSocketClient,
)
from app.exchanges.binance.websocket.futures_private_ws import (
    BinanceFuturesPrivateWebSocketClient,
    BinanceFuturesPrivateStream,
)
from app.exchanges.binance.websocket.spot_public_ws import (
    BinanceSpotPublicWebSocketClient,
)
from app.exchanges.binance.websocket.spot_private_ws import (
    BinanceSpotPrivateWebSocketClient,
)
from app.exchanges.bitget.constants import (
    BITGET_PRIVATE_WS_URL,
    BITGET_PUBLIC_WS_URL,
)
from app.exchanges.bitget.websocket.client import build_login_message
from app.exchanges.bitget.websocket.spot_private_ws import (
    BitgetSpotPrivateWebSocketClient,
)
from app.exchanges.bitget.websocket.spot_public_ws import (
    BitgetSpotPublicWebSocketClient,
)
from app.infrastructure.security.credential_store import ApiCredentials
from app.exchanges.base.exchange_errors import ExchangeCredentialsError
from app.exchanges.base.websockets_client import (
    WebSocketClientError,
    WebSocketProtocolError,
    WebSocketTimeoutError,
)


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.incoming: asyncio.Queue[object] = asyncio.Queue()
        self.closed = False
        self.ping_count = 0

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def recv(self) -> str:
        item = await self.incoming.get()
        if isinstance(item, BaseException):
            raise item
        return str(item)

    async def ping(self) -> asyncio.Future[None]:
        self.ping_count += 1
        future = asyncio.get_running_loop().create_future()
        future.set_result(None)
        return future

    async def close(self) -> None:
        self.closed = True


class _Connection:
    def __init__(self, websocket: _FakeWebSocket) -> None:
        self.websocket = websocket

    async def __aenter__(self) -> _FakeWebSocket:
        return self.websocket

    async def __aexit__(self, *args: object) -> None:
        await self.websocket.close()


class _FailingConnection:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def __aenter__(self) -> _FakeWebSocket:
        raise self.error

    async def __aexit__(self, *args: object) -> None:
        return None


class _Connector:
    def __init__(self, *websockets: _FakeWebSocket) -> None:
        self.websockets = list(websockets)
        self.calls: list[tuple[str, dict[str, object]]] = []

    def __call__(self, url: str, **kwargs: object) -> _Connection:
        self.calls.append((url, kwargs))
        return _Connection(self.websockets.pop(0))


class _FailingConnector:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    def __call__(self, url: str, **kwargs: object) -> _FailingConnection:
        self.calls += 1
        return _FailingConnection(self.error)


def _wait_for(predicate: Callable[[], bool], timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition was not met before timeout")


class WebSocketClientTests(unittest.TestCase):
    def test_binance_public_subscription_runs_on_background_event_loop(self) -> None:
        websocket = _FakeWebSocket()
        connector = Mock(side_effect=_Connector(websocket))
        callback_threads: list[int] = []
        client = BinanceSpotPublicWebSocketClient(
            connector=connector,
            on_message=lambda raw, parsed: callback_threads.append(
                threading.get_ident()
            ),
        )
        client.subscribe("btcusdt@trade")

        client.start()
        _wait_for(lambda: len(websocket.sent) == 1)
        asyncio.run_coroutine_threadsafe(
            websocket.incoming.put('{"e":"trade","p":"1.25"}'),
            client.event_loop,
        ).result(timeout=1)
        _wait_for(lambda: len(callback_threads) == 1)
        client.close()

        connector.assert_called_once()
        call = connector.call_args
        self.assertEqual(call.args, (BINANCE_SPOT_PUBLIC_WS_URL,))
        self.assertIsNone(call.kwargs["ping_interval"])
        self.assertEqual(call.kwargs["close_timeout"], 10.0)
        self.assertEqual(
            call.kwargs["logger"].name, "binance_bitget_bot.websocket.protocol"
        )
        self.assertGreaterEqual(call.kwargs["logger"].level, logging.WARNING)
        self.assertEqual(
            json.loads(websocket.sent[0]),
            {
                "method": "SUBSCRIBE",
                "params": ["btcusdt@trade"],
                "id": "1",
            },
        )
        self.assertNotEqual(callback_threads[0], threading.get_ident())
        self.assertFalse(client.is_running)
        self.assertTrue(websocket.closed)

    def test_message_dispatch_preserves_raw_text_and_parsed_json(self) -> None:
        websocket = _FakeWebSocket()
        received: list[tuple[str, object]] = []
        client = BinanceSpotPublicWebSocketClient(
            connector=_Connector(websocket),
            on_message=lambda raw, parsed: received.append((raw, parsed)),
        )
        raw = '{"e":"trade","p":"1.2500"}'

        client.start()
        _wait_for(lambda: client.is_connected)
        asyncio.run_coroutine_threadsafe(
            websocket.incoming.put(raw), client.event_loop
        ).result(timeout=1)
        _wait_for(lambda: len(received) == 1)
        client.close()

        self.assertEqual(received, [(raw, {"e": "trade", "p": "1.2500"})])

    def test_binance_connected_subscribe_and_unsubscribe_messages(self) -> None:
        websocket = _FakeWebSocket()
        client = BinanceSpotPublicWebSocketClient(connector=_Connector(websocket))
        client.start()
        _wait_for(lambda: client.is_connected)

        client.subscribe("btcusdt@trade")
        _wait_for(lambda: len(websocket.sent) == 1)
        client.unsubscribe("btcusdt@trade")
        _wait_for(lambda: len(websocket.sent) == 2)
        client.close()

        self.assertEqual(json.loads(websocket.sent[0])["method"], "SUBSCRIBE")
        self.assertEqual(json.loads(websocket.sent[1])["method"], "UNSUBSCRIBE")

    def test_binance_rejects_invalid_subscription_before_start(self) -> None:
        client = BinanceSpotPublicWebSocketClient()

        with self.assertRaisesRegex(ValueError, "stream names"):
            client.subscribe("")
        with self.assertRaisesRegex(ValueError, "stream names"):
            client.subscribe({"topic": "ticker"})

    def test_futures_public_routes_are_explicit_production_endpoints(self) -> None:
        public = BinanceFuturesPublicWebSocketClient(
            connector=_Connector(_FakeWebSocket())
        )
        self.assertEqual(public.endpoint, BINANCE_FUTURES_PUBLIC_WS_URL)
        self.assertEqual(
            public.endpoint, "wss://fstream.binance.com/public/stream"
        )

    def test_binance_private_entry_accepts_existing_listen_key_only(self) -> None:
        websocket = _FakeWebSocket()
        client = BinanceFuturesPrivateWebSocketClient(
            "existing-listen-key",
            connector=_Connector(websocket),
        )

        client.start()
        _wait_for(lambda: client.is_connected)
        client.close()

        self.assertEqual(
            client.endpoint,
            f"{BINANCE_FUTURES_PRIVATE_WS_BASE_URL}/existing-listen-key",
        )
        self.assertEqual(websocket.sent, [])
        with self.assertRaisesRegex(ValueError, "listen key"):
            BinanceFuturesPrivateWebSocketClient(" ")
        with self.assertRaisesRegex(NotImplementedError, "do not accept"):
            client.subscribe("btcusdt@trade")

    def test_binance_spot_private_entry_disables_market_stream_controls(self) -> None:
        websocket = _FakeWebSocket()
        websocket.incoming.put_nowait(
            '{"id":"1","status":200,"result":{"subscriptionId":7}}'
        )
        client = BinanceSpotPrivateWebSocketClient(
            credentials=ApiCredentials(
                binance_api_key="spot-key", binance_api_secret="spot-secret"
            ),
            connector=_Connector(websocket),
            clock_ms=lambda: 1700000000000,
        )

        client.start()
        _wait_for(lambda: client.is_connected)
        client.close()
        message = json.loads(websocket.sent[0])
        self.assertEqual(message["method"], "userDataStream.subscribe.signature")
        self.assertEqual(message["params"]["apiKey"], "spot-key")
        self.assertIn("signature", message["params"])

        with self.assertRaisesRegex(NotImplementedError, "do not accept"):
            client.subscribe("btcusdt@trade")
        with self.assertRaisesRegex(NotImplementedError, "do not accept"):
            client.unsubscribe("btcusdt@trade")

    def test_binance_spot_private_rejects_failed_authentication_ack(self) -> None:
        websocket = _FakeWebSocket()
        websocket.incoming.put_nowait(
            '{"id":"1","status":401,"error":{"code":-2015}}'
        )
        errors = []
        client = BinanceSpotPrivateWebSocketClient(
            credentials=ApiCredentials(
                binance_api_key="spot-key", binance_api_secret="spot-secret"
            ),
            connector=_Connector(websocket),
            clock_ms=lambda: 1700000000000,
            reconnect_attempts=0,
            on_error=errors.append,
        )

        client.start()
        _wait_for(lambda: bool(errors))
        client.close()

        self.assertIsInstance(errors[0], WebSocketProtocolError)

    def test_binance_spot_private_authentication_ack_times_out(self) -> None:
        errors = []
        client = BinanceSpotPrivateWebSocketClient(
            credentials=ApiCredentials(
                binance_api_key="spot-key", binance_api_secret="spot-secret"
            ),
            connector=_Connector(_FakeWebSocket()),
            heartbeat_timeout=0.01,
            reconnect_attempts=0,
            on_error=errors.append,
        )

        client.start()
        _wait_for(lambda: bool(errors))
        client.close()

        self.assertIsInstance(errors[0], WebSocketTimeoutError)

    def test_binance_futures_listen_key_is_renewed_rebuilt_and_closed(self) -> None:
        rest = Mock()
        rest.create_listen_key.side_effect = ["key-one", "key-two"]
        rest.keepalive_listen_key.side_effect = RuntimeError("expired")
        sockets = []

        def factory(key, **_kwargs):
            socket = Mock()
            socket.key = key
            sockets.append(socket)
            return socket

        stream = BinanceFuturesPrivateStream(
            rest,
            websocket_factory=factory,
            keepalive_seconds=0.01,
        )
        stream.start()
        _wait_for(lambda: len(sockets) == 2)
        stream.stop()
        stream.stop()

        self.assertEqual([socket.key for socket in sockets], ["key-one", "key-two"])
        sockets[0].stop.assert_called_once()
        sockets[1].stop.assert_called_once()
        self.assertGreaterEqual(rest.close_listen_key.call_count, 2)

    def test_binance_futures_expiry_event_rebuilds_the_private_stream(self) -> None:
        rest = Mock()
        rest.create_listen_key.side_effect = ["key-one", "key-two"]
        sockets = []

        def factory(key, **kwargs):
            socket = Mock()
            socket.key = key
            socket.on_message = kwargs["on_message"]
            sockets.append(socket)
            return socket

        stream = BinanceFuturesPrivateStream(
            rest,
            websocket_factory=factory,
            keepalive_seconds=60,
        )
        stream.start()
        sockets[0].on_message(
            '{"e":"listenKeyExpired"}',
            {"e": "listenKeyExpired"},
        )
        _wait_for(lambda: len(sockets) == 2)
        stream.stop()

        self.assertEqual([socket.key for socket in sockets], ["key-one", "key-two"])
        rest.keepalive_listen_key.assert_not_called()

    def test_binance_futures_exhausted_websocket_rebuilds_stream(self) -> None:
        rest = Mock()
        rest.create_listen_key.side_effect = ["key-one", "key-two"]
        sockets = []

        def factory(key, **kwargs):
            socket = Mock()
            socket.key = key
            socket.on_stopped = kwargs["on_stopped"]
            sockets.append(socket)
            return socket

        stream = BinanceFuturesPrivateStream(
            rest,
            websocket_factory=factory,
            keepalive_seconds=60,
        )
        stream.start()
        sockets[0].on_stopped()
        _wait_for(lambda: len(sockets) == 2)
        stream.stop()

        self.assertEqual([socket.key for socket in sockets], ["key-one", "key-two"])

    def test_bitget_subscription_and_unsubscription_messages(self) -> None:
        websocket = _FakeWebSocket()
        client = BitgetSpotPublicWebSocketClient(connector=_Connector(websocket))
        channel = {"instType": "spot", "topic": "ticker", "symbol": "BTCUSDT"}
        client.subscribe(channel)
        client.start()
        _wait_for(lambda: len(websocket.sent) == 1)
        client.unsubscribe(channel)
        _wait_for(lambda: len(websocket.sent) == 2)
        client.close()

        self.assertEqual(
            json.loads(websocket.sent[0]),
            {"op": "subscribe", "args": [channel]},
        )
        self.assertEqual(
            json.loads(websocket.sent[1]),
            {"op": "unsubscribe", "args": [channel]},
        )
        with self.assertRaisesRegex(ValueError, "instType"):
            BitgetSpotPublicWebSocketClient().subscribe({"topic": "ticker"})

    def test_bitget_login_signature_and_message_match_official_shape(self) -> None:
        credentials = ApiCredentials(
            bitget_api_key="test-key",
            bitget_api_secret="test-secret",
            bitget_api_passphrase="test-passphrase",
        )
        message = build_login_message(credentials, "1700000000")

        self.assertEqual(
            message,
            {
                "op": "login",
                "args": [
                    {
                        "apiKey": "test-key",
                        "passphrase": "test-passphrase",
                        "timestamp": "1700000000",
                        "sign": "QKXMEacdjBcrVZaxWVJypn62KNrQGzBErbiQtYn6KO8=",
                    }
                ],
            },
        )

    def test_bitget_private_login_precedes_subscription(self) -> None:
        credentials = ApiCredentials(
            bitget_api_key="test-key",
            bitget_api_secret="test-secret",
            bitget_api_passphrase="test-passphrase",
        )
        websocket = _FakeWebSocket()
        websocket.incoming.put_nowait('{"event":"login","code":"0","msg":""}')
        client = BitgetSpotPrivateWebSocketClient(
            credentials,
            connector=_Connector(websocket),
            clock_seconds=lambda: 1700000000,
        )
        client.subscribe(
            {"instType": "UTA", "topic": "account"}
        )
        client.start()
        _wait_for(lambda: len(websocket.sent) == 2)
        client.close()

        self.assertEqual(json.loads(websocket.sent[0])["op"], "login")
        self.assertEqual(json.loads(websocket.sent[1])["op"], "subscribe")

    def test_bitget_private_rejects_login_failure_before_subscription(self) -> None:
        credentials = ApiCredentials(
            bitget_api_key="test-key",
            bitget_api_secret="test-secret",
            bitget_api_passphrase="test-passphrase",
        )
        websocket = _FakeWebSocket()
        websocket.incoming.put_nowait(
            '{"event":"error","code":"30005","msg":"Login failure"}'
        )
        errors: list[Exception] = []
        client = BitgetSpotPrivateWebSocketClient(
            credentials,
            connector=_Connector(websocket),
            reconnect_attempts=0,
            on_error=errors.append,
        )
        client.subscribe({"instType": "UTA", "topic": "account"})

        client.start()
        _wait_for(lambda: not client.is_running)

        self.assertEqual(len(websocket.sent), 1)
        self.assertEqual(json.loads(websocket.sent[0])["op"], "login")
        self.assertTrue(
            any(isinstance(error, WebSocketProtocolError) for error in errors)
        )

    def test_bitget_private_is_ready_only_after_subscription_ack(self) -> None:
        credentials = ApiCredentials(
            bitget_api_key="test-key",
            bitget_api_secret="test-secret",
            bitget_api_passphrase="test-passphrase",
        )
        websocket = _FakeWebSocket()
        websocket.incoming.put_nowait('{"event":"login","code":"0","msg":""}')
        websocket.incoming.put_nowait(
            '{"event":"subscribe","arg":{"instType":"UTA","topic":"account"}}'
        )
        client = BitgetSpotPrivateWebSocketClient(
            credentials,
            connector=_Connector(websocket),
            clock_seconds=lambda: 1700000000,
        )
        client.subscribe({"instType": "UTA", "topic": "account"})
        self.assertFalse(client.is_connected)

        client.start()
        _wait_for(lambda: client.is_connected)
        client.close()

    def test_bitget_private_subscription_rejection_disconnects(self) -> None:
        credentials = ApiCredentials(
            bitget_api_key="test-key",
            bitget_api_secret="test-secret",
            bitget_api_passphrase="test-passphrase",
        )
        websocket = _FakeWebSocket()
        websocket.incoming.put_nowait('{"event":"login","code":"0","msg":""}')
        websocket.incoming.put_nowait(
            '{"event":"subscribe","code":"30001","msg":"rejected"}'
        )
        errors: list[Exception] = []
        client = BitgetSpotPrivateWebSocketClient(
            credentials,
            connector=_Connector(websocket),
            reconnect_attempts=0,
            on_error=errors.append,
        )
        client.subscribe({"instType": "UTA", "topic": "account"})

        client.start()
        _wait_for(lambda: not client.is_running)

        self.assertFalse(client.is_connected)
        self.assertTrue(
            any(isinstance(error, WebSocketProtocolError) for error in errors)
        )

    def test_bitget_private_client_rejects_incomplete_credentials(self) -> None:
        with self.assertRaisesRegex(
            ExchangeCredentialsError, "BITGET_API_PASSPHRASE"
        ):
            BitgetSpotPrivateWebSocketClient(
                ApiCredentials(
                    bitget_api_key="key",
                    bitget_api_secret="secret",
                )
            )

    def test_all_websocket_urls_are_fixed_production_addresses(self) -> None:
        urls = (
            BINANCE_SPOT_PUBLIC_WS_URL,
            BINANCE_SPOT_PRIVATE_WS_URL,
            BINANCE_FUTURES_PUBLIC_WS_URL,
            BINANCE_FUTURES_PRIVATE_WS_BASE_URL,
            BITGET_PUBLIC_WS_URL,
            BITGET_PRIVATE_WS_URL,
        )
        for url in urls:
            self.assertTrue(url.startswith("wss://"))
            for forbidden in ("testnet", "demo", "sandbox", "paper"):
                self.assertNotIn(forbidden, url.lower())

    def test_bitget_heartbeat_sends_ping_and_accepts_pong(self) -> None:
        websocket = _FakeWebSocket()
        client = BitgetSpotPublicWebSocketClient(
            connector=_Connector(websocket),
            heartbeat_interval=0.01,
            heartbeat_timeout=0.1,
        )
        client.start()
        _wait_for(lambda: "ping" in websocket.sent)
        asyncio.run_coroutine_threadsafe(
            websocket.incoming.put("pong"), client.event_loop
        ).result(timeout=1)
        time.sleep(0.02)
        client.close()

        self.assertNotIn("pong", websocket.sent)

    def test_binance_heartbeat_uses_protocol_ping(self) -> None:
        websocket = _FakeWebSocket()
        client = BinanceSpotPublicWebSocketClient(
            connector=_Connector(websocket),
            heartbeat_interval=0.01,
            heartbeat_timeout=0.1,
        )

        client.start()
        _wait_for(lambda: websocket.ping_count > 0)
        client.close()

        self.assertGreater(websocket.ping_count, 0)

    def test_heartbeat_timeout_is_reported_without_sensitive_details(self) -> None:
        websocket = _FakeWebSocket()
        errors: list[Exception] = []
        client = BitgetSpotPublicWebSocketClient(
            connector=_Connector(websocket),
            heartbeat_interval=0.01,
            heartbeat_timeout=0.01,
            reconnect_attempts=0,
            on_error=errors.append,
        )
        client.start()
        _wait_for(lambda: not client.is_running)

        self.assertTrue(any(isinstance(error, WebSocketTimeoutError) for error in errors))

    def test_disconnect_reconnects_and_restores_subscription(self) -> None:
        first = _FakeWebSocket()
        first.incoming.put_nowait(OSError("connection lost"))
        second = _FakeWebSocket()
        connector = _Connector(first, second)
        client = BinanceSpotPublicWebSocketClient(
            connector=connector,
            reconnect_attempts=1,
            reconnect_initial=0,
            reconnect_max=0,
        )
        client.subscribe("btcusdt@trade")

        client.start()
        _wait_for(lambda: len(connector.calls) == 2 and len(second.sent) == 1)
        client.close()

        self.assertEqual(
            json.loads(first.sent[0])["params"], ["btcusdt@trade"]
        )
        self.assertEqual(
            json.loads(second.sent[0])["params"], ["btcusdt@trade"]
        )

    def test_reconnect_attempts_are_bounded(self) -> None:
        connector = _FailingConnector(OSError("connection refused"))
        client = BinanceSpotPublicWebSocketClient(
            connector=connector,
            reconnect_attempts=2,
            reconnect_initial=0,
            reconnect_max=0,
        )

        client.start()
        _wait_for(lambda: not client.is_running)

        self.assertEqual(connector.calls, 3)

    def test_reconnect_budget_resets_after_a_successful_heartbeat(self) -> None:
        first = _FakeWebSocket()
        first.incoming.put_nowait(OSError("first failure"))
        second = _FakeWebSocket()
        third = _FakeWebSocket()
        connector = _Connector(first, second, third)
        client = BinanceSpotPublicWebSocketClient(
            connector=connector,
            reconnect_attempts=1,
            reconnect_initial=0,
            reconnect_max=0,
            heartbeat_interval=0.01,
            heartbeat_timeout=0.1,
        )

        client.start()
        _wait_for(lambda: second.ping_count > 0)
        asyncio.run_coroutine_threadsafe(
            second.incoming.put(OSError("later failure")), client.event_loop
        ).result(timeout=1)
        _wait_for(lambda: len(connector.calls) == 3)
        client.close()

        self.assertEqual(len(connector.calls), 3)

    def test_subscribe_during_connection_setup_is_sent_once(self) -> None:
        connection_started = threading.Event()
        continue_connection = threading.Event()

        class _GatedConnection(_Connection):
            async def __aenter__(self) -> _FakeWebSocket:
                connection_started.set()
                while not continue_connection.is_set():
                    await asyncio.sleep(0.001)
                return await super().__aenter__()

        def connector(url: str, **kwargs: object) -> _GatedConnection:
            return _GatedConnection(websocket)

        websocket = _FakeWebSocket()
        client = BinanceSpotPublicWebSocketClient(connector=connector)
        client.start()
        self.assertTrue(connection_started.wait(timeout=1))

        client.subscribe("btcusdt@trade")
        continue_connection.set()
        _wait_for(lambda: len(websocket.sent) >= 1)
        client.close()

        self.assertEqual(len(websocket.sent), 1)
        self.assertEqual(json.loads(websocket.sent[0])["params"], ["btcusdt@trade"])

    def test_subscribe_after_restore_snapshot_is_not_lost(self) -> None:
        snapshot_built = threading.Event()
        continue_connection = threading.Event()

        class _AfterSnapshotClient(BinanceSpotPublicWebSocketClient):
            def _subscription_message(self, subscriptions: list[object]) -> str:
                if not snapshot_built.is_set():
                    snapshot_built.set()
                    continue_connection.wait(timeout=1)
                return super()._subscription_message(subscriptions)

        websocket = _FakeWebSocket()
        client = _AfterSnapshotClient(connector=_Connector(websocket))
        client.subscribe("ethusdt@trade")
        client.start()
        self.assertTrue(snapshot_built.wait(timeout=1))

        client.subscribe("btcusdt@trade")
        continue_connection.set()
        _wait_for(lambda: len(websocket.sent) == 2)
        client.close()

        streams = [
            stream
            for message in websocket.sent
            for stream in json.loads(message)["params"]
        ]
        self.assertCountEqual(streams, ["ethusdt@trade", "btcusdt@trade"])

    def test_unsubscribe_after_restore_snapshot_is_not_lost(self) -> None:
        snapshot_built = threading.Event()
        continue_connection = threading.Event()

        class _AfterSnapshotClient(BinanceSpotPublicWebSocketClient):
            def _subscription_message(self, subscriptions: list[object]) -> str:
                if not snapshot_built.is_set():
                    snapshot_built.set()
                    continue_connection.wait(timeout=1)
                return super()._subscription_message(subscriptions)

        websocket = _FakeWebSocket()
        client = _AfterSnapshotClient(connector=_Connector(websocket))
        client.subscribe("btcusdt@trade")
        client.start()
        self.assertTrue(snapshot_built.wait(timeout=1))

        client.unsubscribe("btcusdt@trade")
        continue_connection.set()
        _wait_for(lambda: len(websocket.sent) == 2)
        client.close()

        self.assertEqual(
            [json.loads(message)["method"] for message in websocket.sent],
            ["SUBSCRIBE", "UNSUBSCRIBE"],
        )

    def test_invalid_json_reports_protocol_error(self) -> None:
        websocket = _FakeWebSocket()
        websocket.incoming.put_nowait("not-json-with-private-secret")
        errors: list[Exception] = []
        client = BinanceSpotPublicWebSocketClient(
            connector=_Connector(websocket),
            reconnect_attempts=0,
            on_error=errors.append,
        )

        client.start()
        _wait_for(lambda: not client.is_running)

        protocol_error = next(
            error for error in errors if isinstance(error, WebSocketProtocolError)
        )
        self.assertIsNone(protocol_error.__cause__)
        self.assertIsNone(protocol_error.__context__)
        self.assertNotIn("private-secret", repr(protocol_error))

    def test_message_handler_failure_is_isolated_and_redacted(self) -> None:
        websocket = _FakeWebSocket()
        errors: list[Exception] = []

        def failing_handler(raw: str, parsed: object) -> None:
            raise RuntimeError(f"callback failed with {raw}")

        client = BinanceSpotPublicWebSocketClient(
            connector=_Connector(websocket),
            on_message=failing_handler,
            on_error=errors.append,
        )
        client.start()
        _wait_for(lambda: client.is_connected)
        asyncio.run_coroutine_threadsafe(
            websocket.incoming.put('{"secret":"private-secret"}'),
            client.event_loop,
        ).result(timeout=1)
        _wait_for(lambda: len(errors) == 1)

        self.assertTrue(client.is_connected)
        self.assertIsInstance(errors[0], WebSocketClientError)
        self.assertNotIn("private-secret", repr(errors[0]))
        client.close()

    def test_start_stop_and_close_are_idempotent_and_restart_cleans_loops(self) -> None:
        first = _FakeWebSocket()
        second = _FakeWebSocket()
        connector = _Connector(first, second)
        client = BinanceSpotPublicWebSocketClient(connector=connector)

        client.start()
        client.start()
        _wait_for(lambda: client.is_connected)
        first_loop = client.event_loop
        client.stop()
        self.assertTrue(first_loop.is_closed())

        client.start()
        _wait_for(lambda: client.is_connected)
        second_loop = client.event_loop
        client.close()
        client.close()

        self.assertEqual(len(connector.calls), 2)
        self.assertIsNot(first_loop, second_loop)
        self.assertTrue(second_loop.is_closed())
        self.assertFalse(client.is_running)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            client.start()

    def test_close_can_retry_after_join_timeout(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        websocket = _FakeWebSocket()

        class _BlockingConnection(_Connection):
            async def __aenter__(self) -> _FakeWebSocket:
                entered.set()
                release.wait(timeout=1)
                return await super().__aenter__()

        def connector(url: str, **kwargs: object) -> _BlockingConnection:
            return _BlockingConnection(websocket)

        client = BinanceSpotPublicWebSocketClient(connector=connector)
        client.start()
        self.assertTrue(entered.wait(timeout=1))

        with self.assertRaisesRegex(RuntimeError, "did not stop"):
            client.close(timeout=0.01)
        release.set()
        client.close()

        self.assertFalse(client.is_running)

    def test_private_authentication_is_not_written_to_logs(self) -> None:
        credentials = ApiCredentials(
            bitget_api_key="test-key",
            bitget_api_secret="test-secret",
            bitget_api_passphrase="test-passphrase",
        )
        stream = io.StringIO()
        logger = logging.getLogger("tests.websocket.redaction")
        logger.handlers.clear()
        logger.propagate = False
        logger.setLevel(logging.DEBUG)
        logger.addHandler(logging.StreamHandler(stream))
        websocket = _FakeWebSocket()
        client = BitgetSpotPrivateWebSocketClient(
            credentials,
            connector=_Connector(websocket),
            clock_seconds=lambda: 1700000000,
            logger=logger,
        )

        client.start()
        _wait_for(lambda: len(websocket.sent) == 1)
        authentication_message = websocket.sent[0]
        client.close()

        rendered = stream.getvalue()
        for value in (
            "test-key",
            "test-secret",
            "test-passphrase",
            json.loads(authentication_message)["args"][0]["sign"],
        ):
            self.assertNotIn(value, rendered)
        self.assertNotIn(authentication_message, rendered)

    def test_transport_error_does_not_expose_private_credentials(self) -> None:
        credentials = ApiCredentials(
            bitget_api_key="test-key",
            bitget_api_secret="test-secret",
            bitget_api_passphrase="test-passphrase",
        )
        stream = io.StringIO()
        logger = logging.getLogger("tests.websocket.transport-redaction")
        logger.handlers.clear()
        logger.propagate = False
        logger.setLevel(logging.DEBUG)
        logger.addHandler(logging.StreamHandler(stream))
        errors: list[Exception] = []
        client = BitgetSpotPrivateWebSocketClient(
            credentials,
            connector=_FailingConnector(
                OSError("failed with test-secret and signed-auth-message")
            ),
            reconnect_attempts=0,
            on_error=errors.append,
            logger=logger,
        )

        client.start()
        _wait_for(lambda: not client.is_running)
        client.close()

        self.assertEqual(len(errors), 1)
        rendered = f"{errors[0]} {stream.getvalue()}"
        self.assertNotIn("test-secret", rendered)
        self.assertNotIn("signed-auth-message", rendered)
        self.assertIsNone(errors[0].__cause__)


if __name__ == "__main__":
    unittest.main()
