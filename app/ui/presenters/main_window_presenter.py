"""Main-window presenter for UI composition only."""

from __future__ import annotations

from PySide6.QtCore import QObject

from app.ui.models.executing_order_table_model import ExecutingOrderTableModel
from app.ui.models.funding_history_table_model import FundingHistoryTableModel
from app.ui.models.opportunity_table_model import OpportunityTableModel
from app.ui.models.order_history_table_model import OrderHistoryTableModel
from app.ui.models.position_table_model import PositionTableModel
from app.ui.views.main_window import MainWindowView


class MainWindowPresenter(QObject):
    """Attach empty models and preserve a clean future application boundary."""

    def __init__(self, view: MainWindowView) -> None:
        super().__init__(view)
        self._view = view
        self._opportunity_model = OpportunityTableModel()
        self._position_model = PositionTableModel()
        self._executing_order_model = ExecutingOrderTableModel()
        self._order_history_model = OrderHistoryTableModel()
        self._funding_history_model = FundingHistoryTableModel()
        self._is_bound = False

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
