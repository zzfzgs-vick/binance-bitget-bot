"""Binance WebSocket control-message format."""

import json
from itertools import count

from app.exchanges.base.websockets_client import ThreadedWebSocketClient


class BinanceWebSocketClient(ThreadedWebSocketClient):
    def __init__(self, url: str, **kwargs: object) -> None:
        super().__init__(url, name="Binance", **kwargs)
        self._request_ids = count(1)

    def _normalize_subscription(self, subscription: object) -> str:
        if not isinstance(subscription, str) or not subscription:
            raise ValueError("Binance subscriptions must be non-empty stream names")
        return subscription

    def _control_message(self, method: str, subscriptions: list[object]) -> str:
        return json.dumps(
            {
                "method": method,
                "params": subscriptions,
                "id": str(next(self._request_ids)),
            },
            separators=(",", ":"),
        )

    def _subscription_message(self, subscriptions: list[object]) -> str:
        return self._control_message("SUBSCRIBE", subscriptions)

    def _unsubscription_message(self, subscriptions: list[object]) -> str:
        return self._control_message("UNSUBSCRIBE", subscriptions)


class BinancePrivateWebSocketClient(BinanceWebSocketClient):
    """Private streams are server-selected and reject market subscriptions."""

    def subscribe(self, *subscriptions: object) -> None:
        raise NotImplementedError(
            "Binance private streams do not accept market subscriptions"
        )

    def unsubscribe(self, *subscriptions: object) -> None:
        raise NotImplementedError(
            "Binance private streams do not accept market subscriptions"
        )
