"""Present executable normalized opportunities without business calculation."""

from PySide6.QtCore import QObject, Signal

from app.application.dto.opportunity_dto import ExecutableOpportunity
from app.ui.models.opportunity_table_model import OpportunityTableModel
from app.ui.views.main_window import MainWindowView


class OpportunityPresenter(QObject):
    selected = Signal(object)

    def __init__(
        self,
        view: MainWindowView,
        model: OpportunityTableModel,
    ) -> None:
        super().__init__(view)
        self._view = view
        self._model = model
        self._plans: tuple[ExecutableOpportunity, ...] = ()
        view.opportunity_selection_changed.connect(self._selection_changed)

    def set_opportunities(
        self, plans: tuple[ExecutableOpportunity, ...]
    ) -> None:
        if not all(isinstance(plan, ExecutableOpportunity) for plan in plans):
            raise TypeError("plans must contain ExecutableOpportunity values")
        self._plans = plans
        self._model.replace_rows(tuple(_opportunity_row(plan) for plan in plans))

    def _selection_changed(self) -> None:
        indexes = self._view.widgets.opportunity_table.selectionModel().selectedRows()
        if not indexes:
            return
        row = indexes[0].row()
        if not 0 <= row < len(self._plans):
            return
        plan = self._plans[row]
        opportunity = plan.opportunity
        self._view.widgets.selected_symbol_label.setText(
            f"{opportunity.buy_leg.instrument.base_asset}/"
            f"{opportunity.buy_leg.instrument.quote_asset}"
        )
        self._view.widgets.selected_route_label.setText(opportunity.direction)
        self._view.widgets.expected_pnl_value_label.setText(
            str(opportunity.net_profit)
        )
        self.selected.emit(plan)


def _opportunity_row(plan: ExecutableOpportunity) -> tuple[object, ...]:
    opportunity = plan.opportunity
    return (
        f"{opportunity.buy_leg.instrument.base_asset}/"
        f"{opportunity.buy_leg.instrument.quote_asset}",
        opportunity.direction,
        str(opportunity.buy_leg.average_price),
        str(opportunity.sell_leg.average_price),
        "—",
        str(opportunity.total_fee),
        str(opportunity.slippage_cost),
        str(opportunity.net_profit),
        str(opportunity.roi),
        "可执行",
    )
