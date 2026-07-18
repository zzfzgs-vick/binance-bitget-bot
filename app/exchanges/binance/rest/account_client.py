"""Synchronous signed Binance account snapshot requests."""

from typing import Any

from app.exchanges.binance.constants import (
    BINANCE_FUTURES_ACCOUNT_PATH,
    BINANCE_FUTURES_BASE_URL,
    BINANCE_FUTURES_POSITIONS_PATH,
    BINANCE_SPOT_ACCOUNT_PATH,
    BINANCE_SPOT_BASE_URL,
)
from app.exchanges.binance.rest.base_client import BinanceRestClient


class BinanceSpotAccountClient(BinanceRestClient):
    BASE_URL = BINANCE_SPOT_BASE_URL

    def get_account(self) -> Any:
        return self.private_request("GET", BINANCE_SPOT_ACCOUNT_PATH)


class BinanceFuturesAccountClient(BinanceRestClient):
    BASE_URL = BINANCE_FUTURES_BASE_URL

    def get_account(self) -> Any:
        return self.private_request("GET", BINANCE_FUTURES_ACCOUNT_PATH)

    def get_positions(self) -> Any:
        return self.private_request("GET", BINANCE_FUTURES_POSITIONS_PATH)
