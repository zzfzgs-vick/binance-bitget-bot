"""Normalize Bitget UTA instrument payloads."""

from collections.abc import Mapping
from decimal import Decimal, DecimalException, InvalidOperation
from typing import Any

from app.domain.enums import Exchange, MarketType, TradingStatus
from app.domain.exceptions import InstrumentDataError
from app.domain.instruments.instrument import Instrument, TradingRules


_STATUS = {
    "online": TradingStatus.TRADING,
    "listed": TradingStatus.UNAVAILABLE,
    "limit_open": TradingStatus.UNAVAILABLE,
    "limit_close": TradingStatus.UNAVAILABLE,
    "offline": TradingStatus.UNAVAILABLE,
    "restrictedAPI": TradingStatus.UNAVAILABLE,
}


def _object(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InstrumentDataError(f"{path} must be an object")
    return value


def _objects(value: object, path: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise InstrumentDataError(f"{path} must be an array")
    return [_object(item, f"{path}[{index}]") for index, item in enumerate(value)]


def _text(data: Mapping[str, Any], field: str, path: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise InstrumentDataError(f"{path}.{field} must be a non-empty string")
    return value.strip()


def _decimal(
    data: Mapping[str, Any], field: str, path: str, *, allow_zero: bool = False
) -> Decimal:
    raw = _text(data, field, path)
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise InstrumentDataError(f"{path}.{field} must be a decimal string") from None
    if not value.is_finite() or value < 0 or (value == 0 and not allow_zero):
        requirement = "zero or greater" if allow_zero else "greater than zero"
        raise InstrumentDataError(f"{path}.{field} must be {requirement}")
    return value


def _precision_step(data: Mapping[str, Any], field: str, path: str) -> Decimal:
    raw = _text(data, field, path)
    if not raw.isascii() or not raw.isdecimal():
        raise InstrumentDataError(f"{path}.{field} must be a non-negative integer string")
    try:
        return Decimal("1").scaleb(-int(raw))
    except (DecimalException, ValueError):
        raise InstrumentDataError(
            f"{path}.{field} is outside the supported decimal precision range"
        ) from None


def _multiplier(
    data: Mapping[str, Any], field: str, precision_field: str, path: str
) -> Decimal:
    value = _decimal(data, field, path)
    precision_step = _precision_step(data, precision_field, path)
    if value % precision_step != 0:
        raise InstrumentDataError(
            f"{path}.{field} conflicts with {path}.{precision_field}"
        )
    return value


def _status(raw_status: str, path: str) -> TradingStatus:
    try:
        return _STATUS[raw_status]
    except KeyError:
        raise InstrumentDataError(
            f"{path}.status has unknown value {raw_status!r}"
        ) from None


def _products(payload: object) -> list[Mapping[str, Any]]:
    root = _object(payload, "payload")
    if root.get("code") != "00000":
        raise InstrumentDataError("payload.code must be '00000'")
    return _objects(root.get("data"), "payload.data")


def parse_spot_products(payload: object) -> tuple[Instrument, ...]:
    normalized = []
    for index, product in enumerate(_products(payload)):
        path = f"payload.data[{index}]"
        category = _text(product, "category", path)
        if category != "SPOT":
            raise InstrumentDataError(
                f"{path}.category must be SPOT, got {category!r}"
            )
        raw_status = _text(product, "status", path)
        quote_asset = _text(product, "quoteCoin", path).upper()
        maximum_quantity = _decimal(
            product, "maxOrderQty", path, allow_zero=True
        )
        normalized.append(
            Instrument(
                exchange=Exchange.BITGET,
                market_type=MarketType.SPOT,
                raw_symbol=_text(product, "symbol", path),
                base_asset=_text(product, "baseCoin", path).upper(),
                quote_asset=quote_asset,
                settlement_asset=quote_asset,
                status=_status(raw_status, path),
                raw_status=raw_status,
                rules=TradingRules(
                    tick_size=_precision_step(product, "pricePrecision", path),
                    quantity_step=_precision_step(
                        product, "quantityPrecision", path
                    ),
                    minimum_quantity=_decimal(product, "minOrderQty", path),
                    maximum_quantity=(
                        None if maximum_quantity == 0 else maximum_quantity
                    ),
                    minimum_notional=_decimal(product, "minOrderAmount", path),
                    contract_multiplier=Decimal("1"),
                ),
            )
        )
    return tuple(normalized)


def parse_usdt_perpetual_products(payload: object) -> tuple[Instrument, ...]:
    normalized = []
    for index, product in enumerate(_products(payload)):
        path = f"payload.data[{index}]"
        category = _text(product, "category", path)
        if category != "USDT-FUTURES":
            raise InstrumentDataError(
                f"{path}.category must be USDT-FUTURES, got {category!r}"
            )
        product_type = _text(product, "type", path)
        if product_type == "delivery":
            continue
        if product_type != "perpetual":
            raise InstrumentDataError(
                f"{path}.type must be perpetual, got {product_type!r}"
            )
        quote_asset = _text(product, "quoteCoin", path).upper()
        if quote_asset != "USDT":
            raise InstrumentDataError(
                f"{path}.quoteCoin must be USDT, got {quote_asset!r}"
            )
        raw_status = _text(product, "status", path)
        maximum_quantity = _decimal(
            product, "maxOrderQty", path, allow_zero=True
        )
        normalized.append(
            Instrument(
                exchange=Exchange.BITGET,
                market_type=MarketType.USDT_PERPETUAL,
                raw_symbol=_text(product, "symbol", path),
                base_asset=_text(product, "baseCoin", path).upper(),
                quote_asset=quote_asset,
                settlement_asset=quote_asset,
                status=_status(raw_status, path),
                raw_status=raw_status,
                rules=TradingRules(
                    tick_size=_multiplier(
                        product, "priceMultiplier", "pricePrecision", path
                    ),
                    quantity_step=_multiplier(
                        product,
                        "quantityMultiplier",
                        "quantityPrecision",
                        path,
                    ),
                    minimum_quantity=_decimal(product, "minOrderQty", path),
                    maximum_quantity=(
                        None if maximum_quantity == 0 else maximum_quantity
                    ),
                    minimum_notional=_decimal(product, "minOrderAmount", path),
                    contract_multiplier=Decimal("1"),
                ),
            )
        )
    return tuple(normalized)
