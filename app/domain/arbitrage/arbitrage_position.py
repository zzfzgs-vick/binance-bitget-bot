"""Arbitrage positions created from reconciled, actual two-leg fills."""

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import Enum

from app.domain.exceptions import PositionDataError
from app.domain.instruments.instrument import Instrument
from app.domain.orders.order import FuturesPositionSide, Order, OrderSide, OrderStatus
from app.domain.orders.order_group import DualLegExecutionResult, DualLegStatus


class PositionStatus(str, Enum):
    OPEN = "open"
    CLOSING = "closing"
    PARTIALLY_CLOSED = "partially_closed"
    CLOSED = "closed"
    CLOSE_FAILED = "close_failed"
    CLOSE_UNKNOWN = "close_unknown"


def _decimal(value: object, field: str, *, non_negative: bool = False) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field} must be Decimal")
    if not value.is_finite() or (non_negative and value < 0):
        raise PositionDataError(f"{field} has an invalid Decimal value")


@dataclass(frozen=True, slots=True)
class ArbitragePositionLeg:
    instrument: Instrument
    opening_side: OrderSide
    opening_order_id: str
    open_quantity: Decimal
    remaining_quantity: Decimal
    open_average_price: Decimal
    open_fee: Decimal
    fee_asset: str | None
    position_side: FuturesPositionSide | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, Instrument):
            raise TypeError("instrument must be Instrument")
        if not isinstance(self.opening_side, OrderSide):
            raise TypeError("opening_side must be OrderSide")
        if self.position_side is not None and not isinstance(
            self.position_side, FuturesPositionSide
        ):
            raise TypeError("position_side must be FuturesPositionSide")
        if not isinstance(self.opening_order_id, str) or not self.opening_order_id.strip():
            raise PositionDataError("opening_order_id must be a non-empty string")
        for field in ("open_quantity", "remaining_quantity", "open_average_price"):
            _decimal(getattr(self, field), field, non_negative=True)
        _decimal(self.open_fee, "open_fee")
        if self.open_quantity <= 0 or self.open_average_price <= 0:
            raise PositionDataError("open quantity and average price must be positive")
        if self.remaining_quantity > self.open_quantity:
            raise PositionDataError("remaining quantity exceeds open quantity")


@dataclass(frozen=True, slots=True)
class ArbitragePosition:
    position_id: str
    first_leg: ArbitragePositionLeg
    second_leg: ArbitragePositionLeg
    opened_at: datetime
    status: PositionStatus
    realized_pnl: Decimal
    unrealized_pnl: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.position_id, str) or not self.position_id.strip():
            raise PositionDataError("position_id must be a non-empty string")
        if not isinstance(self.first_leg, ArbitragePositionLeg) or not isinstance(
            self.second_leg, ArbitragePositionLeg
        ):
            raise TypeError("position legs must be ArbitragePositionLeg")
        if self.first_leg.instrument.exchange is self.second_leg.instrument.exchange:
            raise PositionDataError("position legs must use different exchanges")
        if self.first_leg.opening_side is self.second_leg.opening_side:
            raise PositionDataError("position legs must use opposite sides")
        for field in ("base_asset", "quote_asset", "settlement_asset"):
            if getattr(self.first_leg.instrument, field) != getattr(
                self.second_leg.instrument, field
            ):
                raise PositionDataError("position legs use incompatible assets")
        if not isinstance(self.opened_at, datetime) or self.opened_at.tzinfo is None:
            raise PositionDataError("opened_at must be timezone-aware")
        if not isinstance(self.status, PositionStatus):
            raise TypeError("status must be PositionStatus")
        _decimal(self.realized_pnl, "realized_pnl")
        _decimal(self.unrealized_pnl, "unrealized_pnl")

    @classmethod
    def from_execution(
        cls,
        position_id: str,
        execution: DualLegExecutionResult,
        opened_at: datetime,
    ) -> "ArbitragePosition":
        if execution.status is not DualLegStatus.COMPLETED:
            raise PositionDataError("position requires a completed two-leg execution")
        if execution.second is None:
            raise PositionDataError("completed execution requires both legs")
        first = _filled_order(execution.first.order, "first")
        second = _filled_order(execution.second.order, "second")
        if first.filled_base_quantity != second.filled_base_quantity:
            raise PositionDataError("two legs have an actual filled quantity mismatch")
        first_leg = _position_leg(first, execution.first.request.position_side)
        second_leg = _position_leg(second, execution.second.request.position_side)
        opening_fees = _quote_fee(first_leg) + _quote_fee(second_leg)
        return cls(
            position_id=position_id,
            first_leg=first_leg,
            second_leg=second_leg,
            opened_at=opened_at,
            status=PositionStatus.OPEN,
            realized_pnl=-opening_fees,
            unrealized_pnl=Decimal(0),
        )

    def with_close_orders(
        self,
        first_order: Order | None,
        second_order: Order | None,
        status: PositionStatus,
    ) -> "ArbitragePosition":
        """Apply cumulative reconciled close fills deterministically."""
        first_leg, first_pnl, first_fee = _closed_leg(self.first_leg, first_order)
        second_leg, second_pnl, second_fee = _closed_leg(
            self.second_leg, second_order
        )
        if status is PositionStatus.CLOSED and (
            first_leg.remaining_quantity != 0
            or second_leg.remaining_quantity != 0
        ):
            raise PositionDataError("closed position still has remaining quantity")
        return replace(
            self,
            first_leg=first_leg,
            second_leg=second_leg,
            status=status,
            realized_pnl=(
                self.realized_pnl
                + first_pnl
                + second_pnl
                - first_fee
                - second_fee
            ),
            unrealized_pnl=(Decimal(0) if status is PositionStatus.CLOSED else self.unrealized_pnl),
        )

    def mark_to_market(
        self,
        *,
        first_price: Decimal,
        second_price: Decimal,
    ) -> "ArbitragePosition":
        for value, field in (
            (first_price, "first_price"),
            (second_price, "second_price"),
        ):
            _decimal(value, field, non_negative=True)
            if value <= 0:
                raise PositionDataError(f"{field} must be positive")
        unrealized = _price_pnl(self.first_leg, first_price) + _price_pnl(
            self.second_leg, second_price
        )
        return replace(self, unrealized_pnl=unrealized)


