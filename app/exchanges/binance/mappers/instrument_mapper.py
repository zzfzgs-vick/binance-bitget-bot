"""Normalize Binance exchange-information payloads."""

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from app.domain.enums import Exchange, MarketType, TradingStatus
from app.domain.exceptions import InstrumentDataError
from app.domain.instruments.instrument import Instrument, TradingRules


_STATUS = {
    "TRADING": TradingStatus.TRADING,
    "PRE_TRADING": TradingStatus.UNAVAILABLE,
    "POST_TRADING": TradingStatus.UNAVAILABLE,
    "AUCTION_MATCH": TradingStatus.UNAVAILABLE,
    "HALT": TradingStatus.UNAVAILABLE,
    "BREAK": TradingStatus.UNAVAILABLE,
    "END_OF_DAY": TradingStatus.UNAVAILABLE,
    "PENDING_TRADING": TradingStatus.UNAVAILABLE,
    "PRE_SETTLE": TradingStatus.UNAVAILABLE,
    "SETTLING": TradingStatus.UNAVAILABLE,
    "CLOSE": TradingStatus.UNAVAILABLE,
}

_DELIVERY_CONTRACT_TYPES = {
    "CURRENT_MONTH",
    "NEXT_MONTH",
    "CURRENT_QUARTER",
    "NEXT_QUARTER",
    "PERPETUAL_DELIVERING",
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


def _decimal(data: Mapping[str, Any], field: str, path: str) -> Decimal:
    raw = _text(data, field, path)
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise InstrumentDataError(f"{path}.{field} must be a decimal string") from None
    if not value.is_finite() or value <= 0:
        raise InstrumentDataError(f"{path}.{field} must be greater than zero")
    return value


def _filters(product: Mapping[str, Any], path: str) -> dict[str, Mapping[str, Any]]:
    indexed = {}
    for index, item in enumerate(_objects(product.get("filters"), f"{path}.filters")):
        item_path = f"{path}.filters[{index}]"
        filter_type = _text(item, "filterType", item_path)
        if filter_type in indexed:
            raise InstrumentDataError(f"{path} has duplicate {filter_type} filters")
        indexed[filter_type] = item
    return indexed


def _required_filter(
    filters: Mapping[str, Mapping[str, Any]], filter_type: str, path: str
) -> Mapping[str, Any]:
    try:
        return filters[filter_type]
    except KeyError:
        raise InstrumentDataError(f"{path} is missing {filter_type} filter") from None


def _minimum_notional(
    filters: Mapping[str, Mapping[str, Any]], path: str
) -> Decimal:
    values = []
    if "MIN_NOTIONAL" in filters:
        item = filters["MIN_NOTIONAL"]
        field = "minNotional" if "minNotional" in item else "notional"
        values.append(_decimal(item, field, path))
    if "NOTIONAL" in filters:
        values.append(_decimal(filters["NOTIONAL"], "minNotional", path))
    if not values:
        raise InstrumentDataError(f"{path} is missing minimum notional filter")
    if any(value != values[0] for value in values[1:]):
        raise InstrumentDataError(f"{path} has conflicting minimum notional filters")
    return values[0]


def _status(raw_status: str, path: str) -> TradingStatus:
    try:
        return _STATUS[raw_status]
    except KeyError:
        raise InstrumentDataError(
            f"{path}.status has unknown value {raw_status!r}"
        ) from None


def parse_spot_products(payload: object) -> tuple[Instrument, ...]:
    root = _object(payload, "payload")
    products = _objects(root.get("symbols"), "payload.symbols")
    normalized = []
    for index, product in enumerate(products):
        path = f"payload.symbols[{index}]"
        filters = _filters(product, path)
        price_filter = _required_filter(filters, "PRICE_FILTER", path)
        lot_size = _required_filter(filters, "LOT_SIZE", path)
        raw_status = _text(product, "status", path)
        quote_asset = _text(product, "quoteAsset", path).upper()
        normalized.append(
            Instrument(
                exchange=Exchange.BINANCE,
                market_type=MarketType.SPOT,
                raw_symbol=_text(product, "symbol", path),
                base_asset=_text(product, "baseAsset", path).upper(),
                quote_asset=quote_asset,
                settlement_asset=quote_asset,
                status=_status(raw_status, path),
                raw_status=raw_status,
                rules=TradingRules(
                    tick_size=_decimal(price_filter, "tickSize", path),
                    quantity_step=_decimal(lot_size, "stepSize", path),
                    minimum_quantity=_decimal(lot_size, "minQty", path),
                    maximum_quantity=_decimal(lot_size, "maxQty", path),
                    minimum_notional=_minimum_notional(filters, path),
                    contract_multiplier=Decimal("1"),
                ),
            )
        )
    return tuple(normalized)


def parse_usdt_perpetual_products(payload: object) -> tuple[Instrument, ...]:
    root = _object(payload, "payload")
    products = _objects(root.get("symbols"), "payload.symbols")
    normalized = []
    for index, product in enumerate(products):
        path = f"payload.symbols[{index}]"
        contract_type = _text(product, "contractType", path)
        if contract_type in _DELIVERY_CONTRACT_TYPES:
            continue
        if contract_type != "PERPETUAL":
            raise InstrumentDataError(
                f"{path}.contractType has unknown value {contract_type!r}"
            )
        quote_asset = _text(product, "quoteAsset", path).upper()
        settlement_asset = _text(product, "marginAsset", path).upper()
        if quote_asset != "USDT" or settlement_asset != "USDT":
            continue
        filters = _filters(product, path)
        price_filter = _required_filter(filters, "PRICE_FILTER", path)
        lot_size = _required_filter(filters, "LOT_SIZE", path)
        raw_status = _text(product, "status", path)
        normalized.append(
            Instrument(
                exchange=Exchange.BINANCE,
                market_type=MarketType.USDT_PERPETUAL,
                raw_symbol=_text(product, "symbol", path),
                base_asset=_text(product, "baseAsset", path).upper(),
                quote_asset=quote_asset,
                settlement_asset=settlement_asset,
                status=_status(raw_status, path),
                raw_status=raw_status,
                rules=TradingRules(
                    tick_size=_decimal(price_filter, "tickSize", path),
                    quantity_step=_decimal(lot_size, "stepSize", path),
                    minimum_quantity=_decimal(lot_size, "minQty", path),
                    maximum_quantity=_decimal(lot_size, "maxQty", path),
                    minimum_notional=_minimum_notional(filters, path),
                    contract_multiplier=Decimal("1"),
                ),
            )
        )
    return tuple(normalized)
