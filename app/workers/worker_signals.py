"""Qt Signal bridge for normalized LIVE events emitted by background sources."""

from decimal import Decimal

from PySide6.QtCore import QObject, Signal

from app.application.dto.opportunity_dto import ExecutableOpportunity
from app.domain.accounts.account_snapshot import AccountState
from app.domain.orders.fill import OrderFill
from app.domain.orders.order import Order


class LiveEventBridge(QObject):
    """Carry normalized events to GUI-thread receivers without owning widgets."""

    opportunities_updated = Signal(object)
    account_states_updated = Signal(object)
    position_prices_updated = Signal(str, object, object)
    private_order_event = Signal(object)
    status_updated = Signal(str)

    def disconnect_all(self) -> None:
        for signal in (
            self.opportunities_updated,
            self.account_states_updated,
            self.position_prices_updated,
            self.private_order_event,
            self.status_updated,
        ):
            try:
                signal.disconnect()
            except (RuntimeError, TypeError):
                pass

    def publish_opportunities(
        self,
        plans: tuple[ExecutableOpportunity, ...],
    ) -> None:
        self.opportunities_updated.emit(plans)

    def publish_account_states(self, states: tuple[AccountState, ...]) -> None:
        self.account_states_updated.emit(states)

    def publish_position_prices(
        self,
        position_id: str,
        first_price: Decimal,
        second_price: Decimal,
    ) -> None:
        self.position_prices_updated.emit(position_id, first_price, second_price)

    def publish_private_order_event(self, event: Order | OrderFill) -> None:
        self.private_order_event.emit(event)

    def publish_status(self, message: str) -> None:
        self.status_updated.emit(message)
