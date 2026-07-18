"""Normalize Bitget UTA account snapshots and private stream updates."""

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


def _objects(
    value: object,
    path: str,
    *,
    empty: bool = True,
) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or (not empty and not value):
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
    if isinstance(value, bool):
        raise AccountDataError(f"{path} must be a non-negative integer")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and value.isascii() and value.isdecimal():
        result = int(value)
    else:
        raise AccountDataError(f"{path} must be a non-negative integer")
    if result < 0:
        raise AccountDataError(f"{path} must be a non-negative integer")
    return result


def _timestamp(milliseconds: int, path: str) -> datetime:
    try:
        return datetime.fromtimestamp(
            milliseconds // 1000, tz=timezone.utc
        ) + timedelta(milliseconds=milliseconds % 1000)
    except (OverflowError, OSError, ValueError):
        raise AccountDataError(f"{path} is outside the supported time range") from None


def _asset(value: str, known_assets: set[str] | None) -> str:
    if known_assets is not None and value not in known_assets:
        raise AccountDataError(f"unknown asset {value!r}")
    return value


def _instrument(symbol: str, instruments: Mapping[str, Instrument]) -> Instrument:
    instrument = instruments.get(symbol) or instruments.get(symbol.upper())
    if instrument is None:
        raise AccountDataError(f"unknown symbol {symbol!r}")
    if (
        instrument.exchange is not Exchange.BITGET
        or instrument.market_type is not MarketType.USDT_PERPETUAL
    ):
        raise AccountDataError(f"symbol {symbol!r} is not a Bitget USDT perpetual")
    return instrument


def _margin_mode(raw: str, path: str) -> MarginMode:
    if raw in ("cross", "crossed"):
        return MarginMode.CROSS
    if raw == "isolated":
        return MarginMode.ISOLATED
    raise AccountDataError(f"unknown margin mode {raw!r} at {path}")


def _position(
    item: Mapping[str, Any],
    path: str,
    instruments: Mapping[str, Instrument],
    *,
    quantity_field: str,
    event_time: datetime,
) -> FuturesPosition:
    instrument = _instrument(_text(item, "symbol", path), instruments)
    mode_text = _text(item, "holdMode", path)
    if mode_text == "one_way_mode":
        mode = PositionMode.ONE_WAY
    elif mode_text == "hedge_mode":
        mode = PositionMode.HEDGE
    else:
        raise AccountDataError(f"unknown holding mode {mode_text!r} at {path}")
    side_text = _text(item, "posSide", path)
    if side_text not in ("long", "short"):
        raise AccountDataError(f"unknown position direction {side_text!r} at {path}")
    quantity = _decimal(item, quantity_field, path)
    side = PositionSide.LONG if side_text == "long" else PositionSide.SHORT
    if quantity == 0 and mode is PositionMode.ONE_WAY:
        side = PositionSide.FLAT
    return FuturesPosition(
        instrument=instrument,
        quantity=quantity,
        side=side,
        mode=mode,
        average_open_price=_decimal(item, "avgPrice", path),
        unrealized_pnl=_decimal(item, "unrealisedPnl", path, signed=True),
        margin_mode=_margin_mode(
            _text(item, "marginMode", path), f"{path}.marginMode"
        ),
        updated_time=event_time,
    )


def private_subscriptions() -> tuple[dict[str, str], ...]:
    return (
        {"instType": "UTA", "topic": "account"},
        {"instType": "UTA", "topic": "position"},
    )


def parse_account(
    payload: object,
    received_time: datetime,
    *,
    known_assets: set[str] | None = None,
) -> AccountSnapshot:
    response = _object(payload, "response")
    sequence = _integer(response.get("requestTime"), "response.requestTime")
    data = _object(response.get("data"), "response.data")
    balances = []
    for index, item in enumerate(
        _objects(data.get("assets"), "response.data.assets")
    ):
        path = f"response.data.assets[{index}]"
        balances.append(
            AssetBalance(
                Exchange.BITGET,
                None,
                _asset(_text(item, "coin", path), known_assets),
                _decimal(item, "balance", path),
                _decimal(item, "available", path),
                _decimal(item, "locked", path),
                _decimal(item, "equity", path, signed=True),
            )
        )
    return AccountSnapshot(
        Exchange.BITGET,
        None,
        tuple(balances),
        (),
        _timestamp(sequence, "response.requestTime"),
        received_time,
        sequence,
        replace_positions=False,
    )


