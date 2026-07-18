"""Explicit two-step GUI orchestration for LIVE two-leg opening orders."""

import logging

from PySide6.QtCore import QObject, Signal, Slot

from app.application.dto.opportunity_dto import ExecutableOpportunity
from app.application.services.position_service import PositionService
from app.domain.orders.order_group import DualLegStatus
from app.ui.views.main_window import MainWindowView
from app.workers.execution_worker import ExecutionWorker


_LOGGER = logging.getLogger("binance_bitget_bot.ui.order_entry")


class OrderEntryPresenter(QObject):
    positions_changed = Signal(object)

    def __init__(
        self,
        view: MainWindowView,
        worker: ExecutionWorker,
        positions: PositionService,
    ) -> None:
        super().__init__(view)
        self._view = view
        self._worker = worker
        self._positions = positions
        self._selected: ExecutableOpportunity | None = None
        self._armed = False
        self._unknown_position_id: str | None = None
        view.live_order_requested.connect(self._arm)
        view.open_position_requested.connect(self._submit)
        worker.open_completed.connect(self._completed)
        worker.operation_failed.connect(self._failed)
        worker.status_changed.connect(self._view.set_status)

    @Slot(object)
    def select(self, plan: ExecutableOpportunity) -> None:
        self._selected = plan
        self._armed = False
        if self._unknown_position_id is not None:
            self._show_unknown_recovery()
            return
        available = self._worker.can_execute(plan)
        self._view.widgets.live_order_button.setEnabled(available)
        self._view.widgets.live_order_button.setText("LIVE 正式下单")
        self._view.widgets.live_order_button.setToolTip(
            "准备由用户明确确认的正式双腿订单"
        )
        self._view.widgets.confirm_dual_leg_button.setEnabled(False)

    @Slot()
    def _arm(self) -> None:
        if self._unknown_position_id is not None:
            position_id = self._unknown_position_id
            self._view.widgets.live_order_button.setEnabled(False)
            self._worker.resume_open(position_id)
            return
        if self._selected is None:
            return
        self._armed = True
        self._view.widgets.confirm_dual_leg_button.setEnabled(True)
        self._view.set_status("LIVE 双腿订单已准备，请明确确认开仓")

    @Slot()
    def _submit(self) -> None:
        if not self._armed or self._selected is None:
            return
        plan = self._selected
        self._armed = False
        self._view.widgets.live_order_button.setEnabled(False)
        self._view.widgets.confirm_dual_leg_button.setEnabled(False)
        self._worker.submit_open(plan)

    @Slot(str, object)
    def _completed(self, position_id: str, result) -> None:
        if result.status is DualLegStatus.COMPLETED:
            self._unknown_position_id = None
            self._positions.open_from_execution(position_id, result)
            self.positions_changed.emit(self._positions.positions)
            self._view.set_status(f"双腿开仓已成交：{position_id}")
            _LOGGER.info("Two-leg opening completed position_id=%s", position_id)
            if self._selected is not None:
                self.select(self._selected)
        elif result.status in {
            DualLegStatus.FIRST_UNKNOWN,
            DualLegStatus.SECOND_UNKNOWN,
        }:
            self._unknown_position_id = position_id
            self._show_unknown_recovery()
            self._view.set_status(
                f"订单状态未知，请查询原订单：{result.status.value}", warning=True
            )
        else:
            self._unknown_position_id = None
            self._view.set_status(
                f"双腿开仓未完成：{result.status.value}", warning=True
            )

    def _show_unknown_recovery(self) -> None:
        self._view.widgets.live_order_button.setEnabled(True)
        self._view.widgets.live_order_button.setText("查询原订单状态")
        self._view.widgets.live_order_button.setToolTip(
            "只查询原客户端订单号，不会重复提交订单"
        )
        self._view.widgets.confirm_dual_leg_button.setEnabled(False)

    @Slot(str, str)
    def _failed(self, operation_id: str, reason: str) -> None:
        self._view.set_status(
            f"执行失败 {operation_id}：{reason}", warning=True
        )
        _LOGGER.error("LIVE execution failed operation_id=%s reason=%s", operation_id, reason)
