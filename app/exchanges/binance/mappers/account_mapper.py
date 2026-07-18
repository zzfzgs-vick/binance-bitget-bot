"""Normalize Binance spot and USD-M account snapshots and stream updates."""

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from app.domain.accounts.account_snapshot import AccountSnapshot, AccountUpdate
from app.domain.accounts.balance import AssetBalance, BalanceUpdate
from app.domain.accounts.futures_position import (
    FuturesPosition,
    MarginMode,
    PositionMode,
    PositionSide,
)
from app.domain.enums import Exchange, MarketType
from app.domain.exceptions import AccountDataError
from app.domain.instruments.instrument import Instrument


def _object(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AccountDataError(f"{path} must be an object")
    return value


def _objects(value: object, path: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise AccountDataError(f"{path} must be an array")
    return [_object(item, f"{path}[{index}]") for index, item in enumerate(value)]


def _text(data: Mapping[str, Any], field: str, path: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise AccountDataError(f"{path}.{field} must be a non-empty string")
    return value.strip()


def _decimal(
    data: Mapping[str, Any], field: str, path: str, *, signed: bool = False
) -> Decimal:
    raw = _text(data, field, path)
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise AccountDataError(f"{path}.{field} must be a decimal string") from None
    if not value.is_finite() or (not signed and value < 0):
        raise AccountDataError(f"{path}.{field} has an invalid decimal value")
    return value


def _integer(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AccountDataError(f"{path} must be a non-negative integer")
    return value


def _timestamp(milliseconds: int, path: str) -> datetime:
    try:
        return datetime.fromtimestamp(
            milliseconds // 1000, tz=timezone.utc
        ) + timedelta(milliseconds=milliseconds % 1000)
    except (OverflowError, OSError, ValueError):
        raise AccountDataError(f"{path} is outside the supported time range") from None


def _received_milliseconds(value: datetime) -> int:
    if value.tzinfo is None:
        raise AccountDataError("received_time must be timezone-aware")
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = value.astimezone(timezone.utc) - epoch
    return delta.days * 86_400_000 + delta.seconds * 1000 + delta.microseconds // 1000


def _asset(value: str, known_assets: set[str] | None) -> str:
    if known_assets is not None and value not in known_assets:
        raise AccountDataError(f"unknown asset {value!r}")
    return value


def _instrument(
    symbol: str,
    instruments: Mapping[str, Instrument],
) -> Instrument:
    instrument = instruments.get(symbol) or instruments.get(symbol.upper())
    if instrument is None:
        raise AccountDataError(f"unknown symbol {symbol!r}")
    if (
        instrument.exchange is not Exchange.BINANCE
        or instrument.market_type is not MarketType.USDT_PERPETUAL
    ):
        raise AccountDataError(f"symbol {symbol!r} is not a Binance USDT perpetual")
    return instrument


def _margin_mode(value: object, path: str) -> MarginMode:
    if value in ("cross", "crossed", False):
        return MarginMode.CROSS
    if value in ("isolated", True):
        return MarginMode.ISOLATED
    raise AccountDataError(f"unknown margin mode {value!r} at {path}")


def _position(
    item: Mapping[str, Any],
    path: str,
    instruments: Mapping[str, Instrument],
    *,
    quantity_field: str,
    price_field: str,
    pnl_field: str,
    margin_field: str,
    side_field: str,
    updated_time: datetime,
) -> FuturesPosition:
    instrument = _instrument(_text(item, "symbol" if quantity_field == "positionAmt" else "s", path), instruments)
    raw_quantity = _decimal(item, quantity_field, path, signed=True)
    raw_side = _text(item, side_field, path).upper()
    if raw_side == "BOTH":
        mode = PositionMode.ONE_WAY
        side = (
            PositionSide.LONG
            if raw_quantity > 0
            else PositionSide.SHORT
            if raw_quantity < 0
            else PositionSide.FLAT
        )
    elif raw_side in ("LONG", "SHORT"):
        mode = PositionMode.HEDGE
        side = PositionSide.LONG if raw_side == "LONG" else PositionSide.SHORT
    else:
        raise AccountDataError(f"unknown position direction {raw_side!r} at {path}")
    return FuturesPosition(
        instrument=instrument,
        quantity=abs(raw_quantity),
        side=side,
        mode=mode,
        average_open_price=_decimal(item, price_field, path),
        unrealized_pnl=_decimal(item, pnl_field, path, signed=True),
        margin_mode=_margin_mode(item.get(margin_field), f"{path}.{margin_field}"),
        updated_time=updated_time,
    )


def parse_spot_account(
    payload: object,
    received_time: datetime,
    *,
    known_assets: set[str] | None = None,
) -> AccountSnapshot:
    data = _object(payload, "response")
    raw_sequence = data.get("updateTime", 0)
    sequence = _integer(raw_sequence, "response.updateTime")
    if sequence == 0:
        sequence = _received_milliseconds(received_time)
    balances = []
    for index, item in enumerate(_objects(data.get("balances"), "response.balances")):
        path = f"response.balances[{index}]"
        asset = _asset(_text(item, "asset", path), known_assets)
        available = _decimal(item, "free", path)
        frozen = _decimal(item, "locked", path)
        balances.append(
            AssetBalance(
                Exchange.BINANCE,
                MarketType.SPOT,
                asset,
                available + frozen,
                available,
                frozen,
                None,
            )
        )
    return AccountSnapshot(
        Exchange.BINANCE,
        MarketType.SPOT,
        tuple(balances),
        (),
        _timestamp(sequence, "response.updateTime"),
        received_time,
        sequence,
    )


def parse_futures_account(
    account_payload: object,
    position_payload: object,
    instruments: Mapping[str, Instrument],
    received_time: datetime,
    *,
    known_assets: set[str] | None = None,
) -> AccountSnapshot:
    account = _object(account_payload, "account_response")
    balances = []
    sequence = 0
    for index, item in enumerate(_objects(account.get("assets"), "account_response.assets")):
        path = f"account_response.assets[{index}]"
        asset = _asset(_text(item, "asset", path), known_assets)
        updated = _integer(item.get("updateTime", 0), f"{path}.updateTime")
        sequence = max(sequence, updated)
        total = _decimal(item, "walletBalance", path)
        balances.append(
            AssetBalance(
                Exchange.BINANCE,
                MarketType.USDT_PERPETUAL,
                asset,
                total,
                _decimal(item, "availableBalance", path),
                Decimal("0"),
                _decimal(item, "marginBalance", path, signed=True),
                _decimal(item, "unrealizedProfit", path, signed=True)
                if "unrealizedProfit" in item
                else Decimal("0"),
            )
        )
    raw_positions = position_payload
    if isinstance(position_payload, Mapping):
        raw_positions = position_payload.get("data")
    positions = []
    for index, item in enumerate(_objects(raw_positions, "position_response")):
        path = f"position_response[{index}]"
        updated = _integer(item.get("updateTime", 0), f"{path}.updateTime")
        sequence = max(sequence, updated)
        positions.append(
            _position(
                item,
                path,
                instruments,
                quantity_field="positionAmt",
                price_field="entryPrice",
                pnl_field=(
                    "unRealizedProfit"
                    if "unRealizedProfit" in item
                    else "unrealizedProfit"
                ),
                margin_field=("marginType" if "marginType" in item else "isolated"),
                side_field="positionSide",
                updated_time=_timestamp(updated, f"{path}.updateTime") if updated else received_time,
            )
        )
    if sequence == 0:
        sequence = _received_milliseconds(received_time)
    return AccountSnapshot(
        Exchange.BINANCE,
        MarketType.USDT_PERPETUAL,
        tuple(balances),
        tuple(positions),
        _timestamp(sequence, "account snapshot time"),
        received_time,
        sequence,
    )


def parse_private_message(
    message: object,
    instruments: Mapping[str, Instrument],
    received_time: datetime,
    *,
    known_assets: set[str] | None = None,
) -> AccountUpdate | None:
    payload = _object(message, "message")
    if isinstance(payload.get("event"), Mapping):
        payload = _object(payload.get("event"), "message.event")
    event_type = payload.get("e")
    if event_type == "outboundAccountPosition":
        sequence = _integer(payload.get("u"), "message.u")
        balances = []
        for index, item in enumerate(_objects(payload.get("B"), "message.B")):
            path = f"message.B[{index}]"
            asset = _asset(_text(item, "a", path), known_assets)
            available = _decimal(item, "f", path)
            frozen = _decimal(item, "l", path)
            balances.append(
                BalanceUpdate(
                    Exchange.BINANCE,
                    MarketType.SPOT,
                    asset,
                    available + frozen,
                    available,
                    frozen,
                )
            )
        event_time = _timestamp(sequence, "message.u")
        return AccountUpdate(
            Exchange.BINANCE,
            MarketType.SPOT,
            tuple(balances),
            (),
            event_time,
            received_time,
            sequence,
        )
    if event_type == "ACCOUNT_UPDATE":
        sequence = _integer(payload.get("T"), "message.T")
        event_time = _timestamp(sequence, "message.T")
        account = _object(payload.get("a"), "message.a")
        balances = []
        for index, item in enumerate(_objects(account.get("B"), "message.a.B")):
            path = f"message.a.B[{index}]"
            balances.append(
                BalanceUpdate(
                    Exchange.BINANCE,
                    MarketType.USDT_PERPETUAL,
                    _asset(_text(item, "a", path), known_assets),
                    total=_decimal(item, "wb", path),
                )
            )
        positions = []
        for index, item in enumerate(_objects(account.get("P"), "message.a.P")):
            path = f"message.a.P[{index}]"
            positions.append(
                _position(
                    item,
                    path,
                    instruments,
                    quantity_field="pa",
                    price_field="ep",
                    pnl_field="up",
                    margin_field="mt",
                    side_field="ps",
                    updated_time=event_time,
                )
            )
        return AccountUpdate(
            Exchange.BINANCE,
            MarketType.USDT_PERPETUAL,
            tuple(balances),
            tuple(positions),
            event_time,
            received_time,
            sequence,
        )
    if event_type in ("executionReport", "ORDER_TRADE_UPDATE", "listenKeyExpired"):
        return None
    raise AccountDataError(f"unknown Binance private account event {event_type!r}")
