"""Recorded state of one leg in a two-leg execution."""

from dataclasses import dataclass
from enum import Enum

from app.domain.orders.order import Order, OrderRequest, OrderStatus


class LegRole(str, Enum):
    FIRST = "first"
    SECOND = "second"


class LegExecutionState(str, Enum):
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class OrderLegResult:
    role: LegRole
    request: OrderRequest
    states: tuple[LegExecutionState, ...]
    order: Order | None
    error: str | None = None


def successful_leg(role: LegRole, request: OrderRequest, order: Order) -> OrderLegResult:
    states = [LegExecutionState.SUBMITTED]
    if order.status is not OrderStatus.SUBMITTED:
        states.append(LegExecutionState.CONFIRMED)
    if order.status is OrderStatus.PARTIALLY_FILLED:
        states.append(LegExecutionState.PARTIALLY_FILLED)
    elif order.status is OrderStatus.FILLED:
        states.append(LegExecutionState.FILLED)
    elif order.status in {
        OrderStatus.CANCELED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
    }:
        states.append(LegExecutionState.FAILED)
    return OrderLegResult(role, request, tuple(states), order)


def failed_leg(
    role: LegRole,
    request: OrderRequest,
    error: Exception,
    *,
    submitted: bool = True,
) -> OrderLegResult:
    states = (
        (LegExecutionState.SUBMITTED, LegExecutionState.FAILED)
        if submitted
        else (LegExecutionState.FAILED,)
    )
    return OrderLegResult(
        role,
        request,
        states,
        None,
        str(error),
    )
