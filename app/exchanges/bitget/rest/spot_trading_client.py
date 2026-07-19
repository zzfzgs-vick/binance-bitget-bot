"""Synchronous Bitget UTA Spot order operations."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.domain.enums import Exchange, MarketType
from app.domain.orders.order import Order, OrderRequest, OrderSide, OrderType
from app.domain.orders.fill import OrderFill
from app.exchanges.bitget.constants import (
    BITGET_CANCEL_ORDER_PATH,
    BITGET_FILLS_PATH,
    BITGET_FEE_RATE_PATH,
    BITGET_PLACE_ORDER_PATH,
    BITGET_QUERY_ORDER_PATH,
)
from app.exchanges.bitget.mappers.order_mapper import (
    parse_fills,
    parse_order,
    submitted_order,
)
from app.exchanges.bitget.rest.base_client import BitgetRestClient
from app.execution.preflight_validator import prepare_order
from app.infrastructure.decimal.formatting import decimal_text


class BitgetSpotTradingClient(BitgetRestClient):
    def get_taker_fee_rate(self, symbol: str) -> Decimal:
        payload = self.private_request(
            "GET", BITGET_FEE_RATE_PATH,
            params={"category": "SPOT", "symbol": symbol},
        )
        try:
            return Decimal(payload["data"]["takerFeeRate"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("Bitget Spot fee-rate response is invalid") from None

    def create_order(self, request: OrderRequest) -> Order:
        _request_market(request)
        request = prepare_order(request)
        payload = self.private_request(
            "POST", BITGET_PLACE_ORDER_PATH, body=_create_body(request)
        )
        return submitted_order(request, payload, _now())

    def query_order(self, request: OrderRequest) -> Order:
        _request_market(request)
        request = prepare_order(request)
        payload = self.private_request(
            "GET",
            BITGET_QUERY_ORDER_PATH,
            params={"clientOid": str(request.client_order_id)},
        )
        return parse_order(payload, request.instrument, _now(), request)

    def cancel_order(self, request: OrderRequest) -> Any:
        _request_market(request)
        return self.private_request(
            "POST",
            BITGET_CANCEL_ORDER_PATH,
            body={"clientOid": str(request.client_order_id), "category": "SPOT"},
        )

    def get_fills(
        self, request: OrderRequest, exchange_order_id: str
    ) -> tuple[OrderFill, ...]:
        _request_market(request)
        payload = self.private_request(
            "GET",
            BITGET_FILLS_PATH,
            params={"category": "SPOT", "orderId": exchange_order_id},
        )
        return parse_fills(
            payload,
            {(request.instrument.market_type, request.instrument.raw_symbol): request.instrument},
        )


def _create_body(request: OrderRequest) -> dict[str, str]:
    quantity = request.quantity
    if request.order_type is OrderType.MARKET and request.side is OrderSide.BUY:
        assert request.reference_price is not None
        quantity = quantity * request.reference_price
    body = {
        "category": "SPOT",
        "symbol": request.instrument.raw_symbol,
        "qty": decimal_text(quantity),
        "side": request.side.value,
        "orderType": request.order_type.value,
        "clientOid": str(request.client_order_id),
    }
    if request.order_type is OrderType.LIMIT:
        assert request.price is not None
        body["price"] = decimal_text(request.price)
        body["timeInForce"] = request.time_in_force.value
    return body


def _request_market(request: OrderRequest) -> None:
    if (
        request.instrument.exchange is not Exchange.BITGET
        or request.instrument.market_type is not MarketType.SPOT
    ):
        raise ValueError("BitgetSpotTradingClient requires a Bitget spot order")


def _now() -> datetime:
    return datetime.now(timezone.utc)
