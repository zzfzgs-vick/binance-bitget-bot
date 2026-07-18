"""Typed registry for all main-window widgets used by Python code."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar, cast

from PySide6.QtCore import QObject
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLabel,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableView,
    QTabWidget,
    QLineEdit,
    QWidget,
)

TObject = TypeVar("TObject", bound=QObject)


class WidgetBindingError(RuntimeError):
    """Raised when the UI/source object-name contract is broken."""


def required_child(root: QObject, widget_type: type[TObject], object_name: str) -> TObject:
    """Find one required child and validate its runtime type."""
    child = root.findChild(widget_type, object_name)
    if child is None:
        raise WidgetBindingError(
            f"mainwindow.ui 缺少控件或类型不匹配: {object_name} ({widget_type.__name__})"
        )
    return cast(TObject, child)


@dataclass(frozen=True, slots=True)
class MainWindowWidgets:
    """All widgets directly owned by the main-window integration layer."""

    # Layout and navigation
    main_vertical_splitter: QSplitter
    trading_horizontal_splitter: QSplitter
    position_horizontal_splitter: QSplitter
    position_tabs: QTabWidget

    # Opportunity scan controls
    symbol_search: QLineEdit
    scan_amount: QComboBox
    minimum_pnl: QDoubleSpinBox
    minimum_funding: QDoubleSpinBox
    profitable_only: QCheckBox
    executable_only: QCheckBox
    favorites_only: QCheckBox
    opportunity_table: QTableView

    # Order entry controls
    spot_investment: QDoubleSpinBox
    spot_max_slippage: QDoubleSpinBox
    spot_order_type: QComboBox
    spot_limit_price: QDoubleSpinBox
    margin_mode: QComboBox
    leverage: QSpinBox
    perpetual_max_slippage: QDoubleSpinBox
    perpetual_order_type: QComboBox
    perpetual_limit_price: QDoubleSpinBox
    margin_buffer: QDoubleSpinBox
    refresh_quote_button: QPushButton
    paper_order_button: QPushButton
    confirm_dual_leg_button: QPushButton

    # Tables
    position_table: QTableView
    executing_orders_table: QTableView
    order_history_table: QTableView
    funding_history_table: QTableView

    # Top-level controls
    paper_mode_button: QPushButton
    refresh_products_button: QPushButton
    refresh_accounts_button: QPushButton
    settings_button: QPushButton
    system_log_button: QPushButton

    # Status and selection labels used by the presenter
    selected_symbol_label: QLabel
    selected_route_label: QLabel
    expected_pnl_value_label: QLabel
    system_ready_status_label: QLabel
    last_updated_status_label: QLabel
    warning_status_label: QLabel

    @classmethod
    def bind(cls, window: QMainWindow) -> "MainWindowWidgets":
        """Bind all required widgets by their stable Qt Designer object names."""
        get = lambda typ, name: required_child(window, typ, name)
        return cls(
            main_vertical_splitter=get(QSplitter, "mainVerticalSplitter"),
            trading_horizontal_splitter=get(QSplitter, "tradingHorizontalSplitter"),
            position_horizontal_splitter=get(QSplitter, "positionHorizontalSplitter"),
            position_tabs=get(QTabWidget, "positionTabWidget"),
            symbol_search=get(QLineEdit, "symbolSearchLineEdit"),
            scan_amount=get(QComboBox, "scanAmountComboBox"),
            minimum_pnl=get(QDoubleSpinBox, "minimumPnlDoubleSpinBox"),
            minimum_funding=get(QDoubleSpinBox, "minimumFundingDoubleSpinBox"),
            profitable_only=get(QCheckBox, "profitableOnlyCheckBox"),
            executable_only=get(QCheckBox, "executableOnlyCheckBox"),
            favorites_only=get(QCheckBox, "favoritesOnlyCheckBox"),
            opportunity_table=get(QTableView, "opportunityTableView"),
            spot_investment=get(QDoubleSpinBox, "spotInvestmentDoubleSpinBox"),
            spot_max_slippage=get(QDoubleSpinBox, "spotMaxSlippageDoubleSpinBox"),
            spot_order_type=get(QComboBox, "spotOrderTypeComboBox"),
            spot_limit_price=get(QDoubleSpinBox, "spotLimitPriceDoubleSpinBox"),
            margin_mode=get(QComboBox, "marginModeComboBox"),
            leverage=get(QSpinBox, "leverageSpinBox"),
            perpetual_max_slippage=get(
                QDoubleSpinBox, "perpetualMaxSlippageDoubleSpinBox"
            ),
            perpetual_order_type=get(QComboBox, "perpetualOrderTypeComboBox"),
            perpetual_limit_price=get(
                QDoubleSpinBox, "perpetualLimitPriceDoubleSpinBox"
            ),
            margin_buffer=get(QDoubleSpinBox, "marginBufferDoubleSpinBox"),
            refresh_quote_button=get(QPushButton, "refreshQuoteButton"),
            paper_order_button=get(QPushButton, "paperOrderButton"),
            confirm_dual_leg_button=get(QPushButton, "confirmDualLegButton"),
            position_table=get(QTableView, "positionTableView"),
            executing_orders_table=get(QTableView, "executingOrdersTableView"),
            order_history_table=get(QTableView, "orderHistoryTableView"),
            funding_history_table=get(QTableView, "fundingHistoryTableView"),
            paper_mode_button=get(QPushButton, "paperModeButton"),
            refresh_products_button=get(QPushButton, "refreshProductsButton"),
            refresh_accounts_button=get(QPushButton, "refreshAccountsButton"),
            settings_button=get(QPushButton, "settingsButton"),
            system_log_button=get(QPushButton, "systemLogButton"),
            selected_symbol_label=get(QLabel, "selectedSymbolLabel"),
            selected_route_label=get(QLabel, "selectedRouteLabel"),
            expected_pnl_value_label=get(QLabel, "expectedPnlValueLabel"),
            system_ready_status_label=get(QLabel, "systemReadyStatusLabel"),
            last_updated_status_label=get(QLabel, "lastUpdatedStatusLabel"),
            warning_status_label=get(QLabel, "warningStatusLabel"),
        )
