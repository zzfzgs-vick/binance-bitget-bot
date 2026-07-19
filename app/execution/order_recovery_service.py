"""Client-order-id idempotency and timeout state recovery."""

import logging
import json
from dataclasses import dataclass
from pathlib import Path
import threading
from decimal import Decimal
from datetime import datetime

from app.domain.exceptions import OrderDataError
from app.domain.enums import Exchange, MarketType, TradingStatus
from app.domain.arbitrage.arbitrage_position import (
    ArbitragePosition,
    ArbitragePositionLeg,
    PositionStatus,
)
from app.domain.instruments.instrument import Instrument, TradingRules
from app.domain.orders.client_order_id import ClientOrderId
from app.domain.orders.order import (
    FuturesPositionSide,
    Order,
    OrderRequest,
    OrderSide,
    OrderType,
    TimeInForce,
)
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


@dataclass(frozen=True, slots=True)
class RecoveryContext:
    operation_id: str
    kind: str
    requests: tuple[OrderRequest, ...]
    position: ArbitragePosition | None = None
    requires_confirmation: bool = False


class IdempotentOrderService:
    """Never sends a second create request for the same client order id."""

    def __init__(
        self,
        *,
        logger: logging.Logger | None = None,
        journal_path: Path | None = None,
    ) -> None:
        self._logger = logger or _LOGGER
        self._requests: dict[tuple[str, str], OrderRequest] = {}
        self._submitted_requests: dict[tuple[str, str], OrderRequest] = {}
        self._orders: dict[tuple[str, str], Order] = {}
        self._uncertain: set[tuple[str, str]] = set()
        self._attempted: set[tuple[str, str]] = set()
        self._contexts: dict[str, RecoveryContext] = {}
        self._lock = threading.RLock()
        self._journal_path = journal_path
        self._load_journal()

    @property
    def pending_requests(self) -> tuple[OrderRequest, ...]:
        with self._lock:
            return tuple(self._submitted_requests.values())

    @property
    def recovery_contexts(self) -> tuple[RecoveryContext, ...]:
        with self._lock:
            return tuple(self._contexts.values())

    def register_context(
        self,
        operation_id: str,
        kind: str,
        requests: tuple[OrderRequest, ...],
        position: ArbitragePosition | None = None,
    ) -> None:
        if not operation_id.strip() or kind not in {"open", "close"}:
            raise ValueError("recovery context requires an id and open/close kind")
        if not requests or not all(isinstance(item, OrderRequest) for item in requests):
            raise TypeError("recovery context requests must contain OrderRequest values")
        if position is not None and not isinstance(position, ArbitragePosition):
            raise TypeError("recovery context position must be ArbitragePosition")
        with self._lock:
            known = self._contexts.get(operation_id)
            if known is not None and known.kind != kind:
                raise OrderDataError("operation id has a different recovery context kind")
            context = RecoveryContext(
                operation_id,
                kind,
                requests,
                position,
                bool(known and known.requires_confirmation),
            )
            self._contexts[operation_id] = context
            self._write_journal()

    def complete_context(self, operation_id: str) -> None:
        with self._lock:
            context = self._contexts.pop(operation_id, None)
            if context is not None:
                for request in context.requests:
                    key = _key(request)
                    order = self._orders.get(key)
                    if order is not None and order.is_terminal:
                        self._submitted_requests.pop(key, None)
                        self._uncertain.discard(key)
            self._write_journal()

    def set_confirmation_required(
        self, operation_id: str, required: bool
    ) -> None:
        if not isinstance(required, bool):
            raise TypeError("confirmation flag must be bool")
        with self._lock:
            context = self._contexts.get(operation_id)
            if context is None:
                raise OrderDataError(
                    f"unknown recovery context {operation_id!r}"
                )
            self._contexts[operation_id] = RecoveryContext(
                context.operation_id,
                context.kind,
                context.requests,
                context.position,
                required,
            )
            self._write_journal()

    def confirmation_required(self, operation_id: str) -> bool:
        with self._lock:
            context = self._contexts.get(operation_id)
            return bool(context and context.requires_confirmation)

    def known_order(self, request: OrderRequest) -> Order | None:
        with self._lock:
            return self._orders.get(_key(request))

    def recover_pending(self, clients: dict[tuple[Exchange, MarketType], TradingClient]) -> None:
        """Query every persisted client id before allowing a replacement create."""
        for request in self.pending_requests:
            client = clients.get((request.instrument.exchange, request.instrument.market_type))
            if client is None:
                continue
            try:
                self._recover(client, request, _key(request))
            except OrderStateUnknownError:
                self._logger.warning(
                    "Persisted order remains unknown exchange=%s client_order_id=%s",
                    request.instrument.exchange.value,
                    request.client_order_id,
                )

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
                self._write_journal()
            else:
                normalized = self._submitted_requests[key]
        if uncertain:
            return self._recover(client, normalized, key)
        return self._send_prepared(client, normalized, key)

    def confirm_and_submit(
        self,
        client: TradingClient,
        request: OrderRequest,
        operation_id: str,
    ) -> Order:
        """Persist confirmation and the attempted client id in one journal replace."""
        normalized = prepare_order(request)
        key = _key(normalized)
        with self._lock:
            context = self._contexts.get(operation_id)
            if context is None or not context.requires_confirmation:
                raise OrderDataError("order submission has no pending confirmation")
            if request not in context.requests:
                raise OrderDataError("confirmed order is not part of the recovery context")
            original = self._requests.get(key)
            if original is not None and original != request:
                raise OrderDataError(
                    "client order id is already assigned to a different order request"
                )
            if key in self._attempted:
                raise DuplicateOrderSubmissionError(
                    f"order {request.client_order_id} has already been submitted"
                )
            self._requests[key] = request
            self._submitted_requests[key] = normalized
            self._attempted.add(key)
            self._contexts[operation_id] = RecoveryContext(
                context.operation_id,
                context.kind,
                context.requests,
                context.position,
                False,
            )
            self._write_journal()
        return self._send_prepared(client, normalized, key)

    def _send_prepared(
        self,
        client: TradingClient,
        normalized: OrderRequest,
        key: tuple[str, str],
    ) -> Order:
        try:
            order = client.create_order(normalized)
        except ExchangeRestError as exc:
            if not _requires_lookup(exc):
                with self._lock:
                    self._submitted_requests.pop(key, None)
                    self._write_journal()
                raise
            with self._lock:
                self._uncertain.add(key)
                self._write_journal()
            self._logger.warning(
                "Order submission outcome uncertain; querying state exchange=%s client_order_id=%s",
                normalized.instrument.exchange.value,
                normalized.client_order_id,
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
            self._finish_if_terminal(key, order)
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
            key = _order_key(order)
            self._orders[key] = order
            self._uncertain.discard(key)
            self._finish_if_terminal(key, order)

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
            self._finish_if_terminal(key, order)
        return order

    def _finish_if_terminal(self, key: tuple[str, str], order: Order) -> None:
        active = any(
            any(_key(request) == key for request in context.requests)
            for context in self._contexts.values()
        )
        if order.is_terminal and not active:
            self._submitted_requests.pop(key, None)
            self._uncertain.discard(key)
        self._write_journal()

    def _load_journal(self) -> None:
        path = self._journal_path
        if path is None or not path.is_file():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            requests = tuple(_decode_request(item) for item in payload.get("orders", ()))
            contexts = tuple(_decode_context(item) for item in payload.get("contexts", ()))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise OrderDataError(f"invalid order recovery journal: {exc}") from None
        for request in requests:
            key = _key(request)
            self._requests[key] = request
            self._submitted_requests[key] = request
            self._attempted.add(key)
            self._uncertain.add(key)
        self._contexts = {context.operation_id: context for context in contexts}

    def _write_journal(self) -> None:
        path = self._journal_path
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "orders": [_encode_request(request) for request in self._submitted_requests.values()],
            "contexts": [
                {
                    "operation_id": context.operation_id,
                    "kind": context.kind,
                    "requests": [_encode_request(request) for request in context.requests],
                    "position": (
                        None if context.position is None else _encode_position(context.position)
                    ),
                    "requires_confirmation": context.requires_confirmation,
                }
                for context in self._contexts.values()
            ],
        }
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(path)


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


