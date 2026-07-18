"""Sequence-aware normalized order book."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from app.domain.exceptions import MarketDataError
from app.domain.instruments.instrument import Instrument
from app.domain.market.order_book_level import OrderBookLevel


class UpdateResult(str, Enum):
    SNAPSHOT_APPLIED = "snapshot_applied"
    APPLIED = "applied"
    DUPLICATE = "duplicate"
    OUT_OF_ORDER = "out_of_order"
    GAP_DETECTED = "gap_detected"
    RESYNC_REQUIRED = "resync_required"


@dataclass(frozen=True, slots=True)
class OrderBookUpdate:
    instrument: Instrument
    bids: tuple[OrderBookLevel, ...]
    asks: tuple[OrderBookLevel, ...]
    first_sequence: int
    sequence: int
    previous_sequence: int | None
    is_snapshot: bool
    event_time: datetime
    received_time: datetime

    def __post_init__(self) -> None:
        for field in ("first_sequence", "sequence"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise MarketDataError(f"{field} must be a non-negative integer")
        if self.first_sequence > self.sequence:
            raise MarketDataError("first_sequence cannot exceed sequence")
        if self.previous_sequence is not None and (
            isinstance(self.previous_sequence, bool)
            or not isinstance(self.previous_sequence, int)
            or self.previous_sequence < 0
        ):
            raise MarketDataError(
                "previous_sequence must be a non-negative integer or None"
            )


@dataclass(frozen=True, slots=True)
class OrderBookSnapshot:
    instrument: Instrument
    bids: tuple[OrderBookLevel, ...]
    asks: tuple[OrderBookLevel, ...]
    sequence: int | None
    is_valid: bool
    requires_snapshot: bool
    event_time: datetime | None
    received_time: datetime | None


class OrderBook:
    def __init__(
        self,
        instrument: Instrument,
        *,
        depth_limit: int | None = None,
    ) -> None:
        if depth_limit is not None and (
            isinstance(depth_limit, bool)
            or not isinstance(depth_limit, int)
            or depth_limit <= 0
        ):
            raise ValueError("depth_limit must be a positive integer or None")
        self._instrument = instrument
        self._depth_limit = depth_limit
        self._bids: dict[Decimal, Decimal] = {}
        self._asks: dict[Decimal, Decimal] = {}
        self._sequence: int | None = None
        self._is_valid = False
        self._requires_snapshot = True
        self._after_snapshot = False
        self._event_time: datetime | None = None
        self._received_time: datetime | None = None

    def apply(self, update: OrderBookUpdate) -> UpdateResult:
        if update.instrument != self._instrument:
            raise MarketDataError("order-book update instrument does not match")
        if update.is_snapshot:
            self._bids = self._levels(update.bids)
            self._asks = self._levels(update.asks)
            self._sequence = update.sequence
            self._is_valid = True
            self._requires_snapshot = False
            self._after_snapshot = True
            self._set_times(update)
            return UpdateResult.SNAPSHOT_APPLIED
        if not self._is_valid or self._sequence is None:
            return UpdateResult.RESYNC_REQUIRED
        if update.previous_sequence == 0 and not (
            self._after_snapshot
            and update.first_sequence <= self._sequence <= update.sequence
        ):
            self._invalidate()
            return UpdateResult.GAP_DETECTED
        if update.sequence == self._sequence:
            return UpdateResult.DUPLICATE
        if update.sequence < self._sequence:
            return UpdateResult.OUT_OF_ORDER
        if not self._is_continuous(update):
            self._invalidate()
            return UpdateResult.GAP_DETECTED
        self._update_levels(self._bids, update.bids)
        self._update_levels(self._asks, update.asks)
        self._sequence = update.sequence
        self._after_snapshot = False
        self._set_times(update)
        return UpdateResult.APPLIED

    def snapshot(self) -> OrderBookSnapshot:
        return OrderBookSnapshot(
            instrument=self._instrument,
            bids=tuple(
                OrderBookLevel(price, quantity)
                for price, quantity in sorted(
                    self._bids.items(), reverse=True
                )[: self._depth_limit]
            ),
            asks=tuple(
                OrderBookLevel(price, quantity)
                for price, quantity in sorted(self._asks.items())[
                    : self._depth_limit
                ]
            ),
            sequence=self._sequence,
            is_valid=self._is_valid,
            requires_snapshot=self._requires_snapshot,
            event_time=self._event_time,
            received_time=self._received_time,
        )

    def _is_continuous(self, update: OrderBookUpdate) -> bool:
        assert self._sequence is not None
        if self._after_snapshot:
            target = (
                self._sequence + 1
                if update.previous_sequence is None
                else self._sequence
            )
            return update.first_sequence <= target <= update.sequence
        if update.previous_sequence is not None:
            return update.previous_sequence == self._sequence
        return update.first_sequence <= self._sequence + 1 <= update.sequence

    def _levels(
        self, levels: tuple[OrderBookLevel, ...]
    ) -> dict[Decimal, Decimal]:
        return {
            level.price: level.quantity
            for level in levels
            if level.quantity != 0
        }

    def _update_levels(
        self,
        side: dict[Decimal, Decimal],
        levels: tuple[OrderBookLevel, ...],
    ) -> None:
        for level in levels:
            if level.quantity == 0:
                side.pop(level.price, None)
            else:
                side[level.price] = level.quantity

    def _set_times(self, update: OrderBookUpdate) -> None:
        self._event_time = update.event_time
        self._received_time = update.received_time

    def _invalidate(self) -> None:
        self._is_valid = False
        self._requires_snapshot = True