def _filled_order(order: Order | None, role: str) -> Order:
    if order is None or order.status is not OrderStatus.FILLED:
        raise PositionDataError(f"{role} leg has no completed actual fill")
    return order


def _position_leg(
    order: Order, position_side: FuturesPositionSide | None
) -> ArbitragePositionLeg:
    quantity = order.filled_base_quantity
    return ArbitragePositionLeg(
        instrument=order.instrument,
        opening_side=order.side,
        opening_order_id=order.exchange_order_id,
        open_quantity=quantity,
        remaining_quantity=quantity,
        open_average_price=order.average_price,
        open_fee=order.cumulative_fee,
        fee_asset=order.fee_asset,
        position_side=position_side,
    )


def _quote_fee(leg: ArbitragePositionLeg) -> Decimal:
    if leg.open_fee == 0:
        return Decimal(0)
    if leg.fee_asset not in {
        leg.instrument.quote_asset,
        leg.instrument.settlement_asset,
    }:
        raise PositionDataError(
            "fee asset requires conversion before profit can be calculated"
        )
    return leg.open_fee


def _closed_leg(
    leg: ArbitragePositionLeg,
    order: Order | None,
) -> tuple[ArbitragePositionLeg, Decimal, Decimal]:
    if order is None:
        return leg, Decimal(0), Decimal(0)
    if order.instrument != leg.instrument or order.side is leg.opening_side:
        raise PositionDataError("close order does not reverse the position leg")
    closed_quantity = order.filled_base_quantity
    if closed_quantity > leg.remaining_quantity:
        raise PositionDataError("close fill exceeds the remaining position quantity")
    remaining = leg.remaining_quantity - closed_quantity
    if leg.opening_side is OrderSide.BUY:
        pnl = (order.average_price - leg.open_average_price) * closed_quantity
    else:
        pnl = (leg.open_average_price - order.average_price) * closed_quantity
    fee = Decimal(0)
    if order.cumulative_fee != 0:
        if order.fee_asset not in {
            leg.instrument.quote_asset,
            leg.instrument.settlement_asset,
        }:
            raise PositionDataError(
                "close fee asset requires conversion before profit can be calculated"
            )
        fee = order.cumulative_fee
    return replace(leg, remaining_quantity=remaining), pnl, fee


def _price_pnl(leg: ArbitragePositionLeg, price: Decimal) -> Decimal:
    if leg.opening_side is OrderSide.BUY:
        return (price - leg.open_average_price) * leg.remaining_quantity
    return (leg.open_average_price - price) * leg.remaining_quantity
