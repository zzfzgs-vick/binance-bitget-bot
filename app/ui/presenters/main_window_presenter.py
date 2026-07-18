"""Main-window presenter for UI composition only."""

from __future__ import annotations

from PySide6.QtCore import QObject

from app.ui.models.executing_order_table_model import ExecutingOrderTableModel
from app.ui.models.funding_history_table_model import FundingHistoryTableModel
from app.ui.models.opportunity_table_model import OpportunityTableModel
from app.ui.models.order_history_table_model import OrderHistoryTableModel
from app.ui.models.position_table_model import PositionTableModel
from app.application.dto.opportunity_dto import ExecutableOpportunity
from app.domain.accounts.account_snapshot import AccountState
from app.domain.arbitrage.arbitrage_position import ArbitragePosition
from app.application.services.position_service import PositionService
from app.ui.presenters.account_presenter import AccountPresenter
from app.ui.presenters.opportunity_presenter import OpportunityPresenter
from app.ui.presenters.order_entry_presenter import OrderEntryPresenter
from app.ui.presenters.position_presenter import PositionPresenter
from app.workers.execution_worker import ExecutionWorker
from app.ui.views.main_window import MainWindowView


class MainWindowPresenter(QObject):
    """Attach empty models and preserve a clean future application boundary."""

    def __init__(
        self,
        view: MainWindowView,
        *,
        execution_worker: ExecutionWorker | None = None,
    ) -> None:
        super().__init__(view)
        self._view = view
        self._opportunity_model = OpportunityTableModel()
        self._position_model = PositionTableModel()
        self._executing_order_model = ExecutingOrderTableModel()
        self._order_history_model = OrderHistoryTableModel()
        self._funding_history_model = FundingHistoryTableModel()
        self._is_bound = False
        self._is_shutdown = False
        self._execution_worker = execution_worker
        self._positions = PositionService()
        self._opportunity_presenter = OpportunityPresenter(
            view, self._opportunity_model
        )
        self._account_presenter = AccountPresenter(view)
        self._position_presenter = PositionPresenter(
            view,
            self._position_model,
            positions=self._positions,
            worker=execution_worker,
        )
        self._order_entry_presenter = None
        if execution_worker is not None:
            self._order_entry_presenter = OrderEntryPresenter(
                view,
                execution_worker,
                self._positions,
            )
            self._opportunity_presenter.selected.connect(
                self._order_entry_presenter.select
            )
            self._order_entry_presenter.positions_changed.connect(
                self._position_presenter.set_positions
            )

    def bind(self) -> None:
        """Associate the loaded UI tables with their source-side models."""
        if self._is_bound:
            return

        self._view.set_opportunity_model(self._opportunity_model)
        self._view.set_position_model(self._position_model)
        self._view.set_executing_order_model(self._executing_order_model)
        self._view.set_order_history_model(self._order_history_model)
        self._view.set_funding_history_model(self._funding_history_model)

        # Reconnect after setModel(), because QTableView receives a new selection model.
        self._view.widgets.opportunity_table.selectionModel().selectionChanged.connect(
            lambda _selected, _deselected: self._view.opportunity_selection_changed.emit()
        )

        self._view.set_initial_state()
        self._is_bound = True

    def set_opportunities(
        self, plans: tuple[ExecutableOpportunity, ...]
    ) -> None:
        self._opportunity_presenter.set_opportunities(plans)

    def set_account_states(self, states: tuple[AccountState, ...]) -> None:
        self._account_presenter.set_states(states)

    def set_positions(self, positions: tuple[ArbitragePosition, ...]) -> None:
        self._position_presenter.set_positions(positions)

    def mark_position(
        self,
        position_id: str,
        first_price,
        second_price,
    ) -> None:
        self._position_presenter.mark_position(
            position_id,
            first_price=first_price,
            second_price=second_price,
        )

    def shutdown(self) -> None:
        if self._is_shutdown:
            return
        self._is_shutdown = True
        if self._execution_worker is not None:
            self._execution_worker.shutdown()
