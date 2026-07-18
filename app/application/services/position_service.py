"""In-memory application state for reconciled arbitrage positions."""

from decimal import Decimal

from app.domain.arbitrage.arbitrage_position import ArbitragePosition
from app.domain.exceptions import PositionDataError
from app.domain.orders.order_group import DualLegExecutionResult


class PositionService:
    def __init__(self) -> None:
        self._positions: dict[str, ArbitragePosition] = {}

    @property
    def positions(self) -> tuple[ArbitragePosition, ...]:
        return tuple(self._positions.values())

    def get(self, position_id: str) -> ArbitragePosition:
        try:
            return self._positions[position_id]
        except KeyError:
            raise PositionDataError(f"unknown arbitrage position {position_id!r}") from None

    def open_from_execution(
        self,
        position_id: str,
        execution: DualLegExecutionResult,
    ) -> ArbitragePosition:
        existing = self._positions.get(position_id)
        if existing is not None:
            return existing
        orders = (
            execution.first.order,
            execution.second.order if execution.second is not None else None,
        )
        opened_at = max(
            order.updated_time for order in orders if order is not None
        )
        position = ArbitragePosition.from_execution(position_id, execution, opened_at)
        self._positions[position_id] = position
        return position

    def update(self, position: ArbitragePosition) -> None:
        if not isinstance(position, ArbitragePosition):
            raise TypeError("position must be ArbitragePosition")
        if position.position_id not in self._positions:
            raise PositionDataError(
                f"unknown arbitrage position {position.position_id!r}"
            )
        self._positions[position.position_id] = position

    def replace_all(self, positions: tuple[ArbitragePosition, ...]) -> None:
        if len({position.position_id for position in positions}) != len(positions):
            raise PositionDataError("positions contain duplicate position_id values")
        self._positions = {position.position_id: position for position in positions}

    def mark_to_market(
        self,
        position_id: str,
        *,
        first_price: Decimal,
        second_price: Decimal,
    ) -> ArbitragePosition:
        position = self.get(position_id).mark_to_market(
            first_price=first_price,
            second_price=second_price,
        )
        self._positions[position_id] = position
        return position
