"""Thread-owned asyncio transport shared by the exchange WebSocket clients."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import Future
import asyncio
import json
import logging
import threading
from typing import Any

import websockets


MessageHandler = Callable[[str, object], None]
ErrorHandler = Callable[[Exception], None]
Connector = Callable[..., Any]
_LOGGER = logging.getLogger("binance_bitget_bot.exchanges.websocket")
_LOGGER.addHandler(logging.NullHandler())
_TRANSPORT_LOGGER = logging.getLogger("binance_bitget_bot.websocket.protocol")
_TRANSPORT_LOGGER.setLevel(logging.WARNING)
_TRANSPORT_LOGGER.propagate = False
_TRANSPORT_LOGGER.addHandler(logging.NullHandler())


class WebSocketClientError(RuntimeError):
    """Base error safe to report outside the transport thread."""


class WebSocketProtocolError(WebSocketClientError):
    """A received text frame didn't follow the expected protocol."""


class WebSocketTimeoutError(WebSocketClientError):
    """The peer didn't answer a heartbeat within the timeout."""


class ThreadedWebSocketClient:
    """Run one synchronous-looking WebSocket interface on a private event loop."""

    HEARTBEAT_TEXT: str | None = None
    HEARTBEAT_REPLY: str | None = None

    def __init__(
        self,
        url: str,
        *,
        name: str,
        connector: Connector = websockets.connect,
        on_message: MessageHandler | None = None,
        on_error: ErrorHandler | None = None,
        on_stopped: Callable[[], None] | None = None,
        heartbeat_interval: float = 30.0,
        heartbeat_timeout: float = 10.0,
        reconnect_attempts: int = 3,
        reconnect_initial: float = 1.0,
        reconnect_max: float = 8.0,
        logger: logging.Logger | None = None,
    ) -> None:
        if heartbeat_interval <= 0 or heartbeat_timeout <= 0:
            raise ValueError("heartbeat intervals must be greater than zero")
        if reconnect_attempts < 0:
            raise ValueError("reconnect_attempts cannot be negative")
        if reconnect_initial < 0 or reconnect_max < 0:
            raise ValueError("reconnect delays cannot be negative")
        self._url = url
        self._name = name
        self._connector = connector
        self._on_message = on_message
        self._on_error = on_error
        self._on_stopped = on_stopped
        self._heartbeat_interval = heartbeat_interval
        self._heartbeat_timeout = heartbeat_timeout
        self._reconnect_attempts = reconnect_attempts
        self._reconnect_initial = reconnect_initial
        self._reconnect_max = reconnect_max
        self._logger = logger or _LOGGER
        self._subscriptions: dict[str, object] = {}
        self._subscriptions_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._ready = threading.Event()
        self._connected = threading.Event()
        self._stop_requested = threading.Event()
        self._closed = False
        self._connection_stable = False
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[None] | None = None
        self._websocket: Any = None

    @property
    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    @property
    def endpoint(self) -> str:
        return self._url

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()

    @property
    def event_loop(self) -> asyncio.AbstractEventLoop:
        loop = self._loop
        if loop is None:
            raise RuntimeError("WebSocket client has not started")
        return loop

    def start(self) -> None:
        with self._state_lock:
            if self._closed:
                raise RuntimeError("WebSocket client is closed")
            if self.is_running:
                return
            self._ready.clear()
            self._stop_requested.clear()
            self._thread = threading.Thread(
                target=self._thread_main,
                name=f"{self._name}-websocket",
                daemon=True,
            )
            self._thread.start()
        if not self._ready.wait(timeout=2.0):
            raise RuntimeError("WebSocket event loop failed to start")

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_requested.set()
        loop = self._loop
        task = self._task
        if (
            loop is not None
            and not loop.is_closed()
            and task is not None
            and not task.done()
        ):
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
            if thread.is_alive():
                raise RuntimeError("WebSocket thread did not stop")

    def close(self, timeout: float = 5.0) -> None:
        with self._state_lock:
            if self._closed and not self.is_running:
                return
        self.stop(timeout)
        with self._state_lock:
            self._closed = True

    def subscribe(self, *subscriptions: object) -> None:
        new_subscriptions, connected = self._store_subscriptions(subscriptions)
        if new_subscriptions and connected:
            self._send_from_caller(self._subscription_message(new_subscriptions))

    def unsubscribe(self, *subscriptions: object) -> None:
        removed, connected = self._remove_subscriptions(subscriptions)
        if removed and connected:
            self._send_from_caller(self._unsubscription_message(removed))

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._task = loop.create_task(self._run())
        self._ready.set()
        try:
            loop.run_until_complete(self._task)
        except asyncio.CancelledError:
            pass
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
            self._connected.clear()
            self._websocket = None
            self._task = None
            self._loop = None
            if self._on_stopped is not None:
                try:
                    self._on_stopped()
                except Exception:
                    self._logger.error(
                        "%s WebSocket stopped handler failed", self._name
                    )

    async def _run(self) -> None:
        reconnect_number = 0
        while not self._stop_requested.is_set():
            try:
                await self._run_connection()
            except asyncio.CancelledError:
                raise
            except (OSError, websockets.WebSocketException, WebSocketClientError) as exc:
                self._report_error(self._safe_error(exc))
            except Exception:
                self._report_error(
                    WebSocketClientError(f"{self._name} WebSocket failed")
                )
                return
            else:
                if self._stop_requested.is_set():
                    return
                self._report_error(
                    WebSocketClientError(
                        f"{self._name} WebSocket disconnected unexpectedly"
                    )
                )
            if self._connection_stable:
                reconnect_number = 0
            if reconnect_number >= self._reconnect_attempts:
                return
            delay = min(
                self._reconnect_initial * (2**reconnect_number),
                self._reconnect_max,
            )
            reconnect_number += 1
            self._logger.info(
                "%s WebSocket reconnecting attempt=%s",
                self._name,
                reconnect_number,
            )
            await asyncio.sleep(delay)

    async def _run_connection(self) -> None:
        self._connection_stable = False
        async with self._connector(
            self._url,
            ping_interval=None,
            close_timeout=self._heartbeat_timeout,
            logger=_TRANSPORT_LOGGER,
        ) as websocket:
            self._websocket = websocket
            try:
                await self._prepare_connection(websocket)
                subscriptions = self._activate_connection()
                if subscriptions:
                    await websocket.send(self._subscription_message(subscriptions))
                self._logger.info("%s WebSocket connected", self._name)
                pong_received = asyncio.Event()
                receiver = asyncio.create_task(
                    self._receive_loop(websocket, pong_received)
                )
                heartbeat = asyncio.create_task(
                    self._heartbeat_loop(websocket, pong_received)
                )
                tasks = (receiver, heartbeat)
                try:
                    done, _ = await asyncio.wait(
                        tasks, return_when=asyncio.FIRST_COMPLETED
                    )
                    for task in done:
                        task.result()
                finally:
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
            finally:
                self._deactivate_connection()
                self._websocket = None
                self._logger.info("%s WebSocket disconnected", self._name)

    async def _prepare_connection(self, websocket: Any) -> None:
        for message in self._connection_messages():
            await websocket.send(message)

    async def _receive_loop(
        self,
        websocket: Any,
        pong_received: asyncio.Event,
    ) -> None:
        while not self._stop_requested.is_set():
            raw = await websocket.recv()
            if raw == self.HEARTBEAT_REPLY:
                pong_received.set()
                continue
            self._dispatch(raw)

    async def _heartbeat_loop(
        self,
        websocket: Any,
        pong_received: asyncio.Event,
    ) -> None:
        while not self._stop_requested.is_set():
            await asyncio.sleep(self._heartbeat_interval)
            if self.HEARTBEAT_TEXT is not None:
                pong_received.clear()
                await websocket.send(self.HEARTBEAT_TEXT)
                try:
                    await asyncio.wait_for(
                        pong_received.wait(), timeout=self._heartbeat_timeout
                    )
                except TimeoutError:
                    raise WebSocketTimeoutError(
                        f"{self._name} WebSocket heartbeat timed out"
                    ) from None
                self._connection_stable = True
            else:
                try:
                    pong_waiter = await websocket.ping()
                    await asyncio.wait_for(
                        pong_waiter, timeout=self._heartbeat_timeout
                    )
                except TimeoutError:
                    raise WebSocketTimeoutError(
                        f"{self._name} WebSocket heartbeat timed out"
                    ) from None
                self._connection_stable = True

    def _safe_error(self, error: Exception) -> WebSocketClientError:
        if isinstance(error, WebSocketClientError):
            return error
        return WebSocketClientError(f"{self._name} WebSocket transport error")

    def _report_error(self, error: WebSocketClientError) -> None:
        self._logger.warning(
            "%s WebSocket error=%s", self._name, type(error).__name__
        )
        if self._on_error is None:
            return
        try:
            self._on_error(error)
        except Exception:
            self._logger.error("%s WebSocket error handler failed", self._name)

    def _decode_message(self, raw: object) -> tuple[str, object]:
        if isinstance(raw, bytes):
            decoded: str | None = None
            try:
                decoded = raw.decode("utf-8")
            except UnicodeDecodeError:
                pass
            if decoded is None:
                raise WebSocketProtocolError(
                    "WebSocket binary message is not UTF-8 JSON"
                )
            raw = decoded
        if not isinstance(raw, str):
            raise WebSocketProtocolError("WebSocket message must be text JSON")
        parsed: object = None
        invalid_json = False
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            invalid_json = True
        if invalid_json:
            raise WebSocketProtocolError("WebSocket message is not valid JSON")
        return raw, parsed

    def _dispatch(self, raw: object) -> None:
        raw_text, parsed = self._decode_message(raw)
        self._deliver_message(raw_text, parsed)

    def _deliver_message(self, raw: str, parsed: object) -> None:
        if self._on_message is None:
            return
        try:
            self._on_message(raw, parsed)
        except Exception:
            self._report_error(
                WebSocketClientError(f"{self._name} WebSocket message handler failed")
            )

    def _send_from_caller(self, message: str) -> None:
        loop = self._loop
        websocket = self._websocket
        if loop is None or websocket is None or not self._connected.is_set():
            return
        if loop.is_closed():
            return
        send = websocket.send(message)
        try:
            future = asyncio.run_coroutine_threadsafe(send, loop)
        except RuntimeError:
            send.close()
            return

        def report_send_failure(done: Future[object]) -> None:
            if done.cancelled():
                return
            try:
                done.result()
            except Exception:
                self._report_error(
                    WebSocketClientError(f"{self._name} WebSocket send failed")
                )

        future.add_done_callback(report_send_failure)

    def _store_subscriptions(
        self, subscriptions: tuple[object, ...]
    ) -> tuple[list[object], bool]:
        added = []
        with self._subscriptions_lock:
            for subscription in subscriptions:
                normalized = self._normalize_subscription(subscription)
                key = self._subscription_key(normalized)
                if key not in self._subscriptions:
                    self._subscriptions[key] = normalized
                    added.append(normalized)
            connected = self._connected.is_set()
        return added, connected

    def _remove_subscriptions(
        self, subscriptions: tuple[object, ...]
    ) -> tuple[list[object], bool]:
        removed = []
        with self._subscriptions_lock:
            for subscription in subscriptions:
                normalized = self._normalize_subscription(subscription)
                existing = self._subscriptions.pop(
                    self._subscription_key(normalized), None
                )
                if existing is not None:
                    removed.append(existing)
            connected = self._connected.is_set()
        return removed, connected

    def _activate_connection(self) -> list[object]:
        with self._subscriptions_lock:
            subscriptions = list(self._subscriptions.values())
            self._connected.set()
            return subscriptions

    def _deactivate_connection(self) -> None:
        with self._subscriptions_lock:
            self._connected.clear()

    def _subscription_key(self, subscription: object) -> str:
        if isinstance(subscription, str):
            return subscription
        return json.dumps(subscription, sort_keys=True, separators=(",", ":"))

    def _normalize_subscription(self, subscription: object) -> object:
        if isinstance(subscription, Mapping):
            return dict(subscription)
        return subscription

    def _connection_messages(self) -> tuple[str, ...]:
        return ()

    def _subscription_message(self, subscriptions: list[object]) -> str:
        raise NotImplementedError

    def _unsubscription_message(self, subscriptions: list[object]) -> str:
        raise NotImplementedError
