"""Normalize Binance REST and private-stream order messages."""

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from app.domain.enums import Exchange, MarketType
from app.domain.exceptions import OrderDataError
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
    "NEW": OrderStatus.NEW,
    "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
    "FILLED": OrderStatus.FILLED,
    "CANCELED": OrderStatus.CANCELED,
    "PENDING_CANCEL": OrderStatus.CANCELED,
    "REJECTED": OrderStatus.REJECTED,
    "EXPIRED": OrderStatus.EXPIRED,
    "EXPIRED_IN_MATCH": OrderStatus.EXPIRED,
}


def _object(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise OrderDataError(f"{path} must be an object")
    return value


def _text(data: Mapping[str, Any], *fields: str) -> str:
    for field in fields:
        value = data.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
    raise OrderDataError(f"missing non-empty field {'/'.join(fields)}")


def _decimal(data: Mapping[str, Any], *fields: str) -> Decimal:
    for field in fields:
        raw = data.get(field)
        if isinstance(raw, str) and raw.strip():
            try:
                value = Decimal(raw)
            except InvalidOperation:
                break
            if value.is_finite():
                return value
            break
    raise OrderDataError(f"field {'/'.join(fields)} must be a decimal string")


def _timestamp(value: object, fallback: datetime) -> datetime:
    if value is None:
        return fallback
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        value = int(value)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise OrderDataError("order timestamp must be milliseconds")
    return datetime.fromtimestamp(value // 1000, timezone.utc) + timedelta(
        milliseconds=value % 1000
    )


def _enum(enum_type: type, raw: str, field: str):
    try:
        return enum_type(raw.lower())
    except ValueError:
        raise OrderDataError(f"unknown Binance {field} {raw!r}") from None


def _status(raw: str) -> OrderStatus:
    try:
        return _STATUS[raw]
    except KeyError:
        raise OrderDataError(f"unknown Binance order status {raw!r}") from None


def _fills(data: Mapping[str, Any], event_time: datetime) -> tuple[Fill, ...]:
    raw_fills = data.get("fills")
    if raw_fills is not None:
        if not isinstance(raw_fills, list):
            raise OrderDataError("fills must be an array")
        return tuple(
            Fill(
                fill_id=_text(_object(item, f"fills[{index}]"), "tradeId"),
                price=_decimal(_object(item, f"fills[{index}]"), "price"),
                quantity=_decimal(_object(item, f"fills[{index}]"), "qty"),
                fee=_decimal(_object(item, f"fills[{index}]"), "commission"),
                fee_asset=_text(_object(item, f"fills[{index}]"), "commissionAsset"),
                executed_time=event_time,
            )
            for index, item in enumerate(raw_fills)
        )
    last_quantity = _decimal(data, "l") if "l" in data else Decimal(0)
    if last_quantity == 0:
        return ()
    return (
        Fill(
            fill_id=_text(data, "t"),
            price=_decimal(data, "L"),
            quantity=last_quantity,
            fee=_decimal(data, "n"),
            fee_asset=_text(data, "N"),
            executed_time=_timestamp(data.get("T"), event_time),
        ),
    )


def parse_order(
    payload: object,
    instrument: Instrument,
    received_time: datetime,
    request: OrderRequest | None = None,
) -> Order:
    if instrument.exchange is not Exchange.BINANCE:
        raise OrderDataError("Binance order requires a Binance instrument")
    data = _object(payload, "payload")
    event_time = _timestamp(
        data.get("updateTime", data.get("transactTime", data.get("T", data.get("E")))),
        received_time,
    )
    cumulative = _decimal(data, "executedQty", "z")
    average = Decimal(0)
    if cumulative > 0:
        if "avgPrice" in data or "ap" in data:
            average = _decimal(data, "avgPrice", "ap")
        else:
            average = _decimal(data, "cummulativeQuoteQty", "Z") / cumulative
    price = _decimal(data, "price", "p")
    fills = _fills(data, event_time)
    fee_assets = {fill.fee_asset for fill in fills}
    if len(fee_assets) > 1:
        raise OrderDataError("Binance fills use incompatible fee assets")
    return Order(
        instrument=instrument,
        client_order_id=ClientOrderId(_text(data, "clientOrderId", "c")),
        exchange_order_id=_text(data, "orderId", "i"),
        side=_enum(OrderSide, _text(data, "side", "S"), "side"),
        order_type=_enum(OrderType, _text(data, "type", "o"), "type"),
        time_in_force=_enum(TimeInForce, _text(data, "timeInForce", "f"), "time in force"),
        original_quantity=_decimal(data, "origQty", "q"),
        price=None if price == 0 else price,
        status=_status(_text(data, "status", "X")),
        cumulative_filled_quantity=cumulative,
        average_price=average,
        cumulative_fee=sum((fill.fee for fill in fills), Decimal(0)),
        fee_asset=next(iter(fee_assets), None),
        fills=fills,
        updated_time=event_time,
    )


def parse_private_message(
    message: object,
    instruments: Mapping[tuple[MarketType, str], Instrument],
    received_time: datetime,
) -> Order | None:
    root = _object(message, "message")
    if isinstance(root.get("event"), Mapping):
        root = _object(root.get("event"), "message.event")
    event_type = root.get("e")
    if event_type == "executionReport":
        data = root
        market = MarketType.SPOT
    elif event_type == "ORDER_TRADE_UPDATE":
        data = _object(root.get("o"), "message.o")
        data = dict(data)
        data.setdefault("E", root.get("E"))
        data.setdefault("T", root.get("T"))
        market = MarketType.USDT_PERPETUAL
    elif event_type in ("outboundAccountPosition", "ACCOUNT_UPDATE", "balanceUpdate", "listenKeyExpired"):
        return None
    else:
        raise OrderDataError(f"unknown Binance private order event {event_type!r}")
    symbol = _text(data, "s", "symbol")
    try:
        instrument = instruments[(market, symbol)]
    except KeyError:
        raise OrderDataError(
            f"unknown Binance {market.value} order symbol {symbol!r}"
        ) from None
    if instrument.market_type is not market:
        raise OrderDataError("Binance order event does not match the instrument")
    return parse_order(data, instrument, received_time)


def parse_fills(
    payload: object,
    instrument: Instrument,
    client_order_id: ClientOrderId,
    exchange_order_id: str,
    received_time: datetime,
) -> tuple[OrderFill, ...]:
    if not isinstance(payload, list):
        raise OrderDataError("fill payload must be an array")
    normalized = []
    for index, item in enumerate(payload):
        path = f"fills[{index}]"
        data = _object(item, path)
        if _text(data, "symbol") != instrument.raw_symbol:
            raise OrderDataError(f"{path}.symbol does not match the order")
        if _text(data, "orderId") != exchange_order_id:
            raise OrderDataError(f"{path}.orderId does not match the order")
        normalized.append(
            OrderFill(
                instrument=instrument,
                client_order_id=client_order_id,
                exchange_order_id=exchange_order_id,
                fill=Fill(
                    fill_id=_text(data, "id"),
                    price=_decimal(data, "price"),
                    quantity=_decimal(data, "qty"),
                    fee=_decimal(data, "commission"),
                    fee_asset=_text(data, "commissionAsset"),
                    executed_time=_timestamp(data.get("time"), received_time),
                ),
            )
        )
    return tuple(normalized)
