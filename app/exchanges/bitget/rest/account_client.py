"""Synchronous signed Bitget UTA account snapshot requests."""

from typing import Any

from app.exchanges.bitget.constants import (
    BITGET_ACCOUNT_ASSETS_PATH,
    BITGET_ACCOUNT_SETTINGS_PATH,
    BITGET_POSITIONS_PATH,
)
from app.exchanges.bitget.rest.base_client import BitgetRestClient


class BitgetAccountClient(BitgetRestClient):
    def get_account(self) -> Any:
        return self.private_request("GET", BITGET_ACCOUNT_ASSETS_PATH)

    def get_settings(self) -> Any:
        return self.private_request("GET", BITGET_ACCOUNT_SETTINGS_PATH)

    def get_positions(self) -> Any:
        return self.private_request(
            "GET",
            BITGET_POSITIONS_PATH,
            params={"category": "USDT-FUTURES"},
        )
