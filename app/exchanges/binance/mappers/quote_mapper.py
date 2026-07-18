"""Normalize Binance public market messages."""

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


def _text(data: Mapping[str, Any], field: str, path: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise MarketDataError(f"{path}.{field} must be a non-empty string")
    return value.strip()


def _decimal(data: Mapping[str, Any], field: str, path: str) -> Decimal:
    raw = _text(data, field, path)
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise MarketDataError(f"{path}.{field} must be a decimal string") from None
    if not value.is_finite() or value < 0:
        raise MarketDataError(
            f"{path}.{field} must be a non-negative finite decimal"
        )
    return value


def _signed_decimal(data: Mapping[str, Any], field: str, path: str) -> Decimal:
    raw = _text(data, field, path)
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise MarketDataError(f"{path}.{field} must be a decimal string") from None
    if not value.is_finite():
        raise MarketDataError(f"{path}.{field} must be a finite decimal")
    return value


def _integer(data: Mapping[str, Any], field: str, path: str) -> int:
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MarketDataError(f"{path}.{field} must be a non-negative integer")
    return value


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


def _timestamp(milliseconds: int, path: str) -> datetime:
    try:
        return datetime.fromtimestamp(
            milliseconds // 1000, tz=timezone.utc
        ) + timedelta(milliseconds=milliseconds % 1000)
    except (OverflowError, OSError, ValueError):
        raise MarketDataError(f"{path} is outside the supported time range") from None


def market_subscriptions(instrument: Instrument) -> tuple[str, ...]:
    if instrument.exchange is not Exchange.BINANCE:
        raise MarketDataError("instrument must belong to Binance")
    symbol = instrument.raw_symbol.lower()
    subscriptions = [f"{symbol}@bookTicker", f"{symbol}@depth@100ms"]
    if instrument.market_type is MarketType.USDT_PERPETUAL:
        subscriptions.append(f"{symbol}@markPrice@1s")
    return tuple(subscriptions)


def parse_message(
    message: object,
    instrument: Instrument,
    received_time: datetime,
) -> tuple[BestBidAsk | FundingRateSnapshot | OrderBookUpdate, ...]:
    if instrument.exchange is not Exchange.BINANCE:
        raise MarketDataError("instrument must belong to Binance")
    payload = _object(message, "message")
    if "stream" in payload:
        payload = _object(payload.get("data"), "message.data")
    if "result" in payload and "id" in payload:
        if payload.get("result") is None:
            return ()
        raise MarketDataError("Binance subscription response was not successful")
    if "code" in payload:
        raise MarketDataError("Binance WebSocket returned a control error")
    if "lastUpdateId" in payload:
        sequence = _integer(payload, "lastUpdateId", "message")
        return (
            OrderBookUpdate(
                instrument=instrument,
                bids=_levels(payload.get("bids"), "message.bids"),
                asks=_levels(payload.get("asks"), "message.asks"),
                first_sequence=sequence,
                sequence=sequence,
                previous_sequence=None,
                is_snapshot=True,
                event_time=received_time,
                received_time=received_time,
            ),
        )
    event_type = payload.get("e")
    symbol = _text(payload, "s", "message")
    if symbol.upper() != instrument.raw_symbol.upper():
        raise MarketDataError("message.s does not match instrument.raw_symbol")
    if event_type == "markPriceUpdate":
        if instrument.market_type is not MarketType.USDT_PERPETUAL:
            raise MarketDataError("markPriceUpdate requires a USDT perpetual")
        return (
            FundingRateSnapshot(
                instrument=instrument,
                rate=_signed_decimal(payload, "r", "message"),
                next_funding_time=_timestamp(
                    _integer(payload, "T", "message"), "message.T"
                ),
                event_time=_timestamp(
                    _integer(payload, "E", "message"), "message.E"
                ),
                received_time=received_time,
            ),
        )
    if event_type == "depthUpdate":
        first_sequence = _integer(payload, "U", "message")
        sequence = _integer(payload, "u", "message")
        previous_sequence = (
            _integer(payload, "pu", "message")
            if instrument.market_type is MarketType.USDT_PERPETUAL
            else None
        )
        return (
            OrderBookUpdate(
                instrument=instrument,
                bids=_levels(payload.get("b"), "message.b"),
                asks=_levels(payload.get("a"), "message.a"),
                first_sequence=first_sequence,
                sequence=sequence,
                previous_sequence=previous_sequence,
                is_snapshot=False,
                event_time=_timestamp(
                    _integer(payload, "E", "message"), "message.E"
                ),
                received_time=received_time,
            ),
        )
    if event_type not in (None, "bookTicker", "24hrTicker"):
        raise MarketDataError(f"unknown Binance market event {event_type!r}")
    sequence = (
        None
        if event_type == "24hrTicker"
        else _integer(payload, "u", "message")
    )
    event_time = (
        _timestamp(_integer(payload, "E", "message"), "message.E")
        if "E" in payload
        else received_time
    )
    return (
        BestBidAsk(
            instrument=instrument,
            bid=OrderBookLevel(
                _decimal(payload, "b", "message"),
                _decimal(payload, "B", "message"),
            ),
            ask=OrderBookLevel(
                _decimal(payload, "a", "message"),
                _decimal(payload, "A", "message"),
            ),
            sequence=sequence,
            event_time=event_time,
            received_time=received_time,
        ),
    )
