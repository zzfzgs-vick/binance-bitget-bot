"""Binance USD-margined futures production public WebSocket client."""

from app.exchanges.binance.constants import (
    BINANCE_FUTURES_MARKET_WS_URL,
    BINANCE_FUTURES_PUBLIC_WS_URL,
)
from app.exchanges.binance.websocket.client import BinanceWebSocketClient


_ROUTES = {
    "public": BINANCE_FUTURES_PUBLIC_WS_URL,
    "market": BINANCE_FUTURES_MARKET_WS_URL,
}


class BinanceFuturesPublicWebSocketClient(BinanceWebSocketClient):
    def __init__(self, *, route: str = "public", **kwargs: object) -> None:
        try:
            url = _ROUTES[route]
        except KeyError:
            raise ValueError("Binance futures route must be public or market") from None
        super().__init__(url, **kwargs)