def _encode_request(request: OrderRequest) -> dict[str, object]:
    instrument = request.instrument
    return {
        **_encode_instrument(instrument),
        "side": request.side.value,
        "order_type": request.order_type.value,
        "quantity": str(request.quantity),
        "client_order_id": str(request.client_order_id),
        "price": None if request.price is None else str(request.price),
        "reference_price": (
            None if request.reference_price is None else str(request.reference_price)
        ),
        "time_in_force": request.time_in_force.value,
        "position_side": (
            None if request.position_side is None else request.position_side.value
        ),
        "reduce_only": request.reduce_only,
    }


def _decode_request(item: object) -> OrderRequest:
    if not isinstance(item, dict):
        raise TypeError("journal order must be an object")
    values = item
    instrument = _decode_instrument(values)
    price = values["price"]
    reference_price = values["reference_price"]
    position_side = values["position_side"]
    return OrderRequest(
        instrument=instrument,
        side=OrderSide(str(values["side"])),
        order_type=OrderType(str(values["order_type"])),
        quantity=Decimal(str(values["quantity"])),
        client_order_id=ClientOrderId(str(values["client_order_id"])),
        price=None if price is None else Decimal(str(price)),
        reference_price=(
            None if reference_price is None else Decimal(str(reference_price))
        ),
        time_in_force=TimeInForce(str(values["time_in_force"])),
        position_side=(
            None if position_side is None else FuturesPositionSide(str(position_side))
        ),
        reduce_only=values.get("reduce_only", False),
    )


