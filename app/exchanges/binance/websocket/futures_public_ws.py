"""Binance USD-margined futures production public WebSocket client."""

from app.exchanges.binance.constants import BINANCE_FUTURES_PUBLIC_WS_URL
from app.exchanges.binance.websocket.client import BinanceWebSocketClient

class BinanceFuturesPublicWebSocketClient(BinanceWebSocketClient):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(BINANCE_FUTURES_PUBLIC_WS_URL, **kwargs)
