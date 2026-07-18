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
    paper_order_requested = Signal()
    open_position_requested = Signal()
    refresh_products_requested = Signal()
    refresh_accounts_requested = Signal()
    settings_requested = Signal()
    system_log_requested = Signal()
    mode_change_requested = Signal()

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
        self.widgets = MainWindowWidgets.bind(self.window)
        self._apply_stylesheet(stylesheet_path or ui_style_path("dark.qss"))
        self._connect_view_signals()

    def _apply_stylesheet(self, path: Path) -> None:
        if not path.is_file():
            raise FileNotFoundError(f"QSS 文件不存在: {path}")
        self.window.setStyleSheet(path.read_text(encoding="utf-8"))

    def _connect_view_signals(self) -> None:
        self.widgets.refresh_quote_button.clicked.connect(self.refresh_quote_requested.emit)
        self.widgets.paper_order_button.clicked.connect(self.paper_order_requested.emit)
        self.widgets.confirm_dual_leg_button.clicked.connect(self.open_position_requested.emit)
        self.widgets.refresh_products_button.clicked.connect(
            self.refresh_products_requested.emit
        )
        self.widgets.refresh_accounts_button.clicked.connect(
            self.refresh_accounts_requested.emit
        )
        self.widgets.settings_button.clicked.connect(self.settings_requested.emit)
        self.widgets.system_log_button.clicked.connect(self.system_log_requested.emit)
        self.widgets.paper_mode_button.clicked.connect(self.mode_change_requested.emit)

    def show(self) -> None:
        self.window.show()

    def close(self) -> None:
        self.window.close()

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
