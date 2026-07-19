"""Binance Spot signed user-data WebSocket subscription."""

import asyncio
import json
from itertools import count
import time
from urllib.parse import urlencode

from app.exchanges.binance.constants import BINANCE_SPOT_PRIVATE_WS_URL
from app.exchanges.binance.signer import sign_query
from app.exchanges.binance.websocket.client import BinancePrivateWebSocketClient
from app.exchanges.base.websockets_client import (
    WebSocketProtocolError,
    WebSocketTimeoutError,
)
from app.exchanges.base.exchange_errors import ExchangeCredentialsError
from app.infrastructure.security.credential_store import ApiCredentials


class BinanceSpotPrivateWebSocketClient(BinancePrivateWebSocketClient):
    """Subscribe to Spot user data with a signed production WS-API request."""

    def __init__(
        self,
        *,
        credentials: ApiCredentials,
        clock_ms=None,
        **kwargs: object,
    ) -> None:
        if not credentials.binance_api_key or not credentials.binance_api_secret:
            raise ExchangeCredentialsError("Binance Spot WebSocket credentials incomplete")
        self._credentials = credentials
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self._ids = count(1)
        super().__init__(BINANCE_SPOT_PRIVATE_WS_URL, **kwargs)

    def _connection_messages(self) -> tuple[str, ...]:
        params = {
            "apiKey": self._credentials.binance_api_key,
            "timestamp": self._clock_ms(),
        }
        params["signature"] = sign_query(
            urlencode(params), self._credentials.binance_api_secret
        )
        return (
            json.dumps(
                {
                    "id": str(next(self._ids)),
                    "method": "userDataStream.subscribe.signature",
                    "params": params,
                },
                separators=(",", ":"),
            ),
        )

    async def _prepare_connection(self, websocket) -> None:
        messages = self._connection_messages()
        await websocket.send(messages[0])
        try:
            raw = await asyncio.wait_for(
                websocket.recv(), timeout=self._heartbeat_timeout
            )
        except TimeoutError:
            raise WebSocketTimeoutError(
                "Binance Spot private authentication timed out"
            ) from None
        _raw, response = self._decode_message(raw)
        if (
            not isinstance(response, dict)
            or response.get("status") != 200
            or not isinstance(response.get("result"), dict)
            or "subscriptionId" not in response["result"]
        ):
            raise WebSocketProtocolError(
                "Binance Spot private subscription authentication failed"
            )
