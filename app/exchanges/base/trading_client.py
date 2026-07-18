"""Small protocol consumed by order execution services."""

from typing import Protocol

from app.domain.orders.order import Order, OrderRequest


class TradingClient(Protocol):
    def create_order(self, request: OrderRequest) -> Order: ...

    def query_order(self, request: OrderRequest) -> Order: ...

    def cancel_order(self, request: OrderRequest) -> object: ...
