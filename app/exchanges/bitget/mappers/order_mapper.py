"""Normalize Bitget UTA REST and private order/fill messages."""

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from app.domain.exceptions import OrderDataError
from app.domain.enums import Exchange, MarketType
from app.domain.instruments.instrument import Instrument
from app.domain.orders.client_order_id import ClientOrderId
from app.domain.orders.fill import Fill, OrderFill
from app.domain.orders.order import (
    Order,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)


_STATUS = {
    "live": OrderStatus.NEW,
    "new": OrderStatus.NEW,
    "partially_filled": OrderStatus.PARTIALLY_FILLED,
    "filled": OrderStatus.FILLED,
    "cancelled": OrderStatus.CANCELED,
    "canceled": OrderStatus.CANCELED,
    "rejected": OrderStatus.REJECTED,
}

_CATEGORY = {
    "spot": MarketType.SPOT,
    "usdt-futures": MarketType.USDT_PERPETUAL,
}


def private_subscriptions() -> tuple[dict[str, str], ...]:
    return (
        {"instType": "UTA", "topic": "order"},
        {"instType": "UTA", "topic": "fill"},
    )


def _object(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise OrderDataError(f"{path} must be an object")
    return value


def _text(data: Mapping[str, Any], field: str, path: str) -> str:
    value = data.get(field)
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    raise OrderDataError(f"{path}.{field} must be a non-empty string")


def _decimal(data: Mapping[str, Any], field: str, path: str) -> Decimal:
    raw = data.get(field)
    if not isinstance(raw, str) or not raw.strip():
        raise OrderDataError(f"{path}.{field} must be a decimal string")
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise OrderDataError(f"{path}.{field} must be a decimal string") from None
    if not value.is_finite():
        raise OrderDataError(f"{path}.{field} must be a finite decimal string")
    return value


def _price(data: Mapping[str, Any], path: str) -> Decimal:
    raw = data.get("price")
    if raw in (None, ""):
        return Decimal(0)
    return _decimal(data, "price", path)


def _timestamp(value: object, path: str) -> datetime:
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        value = int(value)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise OrderDataError(f"{path} must be milliseconds")
    return datetime.fromtimestamp(value // 1000, timezone.utc) + timedelta(
        milliseconds=value % 1000
    )


def _enum(enum_type: type, raw: str, field: str):
    try:
        return enum_type(raw.lower())
    except ValueError:
        raise OrderDataError(f"unknown Bitget {field} {raw!r}") from None


def _status(raw: str) -> OrderStatus:
    try:
        return _STATUS[raw.lower()]
    except KeyError:
        raise OrderDataError(f"unknown Bitget order status {raw!r}") from None


def _market(data: Mapping[str, Any], path: str) -> MarketType:
    raw = _text(data, "category", path).lower()
    try:
        return _CATEGORY[raw]
    except KeyError:
        raise OrderDataError(f"unknown Bitget order category {raw!r}") from None


def _instrument(
    data: Mapping[str, Any],
    instruments: Mapping[tuple[MarketType, str], Instrument],
    path: str,
) -> Instrument:
    market = _market(data, path)
    symbol = _text(data, "symbol", path)
    try:
        instrument = instruments[(market, symbol)]
    except KeyError:
        raise OrderDataError(
            f"unknown Bitget {market.value} order symbol {symbol!r}"
        ) from None
    if instrument.market_type is not market:
        raise OrderDataError(f"{path}.category does not match the instrument")
    if instrument.exchange is not Exchange.BITGET:
        raise OrderDataError(f"{path} requires a Bitget instrument")
    return instrument


def _fees(data: Mapping[str, Any], path: str) -> tuple[Decimal, str | None]:
    raw = data.get("feeDetail", [])
    if not isinstance(raw, list):
        raise OrderDataError(f"{path}.feeDetail must be an array")
    fees: list[tuple[str, Decimal]] = []
    for index, item in enumerate(raw):
        detail_path = f"{path}.feeDetail[{index}]"
        detail = _object(item, detail_path)
        fees.append(
            (
                _text(detail, "feeCoin", detail_path),
                _decimal(detail, "fee", detail_path),
            )
        )
    assets = {asset for asset, _ in fees}
    if len(assets) > 1:
        raise OrderDataError(f"{path}.feeDetail uses incompatible fee assets")
    return sum((fee for _, fee in fees), Decimal(0)), next(iter(assets), None)


def submitted_order(
    request: OrderRequest,
    payload: object,
    received_time: datetime,
) -> Order:
    root = _object(payload, "payload")
    data = _object(root.get("data"), "payload.data")
    client_id = _text(data, "clientOid", "payload.data")
    if client_id != str(request.client_order_id):
        raise OrderDataError("Bitget clientOid does not match order request")
    return Order(
        instrument=request.instrument,
        client_order_id=request.client_order_id,
        exchange_order_id=_text(data, "orderId", "payload.data"),
        side=request.side,
        order_type=request.order_type,
        time_in_force=request.time_in_force,
        original_quantity=request.quantity,
        price=request.price,
        status=OrderStatus.SUBMITTED,
        cumulative_filled_quantity=Decimal(0),
        average_price=Decimal(0),
        cumulative_fee=Decimal(0),
        fee_asset=None,
        fills=(),
        updated_time=_timestamp(root.get("requestTime"), "payload.requestTime") if root.get("requestTime") is not None else received_time,
    )


def parse_order(
    payload: object,
    instrument: Instrument,
    received_time: datetime,
    request: OrderRequest | None = None,
) -> Order:
    root = _object(payload, "payload")
    if isinstance(root.get("data"), Mapping) and "orderId" not in root:
        root = _object(root.get("data"), "payload.data")
    path = "order"
    if _market(root, path) is not instrument.market_type:
        raise OrderDataError("order.category does not match the instrument")
    cumulative = _decimal(root, "cumExecQty", path)
    quantity = _decimal(root, "qty", path)
    if (
        request is not None
        and request.instrument.market_type is MarketType.SPOT
        and request.order_type is OrderType.MARKET
        and request.side is OrderSide.BUY
    ):
        quantity = request.quantity
    elif quantity <= 0:
        if request is not None:
            quantity = request.quantity
        elif cumulative > 0:
            quantity = cumulative
        else:
            raise OrderDataError("order.qty must be positive without its request")
    price = _price(root, path)
    average = _decimal(root, "avgPrice", path)
    fee, fee_asset = _fees(root, path)
    return Order(
        instrument=instrument,
        client_order_id=ClientOrderId(_text(root, "clientOid", path)),
        exchange_order_id=_text(root, "orderId", path),
        side=_enum(OrderSide, _text(root, "side", path), "side"),
        order_type=_enum(OrderType, _text(root, "orderType", path), "type"),
        time_in_force=_enum(TimeInForce, _text(root, "timeInForce", path), "time in force"),
        original_quantity=quantity,
        price=None if price == 0 else price,
        status=_status(_text(root, "orderStatus", path)),
        cumulative_filled_quantity=cumulative,
        average_price=average,
        cumulative_fee=fee,
        fee_asset=fee_asset,
        fills=(),
        updated_time=(
            _timestamp(root.get("updatedTime"), "order.updatedTime")
            if root.get("updatedTime") is not None
            else received_time
        ),
    )


def _parse_fill(
    data: Mapping[str, Any],
    instrument: Instrument,
    path: str,
) -> OrderFill:
    if _market(data, path) is not instrument.market_type:
        raise OrderDataError(f"{path}.category does not match the instrument")
    fee, fee_asset = _fees(data, path)
    if fee_asset is None:
        raise OrderDataError(f"{path}.feeDetail must identify the fee asset")
    return OrderFill(
        instrument=instrument,
        client_order_id=ClientOrderId(_text(data, "clientOid", path)),
        exchange_order_id=_text(data, "orderId", path),
        fill=Fill(
            fill_id=_text(data, "execId", path),
            price=_decimal(data, "execPrice", path),
            quantity=_decimal(data, "execQty", path),
            fee=fee,
            fee_asset=fee_asset,
            executed_time=_fill_timestamp(data, path),
        ),
    )


def parse_private_message(
    message: object,
    instruments: Mapping[tuple[MarketType, str], Instrument],
    received_time: datetime,
) -> tuple[Order | OrderFill, ...] | None:
    root = _object(message, "message")
    control = root.get("event")
    if control in ("login", "subscribe", "unsubscribe"):
        return None
    if control is not None:
        raise OrderDataError(f"Bitget private control event {control!r}")
    arg = _object(root.get("arg"), "message.arg")
    if arg.get("instType") != "UTA":
        raise OrderDataError("Bitget private order message requires UTA instType")
    topic = arg.get("topic")
    if topic in ("account", "position"):
        return None
    if topic not in ("order", "fill"):
        raise OrderDataError(f"unknown Bitget private order topic {topic!r}")
    action = root.get("action")
    if action not in ("snapshot", "update"):
        raise OrderDataError("Bitget private order action must be snapshot or update")
    raw_data = root.get("data")
    if not isinstance(raw_data, list):
        raise OrderDataError("message.data must be an array")
    if action == "update" and not raw_data:
        raise OrderDataError("Bitget private order update data must not be empty")
    normalized: list[Order | OrderFill] = []
    for index, item in enumerate(raw_data):
        path = f"message.data[{index}]"
        data = _object(item, path)
        instrument = _instrument(data, instruments, path)
        normalized.append(
            parse_order(data, instrument, received_time)
            if topic == "order"
            else _parse_fill(data, instrument, path)
        )
    return tuple(normalized)


def parse_fills(
    payload: object,
    instruments: Mapping[tuple[MarketType, str], Instrument],
) -> tuple[OrderFill, ...]:
    root = _object(payload, "payload")
    data = _object(root.get("data"), "payload.data")
    raw = data.get("list")
    if not isinstance(raw, list):
        raise OrderDataError("payload.data.list must be an array")
    normalized = []
    for index, item in enumerate(raw):
        path = f"payload.data.list[{index}]"
        detail = _object(item, path)
        instrument = _instrument(detail, instruments, path)
        normalized.append(_parse_fill(detail, instrument, path))
    return tuple(normalized)


def _fill_timestamp(data: Mapping[str, Any], path: str) -> datetime:
    for field in ("execTime", "createdTime", "updatedTime"):
        if data.get(field) is not None:
            return _timestamp(data.get(field), f"{path}.{field}")
    raise OrderDataError(
        f"{path} must contain execTime, createdTime, or updatedTime"
    )
