"""Main-window view wrapper around the runtime-loaded Qt Designer form."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QAbstractItemModel, QObject, Signal
from PySide6.QtWidgets import QMainWindow

from app.infrastructure.config.paths import ui_form_path, ui_style_path
from app.ui.loader.ui_loader import load_typed_ui
from app.ui.loader.widget_registry import MainWindowWidgets


class MainWindowView(QObject):
    """Thin UI boundary: load, bind, expose signals, and display values only."""

    opportunity_selection_changed = Signal()
    refresh_quote_requested = Signal()
    live_order_requested = Signal()
    open_position_requested = Signal()
    refresh_products_requested = Signal()
    refresh_accounts_requested = Signal()
    settings_requested = Signal()
    system_log_requested = Signal()
    live_environment_requested = Signal()

    def __init__(
        self,
        ui_path: Path | None = None,
        stylesheet_path: Path | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.window = load_typed_ui(
            ui_path or ui_form_path("mainwindow.ui"),
            QMainWindow,
        )
        try:
            self.widgets = MainWindowWidgets.bind(self.window)
            self._apply_stylesheet(stylesheet_path or ui_style_path("dark.qss"))
            self._connect_view_signals()
        except Exception:
            self.dispose()
            raise

    def _apply_stylesheet(self, path: Path) -> None:
        if not path.is_file():
            raise FileNotFoundError(f"QSS 文件不存在: {path}")
        self.window.setStyleSheet(path.read_text(encoding="utf-8"))

    def _connect_view_signals(self) -> None:
        self.widgets.refresh_quote_button.clicked.connect(self.refresh_quote_requested.emit)
        self.widgets.live_order_button.clicked.connect(self.live_order_requested.emit)
        self.widgets.confirm_dual_leg_button.clicked.connect(self.open_position_requested.emit)
        self.widgets.refresh_products_button.clicked.connect(
            self.refresh_products_requested.emit
        )
        self.widgets.refresh_accounts_button.clicked.connect(
            self.refresh_accounts_requested.emit
        )
        self.widgets.settings_button.clicked.connect(self.settings_requested.emit)
        self.widgets.system_log_button.clicked.connect(self.system_log_requested.emit)
        self.widgets.live_mode_button.clicked.connect(self.live_environment_requested.emit)

    def show(self) -> None:
        self.window.show()

    def close(self) -> None:
        self.window.close()

    def dispose(self) -> None:
        """Close the top-level window and schedule owned Qt objects for deletion."""
        self.window.close()
        self.window.deleteLater()
        self.deleteLater()

    def set_initial_state(self) -> None:
        """Show the LIVE-only UI shell without implying business data exists."""
        self.widgets.selected_symbol_label.setText("—")
        self.widgets.selected_route_label.setText("尚未选择套利机会")
        self.widgets.expected_pnl_value_label.setText("—")
        self.widgets.system_ready_status_label.setText("●  UI 已加载")
        self.widgets.last_updated_status_label.setText("◷  最后更新时间 —")
        self.widgets.warning_status_label.setText("⚠  告警 —")

        for button in (
            self.widgets.live_mode_button,
            self.widgets.refresh_products_button,
            self.widgets.refresh_accounts_button,
            self.widgets.settings_button,
            self.widgets.system_log_button,
            self.widgets.refresh_quote_button,
            self.widgets.live_order_button,
            self.widgets.confirm_dual_leg_button,
        ):
            button.setEnabled(False)

        for business_input in (
            self.widgets.symbol_search,
            self.widgets.scan_amount,
            self.widgets.minimum_pnl,
            self.widgets.minimum_funding,
            self.widgets.profitable_only,
            self.widgets.executable_only,
            self.widgets.favorites_only,
            self.widgets.spot_investment,
            self.widgets.spot_max_slippage,
            self.widgets.spot_order_type,
            self.widgets.spot_limit_price,
            self.widgets.margin_mode,
            self.widgets.leverage,
            self.widgets.perpetual_max_slippage,
            self.widgets.perpetual_order_type,
            self.widgets.perpetual_limit_price,
            self.widgets.margin_buffer,
        ):
            business_input.setEnabled(False)
            business_input.setToolTip("后续阶段接入真实业务后可用")

    def set_opportunity_model(self, model: QAbstractItemModel) -> None:
        self.widgets.opportunity_table.setModel(model)

    def set_position_model(self, model: QAbstractItemModel) -> None:
        self.widgets.position_table.setModel(model)

    def set_executing_order_model(self, model: QAbstractItemModel) -> None:
        self.widgets.executing_orders_table.setModel(model)

    def set_order_history_model(self, model: QAbstractItemModel) -> None:
        self.widgets.order_history_table.setModel(model)

    def set_funding_history_model(self, model: QAbstractItemModel) -> None:
        self.widgets.funding_history_table.setModel(model)
