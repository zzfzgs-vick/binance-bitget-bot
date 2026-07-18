"""Binance USD-margined futures private stream production entry point."""

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
