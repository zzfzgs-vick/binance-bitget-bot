"""Calculate one executable two-leg arbitrage opportunity."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.domain.arbitrage.arbitrage_opportunity import ArbitrageOpportunity
from app.domain.arbitrage.arbitrage_route import ArbitrageLeg, LegSide
from app.domain.arbitrage.profitability import Profitability
from app.domain.exceptions import (
    ArbitrageCalculationError,
    InstrumentMatchError,
    TradingRuleError,
)
from app.domain.instruments.instrument import Instrument, TradingRules
from app.domain.instruments.trading_pair import match_instruments
from app.domain.market.order_book import OrderBookSnapshot
from app.domain.market.order_book_level import OrderBookLevel


@dataclass(frozen=True, slots=True)
class OpportunityRequest:
    base_quantity: Decimal | None
    quote_amount: Decimal | None
    buy_fee_rate: Decimal | None
    sell_fee_rate: Decimal | None
    now: datetime
    max_age: timedelta


@dataclass(frozen=True, slots=True)
class _DepthFill:
    order_quantity: Decimal
    base_quantity: Decimal
    notional: Decimal
    average_price: Decimal
    best_price: Decimal


def calculate_opportunity(
    buy_book: OrderBookSnapshot,
    sell_book: OrderBookSnapshot,
    request: OpportunityRequest,
) -> ArbitrageOpportunity:
    """Return the result for buying one book and selling the other."""
    _validate_request(request)
    _validate_books(buy_book, sell_book, request)
    try:
        match_instruments(buy_book.instrument, sell_book.instrument)
    except InstrumentMatchError as exc:
        raise ArbitrageCalculationError(
            f"incompatible trading rules: {exc}"
        ) from None

    requested_quantity = request.base_quantity
    if requested_quantity is None:
        assert request.quote_amount is not None
        requested_quantity = _quantity_for_quote_amount(
            buy_book.asks,
            buy_book.instrument,
            request.quote_amount,
        )
    try:
        quantity = buy_book.instrument.rules.normalize_common_base_quantity(
            sell_book.instrument.rules,
            requested_quantity,
        )
    except TradingRuleError as exc:
        raise ArbitrageCalculationError(str(exc)) from None
    buy_fill = _fill(
        buy_book.asks, quantity, buy_book.instrument, LegSide.BUY
    )
    sell_fill = _fill(
        sell_book.bids, quantity, sell_book.instrument, LegSide.SELL
    )
    _validate_fill_rules(buy_fill, buy_book.instrument.rules)
    _validate_fill_rules(sell_fill, sell_book.instrument.rules)

    buy_fee_rate = request.buy_fee_rate
    sell_fee_rate = request.sell_fee_rate
    assert buy_fee_rate is not None and sell_fee_rate is not None
    buy_fee = buy_fill.notional * buy_fee_rate
    sell_fee = sell_fill.notional * sell_fee_rate
    buy_slippage = buy_fill.notional - buy_fill.best_price * quantity
    sell_slippage = sell_fill.best_price * quantity - sell_fill.notional
    gross_profit = sell_fill.notional - buy_fill.notional
    total_fee = buy_fee + sell_fee
    net_profit = gross_profit - total_fee
    profitability = Profitability(
        gross_profit=gross_profit,
        total_fee=total_fee,
        slippage_cost=buy_slippage + sell_slippage,
        net_profit=net_profit,
        roi=net_profit / buy_fill.notional,
    )
    return ArbitrageOpportunity(
        buy_leg=_leg(
            buy_book.instrument,
            LegSide.BUY,
            buy_fill,
            buy_fee_rate,
            buy_fee,
            buy_slippage,
        ),
        sell_leg=_leg(
            sell_book.instrument,
            LegSide.SELL,
            sell_fill,
            sell_fee_rate,
            sell_fee,
            sell_slippage,
        ),
        quantity=quantity,
        profitability=profitability,
    )


def _validate_request(request: OpportunityRequest) -> None:
    if (request.base_quantity is None) == (request.quote_amount is None):
        raise ArbitrageCalculationError(
            "provide exactly one of base_quantity or quote_amount"
        )
    for field in ("base_quantity", "quote_amount"):
        value = getattr(request, field)
        if value is not None:
            _positive_decimal(value, field)
    for field in ("buy_fee_rate", "sell_fee_rate"):
        value = getattr(request, field)
        if value is None:
            raise ArbitrageCalculationError(f"{field} is required")
        if not isinstance(value, Decimal):
            raise TypeError(f"{field} must be Decimal")
        if not value.is_finite() or value < 0:
            raise ArbitrageCalculationError(
                f"{field} must be a non-negative finite Decimal"
            )
    if request.max_age <= timedelta(0):
        raise ArbitrageCalculationError("max_age must be greater than zero")


def _validate_books(
    buy_book: OrderBookSnapshot,
    sell_book: OrderBookSnapshot,
    request: OpportunityRequest,
) -> None:
    for name, book in (("buy_book", buy_book), ("sell_book", sell_book)):
        if not book.is_valid or book.requires_snapshot:
            raise ArbitrageCalculationError(f"{name} is invalid")
        if book.received_time is None:
            raise ArbitrageCalculationError(f"{name} has no received_time")
        try:
            age = request.now - book.received_time
        except TypeError:
            raise ArbitrageCalculationError(
                f"{name} timestamp is incompatible with request.now"
            ) from None
        if age > request.max_age:
            raise ArbitrageCalculationError(f"{name} is stale")


def _fill(
    levels: tuple[OrderBookLevel, ...],
    base_quantity: Decimal,
    instrument: Instrument,
    side: LegSide,
) -> _DepthFill:
    if not levels:
        raise ArbitrageCalculationError(f"{side.value} depth is empty")
    ordered = sorted(
        levels,
        key=lambda level: level.price,
        reverse=side is LegSide.SELL,
    )
    remaining = base_quantity
    notional = Decimal(0)
    for level in ordered:
        available = level.quantity * instrument.rules.contract_multiplier
        taken = min(remaining, available)
        notional += taken * level.price
        remaining -= taken
        if remaining == 0:
            break
    if remaining != 0:
        raise ArbitrageCalculationError(
            f"insufficient {side.value} depth for requested quantity"
        )
    return _DepthFill(
        order_quantity=base_quantity / instrument.rules.contract_multiplier,
        base_quantity=base_quantity,
        notional=notional,
        average_price=notional / base_quantity,
        best_price=ordered[0].price,
    )


def _quantity_for_quote_amount(
    levels: tuple[OrderBookLevel, ...],
    instrument: Instrument,
    quote_amount: Decimal,
) -> Decimal:
    if not levels:
        raise ArbitrageCalculationError("buy depth is empty")
    remaining = quote_amount
    quantity = Decimal(0)
    for level in sorted(levels, key=lambda item: item.price):
        available = level.quantity * instrument.rules.contract_multiplier
        level_notional = available * level.price
        if remaining >= level_notional:
            quantity += available
            remaining -= level_notional
        else:
            quantity += remaining / level.price
            remaining = Decimal(0)
            break
    if remaining != 0:
        raise ArbitrageCalculationError(
            "insufficient buy depth for requested quote_amount"
        )
    return quantity


def _validate_fill_rules(fill: _DepthFill, rules: TradingRules) -> None:
    try:
        rules.validate_execution(fill.average_price, fill.order_quantity)
    except TradingRuleError as exc:
        raise ArbitrageCalculationError(str(exc)) from None


def _leg(
    instrument: Instrument,
    side: LegSide,
    fill: _DepthFill,
    fee_rate: Decimal,
    fee: Decimal,
    slippage: Decimal,
) -> ArbitrageLeg:
    return ArbitrageLeg(
        instrument=instrument,
        side=side,
        order_quantity=fill.order_quantity,
        base_quantity=fill.base_quantity,
        average_price=fill.average_price,
        notional=fill.notional,
        fee_rate=fee_rate,
        fee=fee,
        slippage=slippage,
    )


def _positive_decimal(value: object, field: str) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field} must be Decimal")
    if not value.is_finite() or value <= 0:
        raise ArbitrageCalculationError(
            f"{field} must be a positive finite Decimal"
        )
