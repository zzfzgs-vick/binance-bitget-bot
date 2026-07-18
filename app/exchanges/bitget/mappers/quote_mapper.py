"""Normalize Bitget UTA public market messages."""

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from app.domain.enums import Exchange, MarketType
from app.domain.exceptions import MarketDataError
from app.domain.instruments.instrument import Instrument
from app.domain.market.funding_snapshot import FundingRateSnapshot
from app.domain.market.market_quote import BestBidAsk
from app.domain.market.order_book import OrderBookUpdate
from app.domain.market.order_book_level import OrderBookLevel


def _object(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MarketDataError(f"{path} must be an object")
    return value


def _objects(value: object, path: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or not value:
        raise MarketDataError(f"{path} must be a non-empty array")
    return [_object(item, f"{path}[{index}]") for index, item in enumerate(value)]


def _text(data: Mapping[str, Any], field: str, path: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise MarketDataError(f"{path}.{field} must be a non-empty string")
    return value.strip()


def _decimal(
    data: Mapping[str, Any], field: str, path: str, *, signed: bool = False
) -> Decimal:
    raw = _text(data, field, path)
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise MarketDataError(f"{path}.{field} must be a decimal string") from None
    if not value.is_finite() or (not signed and value < 0):
        raise MarketDataError(f"{path}.{field} has an invalid decimal value")
    return value


def _integer(value: object, path: str) -> int:
    if isinstance(value, bool):
        raise MarketDataError(f"{path} must be a non-negative integer")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and value.isascii() and value.isdecimal():
        try:
            result = int(value)
        except ValueError:
            raise MarketDataError(
                f"{path} is outside the supported integer range"
            ) from None
    else:
        raise MarketDataError(f"{path} must be a non-negative integer")
    if result < 0:
        raise MarketDataError(f"{path} must be a non-negative integer")
    return result


def _timestamp(value: object, path: str) -> datetime:
    milliseconds = _integer(value, path)
    try:
        return datetime.fromtimestamp(
            milliseconds // 1000, tz=timezone.utc
        ) + timedelta(milliseconds=milliseconds % 1000)
    except (OverflowError, OSError, ValueError):
        raise MarketDataError(f"{path} is outside the supported time range") from None


def _levels(value: object, path: str) -> tuple[OrderBookLevel, ...]:
    if not isinstance(value, list):
        raise MarketDataError(f"{path} must be an array")
    levels = []
    for index, raw_level in enumerate(value):
        level_path = f"{path}[{index}]"
        if not isinstance(raw_level, list) or len(raw_level) != 2:
            raise MarketDataError(f"{level_path} must contain price and quantity")
        level = {"price": raw_level[0], "quantity": raw_level[1]}
        levels.append(
            OrderBookLevel(
                _decimal(level, "price", level_path),
                _decimal(level, "quantity", level_path),
            )
        )
    return tuple(levels)


def market_subscriptions(
    instrument: Instrument,
) -> tuple[dict[str, str], ...]:
    if instrument.exchange is not Exchange.BITGET:
        raise MarketDataError("instrument must belong to Bitget")
    instrument_type = (
        "spot"
        if instrument.market_type is MarketType.SPOT
        else "usdt-futures"
    )
    base = {
        "instType": instrument_type,
        "symbol": instrument.raw_symbol.upper(),
    }
    return (
        {**base, "topic": "ticker"},
        {**base, "topic": "books"},
    )


def parse_message(
    message: object,
    instrument: Instrument,
    received_time: datetime,
) -> tuple[BestBidAsk | FundingRateSnapshot | OrderBookUpdate, ...]:
    if instrument.exchange is not Exchange.BITGET:
        raise MarketDataError("instrument must belong to Bitget")
    payload = _object(message, "message")
    control_event = payload.get("event")
    if control_event in ("subscribe", "unsubscribe"):
        return ()
    if control_event is not None:
        raise MarketDataError(
            f"Bitget WebSocket returned control event {control_event!r}"
        )
    argument = _object(payload.get("arg"), "message.arg")
    topic = _text(argument, "topic", "message.arg")
    if topic not in ("ticker", "books"):
        raise MarketDataError(f"unknown Bitget market topic {topic!r}")
    expected_type = (
        "spot"
        if instrument.market_type is MarketType.SPOT
        else "usdt-futures"
    )
    instrument_type = _text(argument, "instType", "message.arg")
    if instrument_type != expected_type:
        raise MarketDataError("message.arg.instType does not match instrument")
    symbol = _text(argument, "symbol", "message.arg")
    if symbol.upper() != instrument.raw_symbol.upper():
        raise MarketDataError("message.arg.symbol does not match instrument")
    action = payload.get("action")
    if topic == "ticker" and action != "snapshot":
        raise MarketDataError("Bitget ticker action must be snapshot")
    if topic == "books" and action not in ("snapshot", "update"):
        raise MarketDataError("Bitget books action must be snapshot or update")
    event_time = _timestamp(payload.get("ts"), "message.ts")
    events: list[BestBidAsk | FundingRateSnapshot | OrderBookUpdate] = []
    for index, item in enumerate(_objects(payload.get("data"), "message.data")):
        path = f"message.data[{index}]"
        if topic == "books":
            sequence = _integer(item.get("seq"), f"{path}.seq")
            previous_sequence = _integer(
                item.get("pseq"), f"{path}.pseq"
            )
            events.append(
                OrderBookUpdate(
                    instrument=instrument,
                    bids=_levels(item.get("b"), f"{path}.b"),
                    asks=_levels(item.get("a"), f"{path}.a"),
                    first_sequence=(
                        sequence if action == "snapshot" else previous_sequence
                    ),
                    sequence=sequence,
                    previous_sequence=(
                        None if action == "snapshot" else previous_sequence
                    ),
                    is_snapshot=action == "snapshot",
                    event_time=_timestamp(item.get("ts"), f"{path}.ts"),
                    received_time=received_time,
                )
            )
            continue
        events.append(
            BestBidAsk(
                instrument=instrument,
                bid=OrderBookLevel(
                    _decimal(item, "bid1Price", path),
                    _decimal(item, "bid1Size", path),
                ),
                ask=OrderBookLevel(
                    _decimal(item, "ask1Price", path),
                    _decimal(item, "ask1Size", path),
                ),
                sequence=None,
                event_time=event_time,
                received_time=received_time,
            )
        )
        if instrument.market_type is MarketType.USDT_PERPETUAL:
            events.append(
                FundingRateSnapshot(
                    instrument=instrument,
                    rate=_decimal(item, "fundingRate", path, signed=True),
                    next_funding_time=_timestamp(
                        item.get("nextFundingTime"),
                        f"{path}.nextFundingTime",
                    ),
                    event_time=event_time,
                    received_time=received_time,
                )
            )
    return tuple(events)
