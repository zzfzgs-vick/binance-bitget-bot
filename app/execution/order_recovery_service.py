"""Client-order-id idempotency and timeout state recovery."""

import logging
import threading

from app.domain.exceptions import OrderDataError
from app.domain.orders.order import Order, OrderRequest
from app.exchanges.base.exchange_errors import (
    ExchangeApiError,
    ExchangeHttpError,
    ExchangeRestError,
    ExchangeResponseError,
    ExchangeTimeoutError,
)
from app.exchanges.base.trading_client import TradingClient
from app.execution.preflight_validator import prepare_order


_LOGGER = logging.getLogger("binance_bitget_bot.execution.orders")


class OrderStateUnknownError(RuntimeError):
    """An accepted-or-rejected submission cannot yet be distinguished."""


class DuplicateOrderSubmissionError(RuntimeError):
    """A create request already ran for this client order id."""


class IdempotentOrderService:
    """Never sends a second create request for the same client order id."""

    def __init__(self, *, logger: logging.Logger | None = None) -> None:
        self._logger = logger or _LOGGER
        self._requests: dict[tuple[str, str], OrderRequest] = {}
        self._submitted_requests: dict[tuple[str, str], OrderRequest] = {}
        self._orders: dict[tuple[str, str], Order] = {}
        self._uncertain: set[tuple[str, str]] = set()
        self._attempted: set[tuple[str, str]] = set()
        self._lock = threading.RLock()

    def submit(self, client: TradingClient, request: OrderRequest) -> Order:
        key = _key(request)
        with self._lock:
            original = self._requests.get(key)
            if original is not None and original != request:
                raise OrderDataError(
                    "client order id is already assigned to a different order request"
                )
            known = self._orders.get(key)
            if known is not None:
                return known
            uncertain = key in self._uncertain
            if not uncertain and key in self._attempted:
                raise DuplicateOrderSubmissionError(
                    f"order {request.client_order_id} has already been submitted"
                )
            if not uncertain:
                self._requests[key] = request
                normalized = prepare_order(request)
                self._submitted_requests[key] = normalized
                self._attempted.add(key)
            else:
                normalized = self._submitted_requests[key]
        if uncertain:
            return self._recover(client, normalized, key)
        try:
            order = client.create_order(normalized)
        except ExchangeRestError as exc:
            if not _requires_lookup(exc):
                raise
            with self._lock:
                self._uncertain.add(key)
            self._logger.warning(
                "Order submission outcome uncertain; querying state exchange=%s client_order_id=%s",
                request.instrument.exchange.value,
                request.client_order_id,
            )
            return self._recover(client, normalized, key)
        try:
            _validate_recovered_order(normalized, order)
        except OrderDataError:
            with self._lock:
                self._uncertain.add(key)
            return self._recover(client, normalized, key)
        with self._lock:
            self._orders[key] = order
        return order

    def refresh(self, client: TradingClient, request: OrderRequest) -> Order:
        key = _key(request)
        with self._lock:
            self._requests.setdefault(key, request)
            normalized = self._submitted_requests.get(key)
            if normalized is None:
                normalized = prepare_order(request)
                self._submitted_requests[key] = normalized
        return self._recover(client, normalized, key)

    def record(self, order: Order) -> None:
        with self._lock:
            self._orders[_order_key(order)] = order
            self._uncertain.discard(_order_key(order))

    def _recover(
        self,
        client: TradingClient,
        request: OrderRequest,
        key: tuple[str, str],
    ) -> Order:
        try:
            order = client.query_order(request)
        except ExchangeRestError:
            with self._lock:
                self._uncertain.add(key)
            raise OrderStateUnknownError(
                f"order {request.client_order_id} state is unknown and must not be resubmitted"
            ) from None
        _validate_recovered_order(request, order)
        with self._lock:
            self._orders[key] = order
            self._uncertain.discard(key)
        return order


def _key(request: OrderRequest) -> tuple[str, str]:
    return request.instrument.exchange.value, str(request.client_order_id)


def _order_key(order: Order) -> tuple[str, str]:
    return order.instrument.exchange.value, str(order.client_order_id)


def _requires_lookup(error: ExchangeRestError) -> bool:
    if isinstance(error, (ExchangeTimeoutError, ExchangeResponseError)):
        return True
    if isinstance(error, ExchangeHttpError) and error.status_code >= 500:
        return True
    if not isinstance(error, ExchangeApiError):
        return False
    return str(error.api_code) in {
        "-1007",
        "25001",
        "25212",
        "40010",
        "40725",
        "45001",
    }


def _validate_recovered_order(request: OrderRequest, order: Order) -> None:
    if (
        order.instrument != request.instrument
        or order.client_order_id != request.client_order_id
        or order.side is not request.side
        or order.order_type is not request.order_type
        or order.original_quantity != request.quantity
    ):
        raise OrderDataError(
            "queried order does not match the original client order request"
        )
