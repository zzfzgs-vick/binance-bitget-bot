"""Synchronous Binance Spot order operations."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.domain.enums import Exchange, MarketType
from app.domain.orders.order import Order, OrderRequest, OrderType
from app.domain.orders.fill import OrderFill
from app.exchanges.binance.constants import (
    BINANCE_SPOT_COMMISSION_PATH,
    BINANCE_SPOT_BASE_URL,
    BINANCE_SPOT_FILLS_PATH,
    BINANCE_SPOT_ORDER_PATH,
)
from app.exchanges.binance.mappers.order_mapper import parse_fills, parse_order
from app.exchanges.binance.rest.base_client import BinanceRestClient
from app.execution.preflight_validator import prepare_order
from app.infrastructure.decimal.formatting import decimal_text


class BinanceSpotTradingClient(BinanceRestClient):
    BASE_URL = BINANCE_SPOT_BASE_URL

    def get_taker_fee_rate(self, symbol: str) -> Decimal:
        payload = self.private_request(
            "GET", BINANCE_SPOT_COMMISSION_PATH, {"symbol": symbol}
        )
        try:
            return Decimal(payload["standardCommission"]["taker"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("Binance Spot commission response is invalid") from None

    def create_order(self, request: OrderRequest) -> Order:
        _request_market(request)
        request = prepare_order(request)
        payload = self.private_request(
            "POST", BINANCE_SPOT_ORDER_PATH, _create_params(request)
        )
        return parse_order(payload, request.instrument, _now(), request)

    def query_order(self, request: OrderRequest) -> Order:
        _request_market(request)
        payload = self.private_request(
            "GET",
            BINANCE_SPOT_ORDER_PATH,
            {
                "symbol": request.instrument.raw_symbol,
                "origClientOrderId": str(request.client_order_id),
            },
        )
        return parse_order(payload, request.instrument, _now(), request)

    def cancel_order(self, request: OrderRequest) -> Any:
        _request_market(request)
        return self.private_request(
            "DELETE",
            BINANCE_SPOT_ORDER_PATH,
            {
                "symbol": request.instrument.raw_symbol,
                "origClientOrderId": str(request.client_order_id),
            },
        )

    def get_fills(
        self, request: OrderRequest, exchange_order_id: str
    ) -> tuple[OrderFill, ...]:
        _request_market(request)
        payload = self.private_request(
            "GET",
            BINANCE_SPOT_FILLS_PATH,
            {"symbol": request.instrument.raw_symbol, "orderId": exchange_order_id},
        )
        return parse_fills(
            payload,
            request.instrument,
            request.client_order_id,
            exchange_order_id,
            _now(),
        )


def _create_params(request: OrderRequest) -> dict[str, object]:
    params: dict[str, object] = {
        "symbol": request.instrument.raw_symbol,
        "side": request.side.value.upper(),
        "type": request.order_type.value.upper(),
        "quantity": decimal_text(request.quantity),
        "newClientOrderId": str(request.client_order_id),
        "newOrderRespType": "FULL",
    }
    if request.order_type is OrderType.LIMIT:
        assert request.price is not None
        params.update(
            price=decimal_text(request.price),
            timeInForce=request.time_in_force.value.upper(),
        )
    return params


def _request_market(request: OrderRequest) -> None:
    if (
        request.instrument.exchange is not Exchange.BINANCE
        or request.instrument.market_type is not MarketType.SPOT
    ):
        raise ValueError("BinanceSpotTradingClient requires a Binance spot order")


def _now() -> datetime:
    return datetime.now(timezone.utc)
