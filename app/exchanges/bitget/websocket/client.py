"""Bitget WebSocket messages and authentication."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import asyncio
import json
import time
from typing import Any
import threading

from app.exchanges.base.exchange_errors import ExchangeCredentialsError
from app.exchanges.base.websockets_client import (
    ThreadedWebSocketClient,
    WebSocketProtocolError,
    WebSocketTimeoutError,
)
from app.exchanges.bitget.signer import sign_websocket_login
from app.infrastructure.security.credential_store import ApiCredentials


def build_login_message(
    credentials: ApiCredentials,
    timestamp: str,
) -> dict[str, object]:
    missing = []
    if not credentials.bitget_api_key.strip():
        missing.append("BITGET_API_KEY")
    if not credentials.bitget_api_secret.strip():
        missing.append("BITGET_API_SECRET")
    if not credentials.bitget_api_passphrase.strip():
        missing.append("BITGET_API_PASSPHRASE")
    if missing:
        raise ExchangeCredentialsError(
            f"Bitget WebSocket credentials incomplete: {', '.join(missing)}"
        )
    return {
        "op": "login",
        "args": [
            {
                "apiKey": credentials.bitget_api_key,
                "passphrase": credentials.bitget_api_passphrase,
                "timestamp": timestamp,
                "sign": sign_websocket_login(
                    timestamp, credentials.bitget_api_secret
                ),
            }
        ],
    }


class BitgetWebSocketClient(ThreadedWebSocketClient):
    HEARTBEAT_TEXT = "ping"
    HEARTBEAT_REPLY = "pong"

    def __init__(self, url: str, **kwargs: object) -> None:
        super().__init__(url, name="Bitget", **kwargs)

    def _normalize_subscription(self, subscription: object) -> object:
        if not isinstance(subscription, Mapping):
            raise ValueError("Bitget subscriptions must be channel objects")
        channel = dict(subscription)
        for field in ("instType", "topic"):
            if not isinstance(channel.get(field), str) or not channel[field]:
                raise ValueError(f"Bitget UTA subscription requires {field}")
        return channel

    def _message(self, operation: str, subscriptions: list[object]) -> str:
        return json.dumps(
            {"op": operation, "args": subscriptions},
            separators=(",", ":"),
        )

    def _subscription_message(self, subscriptions: list[object]) -> str:
        return self._message("subscribe", subscriptions)

    def _unsubscription_message(self, subscriptions: list[object]) -> str:
        return self._message("unsubscribe", subscriptions)


class BitgetPrivateWebSocketClient(BitgetWebSocketClient):
    def __init__(
        self,
        url: str,
        credentials: ApiCredentials,
        *,
        clock_seconds: Callable[[], int] | None = None,
        **kwargs: object,
    ) -> None:
        build_login_message(credentials, "0")
        super().__init__(url, **kwargs)
        self._credentials = credentials
        self._clock_seconds = clock_seconds or (lambda: int(time.time()))
        self._subscriptions_ready = threading.Event()
        self._pending_subscription_acks: set[str] = set()

    @property
    def is_connected(self) -> bool:
        return super().is_connected and self._subscriptions_ready.is_set()

    def _subscription_message(self, subscriptions: list[object]) -> str:
        with self._subscriptions_lock:
            self._pending_subscription_acks.update(
                self._subscription_key(item) for item in subscriptions
            )
            self._subscriptions_ready.clear()
        return super()._subscription_message(subscriptions)

    def _deactivate_connection(self) -> None:
        self._subscriptions_ready.clear()
        with self._subscriptions_lock:
            self._pending_subscription_acks.clear()
        super()._deactivate_connection()

    def _deliver_message(self, raw: str, parsed: object) -> None:
        if isinstance(parsed, Mapping):
            event = parsed.get("event")
            code = parsed.get("code")
            if event == "error" or (event == "subscribe" and code not in (None, 0, "0")):
                raise WebSocketProtocolError("Bitget WebSocket subscription was rejected")
            if event == "subscribe":
                acknowledged = parsed.get("arg")
                if acknowledged is not None:
                    with self._subscriptions_lock:
                        self._pending_subscription_acks.discard(
                            self._subscription_key(self._normalize_subscription(acknowledged))
                        )
                        if not self._pending_subscription_acks:
                            self._subscriptions_ready.set()
        super()._deliver_message(raw, parsed)

    def _connection_messages(self) -> tuple[str, ...]:
        message = build_login_message(
            self._credentials,
            str(self._clock_seconds()),
        )
        return (json.dumps(message, separators=(",", ":")),)

    async def _prepare_connection(self, websocket: Any) -> None:
        await super()._prepare_connection(websocket)
        try:
            response = await asyncio.wait_for(
                websocket.recv(), timeout=self._heartbeat_timeout
            )
        except TimeoutError:
            raise WebSocketTimeoutError(
                "Bitget WebSocket login timed out"
            ) from None
        raw, parsed = self._decode_message(response)
        if (
            not isinstance(parsed, Mapping)
            or parsed.get("event") != "login"
            or str(parsed.get("code")) != "0"
        ):
            raise WebSocketProtocolError("Bitget WebSocket login was rejected")
        self._deliver_message(raw, parsed)
