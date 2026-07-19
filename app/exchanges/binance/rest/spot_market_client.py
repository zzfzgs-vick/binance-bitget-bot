"""Binance Spot public REST capabilities required by Stage 3."""

from typing import Any

from app.exchanges.binance.constants import (
    BINANCE_SPOT_BASE_URL,
    BINANCE_SPOT_EXCHANGE_INFO_PATH,
    BINANCE_SPOT_DEPTH_PATH,
    BINANCE_SPOT_TIME_PATH,
)
from app.exchanges.binance.rest.base_client import BinanceRestClient


class BinanceSpotMarketClient(BinanceRestClient):
    BASE_URL = BINANCE_SPOT_BASE_URL

    def get_server_time(self) -> Any:
        return self.public_request("GET", BINANCE_SPOT_TIME_PATH)

    def get_raw_product_info(self) -> Any:
        return self.public_request("GET", BINANCE_SPOT_EXCHANGE_INFO_PATH)

    def get_order_book(self, symbol: str, *, limit: int = 1000) -> Any:
        return self.public_request(
            "GET", BINANCE_SPOT_DEPTH_PATH, {"symbol": symbol, "limit": limit}
        )
