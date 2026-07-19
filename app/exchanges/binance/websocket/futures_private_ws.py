"""Binance USD-margined futures private stream and listen-key lifecycle."""

import logging
import threading
from collections.abc import Callable

from app.exchanges.binance.constants import BINANCE_FUTURES_PRIVATE_WS_BASE_URL
from app.exchanges.binance.websocket.client import BinancePrivateWebSocketClient


class BinanceFuturesPrivateWebSocketClient(BinancePrivateWebSocketClient):
    """Accept an existing listen key without managing its REST lifecycle."""

    def __init__(self, listen_key: str, **kwargs: object) -> None:
        listen_key = listen_key.strip()
        if not listen_key:
            raise ValueError("Binance futures listen key cannot be empty")
        url = f"{BINANCE_FUTURES_PRIVATE_WS_BASE_URL}/{listen_key}"
        super().__init__(url, **kwargs)


class BinanceFuturesPrivateStream:
    """Own one listen key, its WebSocket, and periodic renewal."""

    def __init__(
        self,
        rest_client,
        *,
        websocket_factory: Callable[..., BinanceFuturesPrivateWebSocketClient] = BinanceFuturesPrivateWebSocketClient,
        keepalive_seconds: float = 50 * 60,
        logger: logging.Logger | None = None,
        **websocket_kwargs: object,
    ) -> None:
        if keepalive_seconds <= 0:
            raise ValueError("keepalive_seconds must be positive")
        self._rest = rest_client
        self._factory = websocket_factory
        self._interval = keepalive_seconds
        self._logger = logger or logging.getLogger(
            "binance_bitget_bot.exchanges.binance.user_stream"
        )
        self._websocket_kwargs = dict(websocket_kwargs)
        self._on_message = self._websocket_kwargs.pop("on_message", None)
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._websocket: BinanceFuturesPrivateWebSocketClient | None = None
        self._has_listen_key = False
        self._generation = 0
        self._lock = threading.RLock()

    @property
    def is_connected(self) -> bool:
        with self._lock:
            websocket = self._websocket
            return websocket is not None and websocket.is_connected

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._wake.clear()
            self._replace_stream()
            self._thread = threading.Thread(
                target=self._keepalive_loop,
                name="binance-listen-key",
                daemon=False,
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
            self._stop.set()
            self._wake.set()
        error: Exception | None = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=20.0)
            if thread.is_alive():
                raise RuntimeError("Binance listen-key thread did not stop")
        with self._lock:
            self._thread = None
            if self._websocket is not None:
                try:
                    self._websocket.stop()
                except Exception as exc:
                    error = error or exc
                self._websocket = None
            if self._has_listen_key:
                try:
                    self._rest.close_listen_key()
                except Exception as exc:
                    self._logger.warning("Binance listen key close failed")
                    error = error or exc
                finally:
                    self._has_listen_key = False
        if error is not None:
            raise error

    close = stop

    def _keepalive_loop(self) -> None:
        while True:
            rebuild = self._wake.wait(self._interval)
            self._wake.clear()
            if self._stop.is_set():
                return
            if rebuild:
                try:
                    self._replace_stream()
                except Exception:
                    self._logger.warning("Binance listen key rebuild failed")
                continue
            try:
                self._rest.keepalive_listen_key()
            except Exception:
                if self._stop.is_set():
                    return
                self._logger.warning("Binance listen key expired; rebuilding stream")
                try:
                    self._replace_stream()
                except Exception:
                    self._logger.warning("Binance listen key rebuild failed")

    def _replace_stream(self) -> None:
        self._generation += 1
        generation = self._generation
        previous = self._websocket
        if previous is not None:
            previous.stop()
            self._websocket = None
            if self._has_listen_key:
                try:
                    self._rest.close_listen_key()
                except Exception:
                    self._logger.warning("Expired Binance listen key close failed")
                finally:
                    self._has_listen_key = False
        listen_key = self._rest.create_listen_key()
        self._has_listen_key = True
        replacement = self._factory(
            listen_key,
            on_message=self._handle_message,
            on_stopped=lambda: self._stream_stopped(generation),
            **self._websocket_kwargs,
        )
        self._websocket = replacement
        replacement.start()

    def _handle_message(self, raw: str, parsed: object) -> None:
        event = parsed.get("event") if isinstance(parsed, dict) else None
        if isinstance(event, dict):
            parsed_event = event
        else:
            parsed_event = parsed
        if (
            isinstance(parsed_event, dict)
            and parsed_event.get("e") == "listenKeyExpired"
        ):
            self._wake.set()
        if self._on_message is not None:
            self._on_message(raw, parsed)

    def _stream_stopped(self, generation: int) -> None:
        if generation == self._generation and not self._stop.is_set():
            self._wake.set()
