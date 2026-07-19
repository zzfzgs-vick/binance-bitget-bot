"""Outcome of an explicitly ordered two-leg execution."""

from dataclasses import dataclass
from enum import Enum

from app.domain.orders.order_leg import OrderLegResult


class DualLegStatus(str, Enum):
    PREFLIGHT_FAILED = "preflight_failed"
    COMPLETED = "completed"
    FIRST_FAILED = "first_failed"
    FIRST_INCOMPLETE = "first_incomplete"
    FIRST_DEFERRED = "first_deferred"
    SECOND_FAILED = "second_failed"
    SECOND_INCOMPLETE = "second_incomplete"
    SECOND_DEFERRED = "second_deferred"
    FIRST_UNKNOWN = "first_unknown"
    SECOND_UNKNOWN = "second_unknown"
    QUANTITY_MISMATCH = "quantity_mismatch"


@dataclass(frozen=True, slots=True)
class DualLegExecutionResult:
    status: DualLegStatus
    first: OrderLegResult
    second: OrderLegResult | None