def _decode_context(item: object) -> RecoveryContext:
    if not isinstance(item, dict):
        raise TypeError("journal context must be an object")
    operation_id = item.get("operation_id")
    kind = item.get("kind")
    requests = item.get("requests")
    if not isinstance(operation_id, str) or not isinstance(kind, str):
        raise TypeError("journal context id and kind must be strings")
    if not isinstance(requests, list):
        raise TypeError("journal context requests must be an array")
    requires_confirmation = item.get("requires_confirmation", False)
    if not isinstance(requires_confirmation, bool):
        raise TypeError("journal confirmation flag must be bool")
    return RecoveryContext(
        operation_id,
        kind,
        tuple(_decode_request(request) for request in requests),
        (
            None
            if item.get("position") is None
            else _decode_position(item["position"])
        ),
        requires_confirmation,
    )


def _encode_instrument(instrument: Instrument) -> dict[str, object]:
    rules = instrument.rules
    return {
        "exchange": instrument.exchange.value,
        "market_type": instrument.market_type.value,
        "symbol": instrument.raw_symbol,
        "base": instrument.base_asset,
        "quote": instrument.quote_asset,
        "settlement": instrument.settlement_asset,
        "status": instrument.status.value,
        "raw_status": instrument.raw_status,
        "rules": {
            "tick_size": str(rules.tick_size),
            "quantity_step": str(rules.quantity_step),
            "minimum_quantity": str(rules.minimum_quantity),
            "maximum_quantity": None if rules.maximum_quantity is None else str(rules.maximum_quantity),
            "minimum_notional": str(rules.minimum_notional),
            "contract_multiplier": str(rules.contract_multiplier),
        },
    }


def _decode_instrument(values: dict[str, object]) -> Instrument:
    rules_value = values["rules"]
    if not isinstance(rules_value, dict):
        raise TypeError("journal rules must be an object")
    maximum = rules_value["maximum_quantity"]
    return Instrument(
        exchange=Exchange(str(values["exchange"])),
        market_type=MarketType(str(values["market_type"])),
        raw_symbol=str(values["symbol"]),
        base_asset=str(values["base"]),
        quote_asset=str(values["quote"]),
        settlement_asset=str(values["settlement"]),
        rules=TradingRules(
            Decimal(str(rules_value["tick_size"])),
            Decimal(str(rules_value["quantity_step"])),
            Decimal(str(rules_value["minimum_quantity"])),
            None if maximum is None else Decimal(str(maximum)),
            Decimal(str(rules_value["minimum_notional"])),
            Decimal(str(rules_value["contract_multiplier"])),
        ),
        status=TradingStatus(str(values["status"])),
        raw_status=str(values["raw_status"]),
    )


def _encode_position(position: ArbitragePosition) -> dict[str, object]:
    def leg(value: ArbitragePositionLeg) -> dict[str, object]:
        return {
            "instrument": _encode_instrument(value.instrument),
            "opening_side": value.opening_side.value,
            "opening_order_id": value.opening_order_id,
            "open_quantity": str(value.open_quantity),
            "remaining_quantity": str(value.remaining_quantity),
            "open_average_price": str(value.open_average_price),
            "open_fee": str(value.open_fee),
            "fee_asset": value.fee_asset,
            "position_side": None if value.position_side is None else value.position_side.value,
        }
    return {
        "position_id": position.position_id,
        "first_leg": leg(position.first_leg),
        "second_leg": leg(position.second_leg),
        "opened_at": position.opened_at.isoformat(),
        "status": position.status.value,
        "realized_pnl": str(position.realized_pnl),
        "unrealized_pnl": str(position.unrealized_pnl),
    }


def _decode_position(item: object) -> ArbitragePosition:
    if not isinstance(item, dict):
        raise TypeError("journal position must be an object")
    def leg(value: object) -> ArbitragePositionLeg:
        if not isinstance(value, dict) or not isinstance(value.get("instrument"), dict):
            raise TypeError("journal position leg must be an object")
        side = value.get("position_side")
        return ArbitragePositionLeg(
            instrument=_decode_instrument(value["instrument"]),
            opening_side=OrderSide(str(value["opening_side"])),
            opening_order_id=str(value["opening_order_id"]),
            open_quantity=Decimal(str(value["open_quantity"])),
            remaining_quantity=Decimal(str(value["remaining_quantity"])),
            open_average_price=Decimal(str(value["open_average_price"])),
            open_fee=Decimal(str(value["open_fee"])),
            fee_asset=None if value.get("fee_asset") is None else str(value["fee_asset"]),
            position_side=None if side is None else FuturesPositionSide(str(side)),
        )
    return ArbitragePosition(
        position_id=str(item["position_id"]),
        first_leg=leg(item["first_leg"]),
        second_leg=leg(item["second_leg"]),
        opened_at=datetime.fromisoformat(str(item["opened_at"])),
        status=PositionStatus(str(item["status"])),
        realized_pnl=Decimal(str(item["realized_pnl"])),
        unrealized_pnl=Decimal(str(item["unrealized_pnl"])),
    )
