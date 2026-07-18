"""Bitget Spot production public WebSocket client."""

from app.exchanges.bitget.constants import BITGET_PUBLIC_WS_URL
from app.exchanges.bitget.websocket.client import BitgetWebSocketClient


class BitgetSpotPublicWebSocketClient(BitgetWebSocketClient):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(BITGET_PUBLIC_WS_URL, **kwargs)