def parse_positions(
    payload: object,
    instruments: Mapping[str, Instrument],
    received_time: datetime,
) -> AccountSnapshot:
    response = _object(payload, "response")
    sequence = _integer(response.get("requestTime"), "response.requestTime")
    data = _object(response.get("data"), "response.data")
    event_time = _timestamp(sequence, "response.requestTime")
    positions = tuple(
        _position(
            item,
            f"response.data.list[{index}]",
            instruments,
            quantity_field="total",
            event_time=event_time,
        )
        for index, item in enumerate(_objects(data.get("list"), "response.data.list"))
    )
    return AccountSnapshot(
        Exchange.BITGET,
        None,
        (),
        positions,
        event_time,
        received_time,
        sequence,
        replace_balances=False,
    )


def parse_private_message(
    message: object,
    instruments: Mapping[str, Instrument],
    received_time: datetime,
    *,
    known_assets: set[str] | None = None,
) -> AccountSnapshot | AccountUpdate | None:
    payload = _object(message, "message")
    control = payload.get("event")
    if control in ("login", "subscribe", "unsubscribe"):
        return None
    if control is not None:
        raise AccountDataError(f"Bitget private control event {control!r}")
    argument = _object(payload.get("arg"), "message.arg")
    if _text(argument, "instType", "message.arg") != "UTA":
        raise AccountDataError("message.arg.instType must be UTA")
    topic = _text(argument, "topic", "message.arg")
    if topic not in ("account", "position"):
        raise AccountDataError(f"unknown Bitget private topic {topic!r}")
    action = payload.get("action")
    if action not in ("snapshot", "update"):
        raise AccountDataError("Bitget private action must be snapshot or update")
    sequence = _integer(payload.get("ts"), "message.ts")
    event_time = _timestamp(sequence, "message.ts")
    rows = _objects(payload.get("data"), "message.data")
    if action == "update" and not rows:
        raise AccountDataError("Bitget private update data must not be empty")
    if topic == "account":
        balances = []
        for row_index, row in enumerate(rows):
            for index, item in enumerate(
                _objects(
                    row.get("coin"), f"message.data[{row_index}].coin"
                )
            ):
                path = f"message.data[{row_index}].coin[{index}]"
                asset = _asset(_text(item, "coin", path), known_assets)
                values = {
                    "total": _decimal(item, "balance", path),
                    "available": _decimal(item, "available", path),
                    "frozen": _decimal(item, "locked", path),
                    "margin_balance": _decimal(
                        item, "equity", path, signed=True
                    ),
                }
                balances.append(
                    AssetBalance(Exchange.BITGET, None, asset, **values)
                    if action == "snapshot"
                    else BalanceUpdate(Exchange.BITGET, None, asset, **values)
                )
        if action == "snapshot":
            return AccountSnapshot(
                Exchange.BITGET,
                None,
                tuple(balances),
                (),
                event_time,
                received_time,
                sequence,
                replace_positions=False,
            )
        return AccountUpdate(
            Exchange.BITGET,
            None,
            tuple(balances),
            (),
            event_time,
            received_time,
            sequence,
        )
    positions = tuple(
        _position(
            item,
            f"message.data[{index}]",
            instruments,
            quantity_field="size",
            event_time=event_time,
        )
        for index, item in enumerate(rows)
    )
    if action == "snapshot":
        return AccountSnapshot(
            Exchange.BITGET,
            None,
            (),
            positions,
            event_time,
            received_time,
            sequence,
            replace_balances=False,
        )
    return AccountUpdate(
        Exchange.BITGET,
        None,
        (),
        positions,
        event_time,
        received_time,
        sequence,
    )
