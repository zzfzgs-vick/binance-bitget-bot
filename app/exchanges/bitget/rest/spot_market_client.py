"""Bitget Spot public REST capabilities required by Stage 3."""

from typing import Any

from app.exchanges.bitget.constants import (
    BITGET_INSTRUMENTS_PATH,
    BITGET_SERVER_TIME_PATH,
)
from app.exchanges.bitget.rest.base_client import BitgetRestClient


class BitgetSpotMarketClient(BitgetRestClient):
    def get_server_time(self) -> Any:
        return self.public_request("GET", BITGET_SERVER_TIME_PATH)

    def get_raw_product_info(self) -> Any:
        return self.public_request(
            "GET", BITGET_INSTRUMENTS_PATH, {"category": "SPOT"}
        )
