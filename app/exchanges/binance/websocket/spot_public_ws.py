"""Binance Spot production public WebSocket client."""

from app.exchanges.binance.constants import BINANCE_SPOT_PUBLIC_WS_URL
from app.exchanges.binance.websocket.client import BinanceWebSocketClient


class BinanceSpotPublicWebSocketClient(BinanceWebSocketClient):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(BINANCE_SPOT_PUBLIC_WS_URL, **kwargs)
