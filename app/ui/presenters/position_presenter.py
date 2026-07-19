"""Present current arbitrage positions in existing table and detail widgets."""

from decimal import Decimal
from datetime import datetime, timedelta, timezone
import logging

from PySide6.QtCore import QObject, Signal, Slot

from app.application.services.position_service import PositionService
from app.domain.arbitrage.arbitrage_position import ArbitragePosition, PositionStatus
from app.ui.models.position_table_model import PositionTableModel
from app.ui.views.main_window import MainWindowView
from app.workers.execution_worker import ExecutionWorker


_LOGGER = logging.getLogger("binance_bitget_bot.ui.positions")


class PositionPresenter(QObject):
    positions_changed = Signal(object)
    def __init__(
        self,
        view: MainWindowView,
        model: PositionTableModel,
        *,
        positions: PositionService | None = None,
        worker: ExecutionWorker | None = None,
    ) -> None:
        super().__init__(view)
        self._view = view
        self._model = model
        self._position_service = positions or PositionService()
        self._worker = worker
        self._close_prices: dict[
            str, tuple[Decimal, Decimal, datetime]
        ] = {}
        self._retryable_close_ids: set[str] = set()
        self._positions: tuple[ArbitragePosition, ...] = ()
        self._is_shutdown = False
        view.widgets.position_table.clicked.connect(self._show_selected)
        if worker is not None:
            view.close_position_requested.connect(self._request_close)
            worker.close_completed.connect(self._close_completed)

    def shutdown(self) -> None:
        if self._is_shutdown:
            return
        self._is_shutdown = True
        connections = [(self._view.widgets.position_table.clicked, self._show_selected)]
        if self._worker is not None:
            connections.extend(
                (
                    (self._view.close_position_requested, self._request_close),
                    (self._worker.close_completed, self._close_completed),
                )
            )
        for signal, slot in connections:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    def set_positions(self, positions: tuple[ArbitragePosition, ...]) -> None:
        if self._is_shutdown:
            return
        if not all(isinstance(position, ArbitragePosition) for position in positions):
            raise TypeError("positions must contain ArbitragePosition values")
        self._positions = positions
        self._position_service.replace_all(positions)
        self._model.replace_rows(tuple(_position_row(position) for position in positions))
        if positions:
            self._show_position(positions[0])
        else:
            self._clear_details()

    def mark_position(
        self,
        position_id: str,
        *,
        first_price: Decimal,
        second_price: Decimal,
    ) -> None:
        position = self._position_service.mark_to_market(
            position_id,
            first_price=first_price,
            second_price=second_price,
        )
        self._close_prices[position_id] = (
            first_price,
            second_price,
            datetime.now(timezone.utc),
        )
        self.set_positions(
            tuple(
                position if item.position_id == position_id else item
                for item in self._positions
            )
        )

    @Slot(str)
    def _request_close(self, position_id: str) -> None:
        if self._worker is None:
            return
        position = self._position_service.get(position_id)
        prices = self._close_prices.get(position_id)
        if prices is None:
            self._view.set_status(
                "平仓前需要最新的两腿市场价格", warning=True
            )
            return
        if datetime.now(timezone.utc) - prices[2] > timedelta(seconds=5):
            self._close_prices.pop(position_id, None)
            self._view.set_status(
                "平仓价格已过期，请等待两腿最新市场价格", warning=True
            )
            return
        if position.status is PositionStatus.CLOSED:
            return
        if position.status is PositionStatus.CLOSE_UNKNOWN:
            try:
                self._worker.resume_close(position_id)
            except RuntimeError as exc:
                self._view.set_status(str(exc), warning=True)
            return
        if position.status is PositionStatus.PARTIALLY_CLOSED:
            try:
                self._worker.resume_close(position_id)
            except RuntimeError as exc:
                self._view.set_status(str(exc), warning=True)
            return
        if position_id in self._retryable_close_ids:
            try:
                self._worker.retry_close(
                    position,
                    first_reference_price=prices[0],
                    second_reference_price=prices[1],
                )
            except RuntimeError as exc:
                self._view.set_status(str(exc), warning=True)
            return
        try:
            self._worker.submit_close(
                position,
                first_reference_price=prices[0],
                second_reference_price=prices[1],
            )
        except RuntimeError as exc:
            self._view.set_status(str(exc), warning=True)

    @Slot(str, object)
    def _close_completed(self, position_id: str, result) -> None:
        if self._is_shutdown:
            return
        position = result.position
        prices = self._close_prices.get(position_id)
        if prices is not None and position.status is not PositionStatus.CLOSED:
            position = position.mark_to_market(
                first_price=prices[0],
                second_price=prices[1],
            )
        self._position_service.restore(position)
        if result.can_retry:
            self._retryable_close_ids.add(position_id)
        else:
            self._retryable_close_ids.discard(position_id)
        self.set_positions(self._position_service.positions)
        self.positions_changed.emit(self._position_service.positions)
        warning = result.requires_attention
        self._view.set_status(
            f"双腿平仓结果 {position_id}：{result.status.value}",
            warning=warning,
        )
        log = _LOGGER.warning if warning else _LOGGER.info
        log(
            "Two-leg close result position_id=%s status=%s",
            position_id,
            result.status.value,
        )

    def _show_selected(self, index) -> None:
        if index.isValid() and 0 <= index.row() < len(self._positions):
            self._show_position(self._positions[index.row()])

    def _show_position(self, position: ArbitragePosition) -> None:
        widgets = self._view.widgets
        widgets.position_id_label.setText(position.position_id)
        widgets.position_spot_leg_label.setText(_leg_text("第一腿", position.first_leg))
        widgets.position_perpetual_leg_label.setText(
            _leg_text("第二腿", position.second_leg)
        )
        widgets.position_leverage_label.setText("杠杆：按账户设置    保证金模式：按账户设置")
        widgets.position_open_basis_label.setText(
            f"开仓价差：{position.second_leg.open_average_price - position.first_leg.open_average_price}"
        )
        widgets.position_funding_paid_label.setText("累计资金费：—")
        widgets.position_net_pnl_label.setText(
            f"组合净盈亏：{position.realized_pnl + position.unrealized_pnl}"
        )

    def _clear_details(self) -> None:
        widgets = self._view.widgets
        widgets.position_id_label.setText("暂无套利仓位")
        widgets.position_spot_leg_label.setText("第一腿：—")
        widgets.position_perpetual_leg_label.setText("第二腿：—")


def _leg_text(name, leg) -> str:
    return (
        f"{name}：{leg.instrument.exchange.value} {leg.instrument.raw_symbol} "
        f"{leg.opening_side.value} {leg.remaining_quantity} @ {leg.open_average_price}"
    )


def _position_row(position: ArbitragePosition) -> tuple[object, ...]:
    first = position.first_leg
    second = position.second_leg
    ratio = (
        second.remaining_quantity / first.remaining_quantity
        if first.remaining_quantity != 0
        else "—"
    )
    return (
        position.position_id,
        f"{first.instrument.base_asset}/{first.instrument.quote_asset}",
        f"{first.instrument.exchange.value}→{second.instrument.exchange.value}",
        str(first.remaining_quantity),
        str(second.remaining_quantity),
        str(ratio),
        str(first.open_average_price),
        str(second.open_average_price),
        "—",
        "—",
        str(position.realized_pnl + position.unrealized_pnl),
        position.status.value,
        "—" if position.status is PositionStatus.CLOSED else "双击平仓",
    )
