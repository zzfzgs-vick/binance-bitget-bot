"""Bitget futures production private WebSocket client."""

from app.exchanges.bitget.constants import BITGET_PRIVATE_WS_URL
from app.exchanges.bitget.websocket.client import BitgetPrivateWebSocketClient
from app.infrastructure.security.credential_store import ApiCredentials


class BitgetFuturesPrivateWebSocketClient(BitgetPrivateWebSocketClient):
    def __init__(self, credentials: ApiCredentials, **kwargs: object) -> None:
        super().__init__(BITGET_PRIVATE_WS_URL, credentials, **kwargs)
