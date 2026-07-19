"""Binance USD-margined futures public REST capabilities for Stage 3."""

from typing import Any

from app.exchanges.binance.constants import (
    BINANCE_FUTURES_BASE_URL,
    BINANCE_FUTURES_EXCHANGE_INFO_PATH,
    BINANCE_FUTURES_DEPTH_PATH,
    BINANCE_FUTURES_TIME_PATH,
)
from app.exchanges.binance.rest.base_client import BinanceRestClient


class BinanceFuturesMarketClient(BinanceRestClient):
    BASE_URL = BINANCE_FUTURES_BASE_URL

    def get_server_time(self) -> Any:
        return self.public_request("GET", BINANCE_FUTURES_TIME_PATH)

    def get_raw_product_info(self) -> Any:
        return self.public_request("GET", BINANCE_FUTURES_EXCHANGE_INFO_PATH)

    def get_order_book(self, symbol: str, *, limit: int = 1000) -> Any:
        return self.public_request(
            "GET", BINANCE_FUTURES_DEPTH_PATH, {"symbol": symbol, "limit": limit}
        )
