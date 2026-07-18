"""Binance Spot private WebSocket API production entry point."""

from app.exchanges.binance.constants import BINANCE_SPOT_PRIVATE_WS_URL
from app.exchanges.binance.websocket.client import BinancePrivateWebSocketClient


class BinanceSpotPrivateWebSocketClient(BinancePrivateWebSocketClient):
    """Connection foundation only; session authentication is a later stage."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(BINANCE_SPOT_PRIVATE_WS_URL, **kwargs)
