"""Outcome of an explicitly ordered two-leg execution."""

from dataclasses import dataclass
from enum import Enum

from app.domain.orders.order_leg import OrderLegResult


class DualLegStatus(str, Enum):
    PREFLIGHT_FAILED = "preflight_failed"
    COMPLETED = "completed"
    FIRST_FAILED = "first_failed"
    FIRST_INCOMPLETE = "first_incomplete"
    SECOND_FAILED = "second_failed"
    SECOND_INCOMPLETE = "second_incomplete"
    QUANTITY_MISMATCH = "quantity_mismatch"


@dataclass(frozen=True, slots=True)
class DualLegExecutionResult:
    status: DualLegStatus
    first: OrderLegResult
    second: OrderLegResult | None
