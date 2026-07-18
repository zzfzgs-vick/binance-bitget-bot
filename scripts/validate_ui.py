"""Static and optional runtime validation for mainwindow.ui."""

from __future__ import annotations

from pathlib import Path
import sys
from xml.etree import ElementTree as ET

PROJECT_ROOT = Path(__file__).resolve().parents[1]
UI_PATH = PROJECT_ROOT / "app" / "ui" / "forms" / "mainwindow.ui"
QSS_PATH = PROJECT_ROOT / "app" / "ui" / "styles" / "dark.qss"

REQUIRED_OBJECT_NAMES = {
    "MainWindow",
    "mainVerticalSplitter",
    "tradingHorizontalSplitter",
    "positionHorizontalSplitter",
    "positionTabWidget",
    "symbolSearchLineEdit",
    "scanAmountComboBox",
    "minimumPnlDoubleSpinBox",
    "minimumFundingDoubleSpinBox",
    "profitableOnlyCheckBox",
    "executableOnlyCheckBox",
    "favoritesOnlyCheckBox",
    "opportunityTableView",
    "spotInvestmentDoubleSpinBox",
    "spotMaxSlippageDoubleSpinBox",
    "spotOrderTypeComboBox",
    "spotLimitPriceDoubleSpinBox",
    "marginModeComboBox",
    "leverageSpinBox",
    "perpetualMaxSlippageDoubleSpinBox",
    "perpetualOrderTypeComboBox",
    "perpetualLimitPriceDoubleSpinBox",
    "marginBufferDoubleSpinBox",
    "refreshQuoteButton",
    "paperOrderButton",
    "confirmDualLegButton",
    "positionTableView",
    "executingOrdersTableView",
    "orderHistoryTableView",
    "fundingHistoryTableView",
    "paperModeButton",
    "refreshProductsButton",
    "refreshAccountsButton",
    "settingsButton",
    "systemLogButton",
}


def static_validate() -> list[str]:
    failures: list[str] = []
    if not UI_PATH.is_file():
        return [f"UI file missing: {UI_PATH}"]
    if not QSS_PATH.is_file() or not QSS_PATH.read_text(encoding="utf-8").strip():
        failures.append(f"QSS file missing or empty: {QSS_PATH}")

    root = ET.parse(UI_PATH).getroot()
    if root.find("./widget[@class='QMainWindow'][@name='MainWindow']") is None:
        failures.append("Root widget must be QMainWindow named MainWindow")

    names = {element.get("name") for element in root.iter() if element.get("name")}
    missing = sorted(REQUIRED_OBJECT_NAMES - names)
    if missing:
        failures.append("Missing objectName values: " + ", ".join(missing))

    if root.find("./widget/property[@name='styleSheet']") is not None:
        failures.append("Root stylesheet must remain external in dark.qss")

    return failures


def optional_runtime_validate() -> str:
    try:
        from PySide6.QtWidgets import QApplication, QMainWindow
    except ModuleNotFoundError:
        return "SKIPPED: PySide6 is not installed"

    sys.path.insert(0, str(PROJECT_ROOT))
    from app.ui.loader.ui_loader import load_typed_ui
    from app.ui.loader.widget_registry import MainWindowWidgets

    app = QApplication.instance() or QApplication([])
    window = load_typed_ui(UI_PATH, QMainWindow)
    MainWindowWidgets.bind(window)
    window.close()
    app.processEvents()
    return "PASS"


def main() -> int:
    failures = static_validate()
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1

    print("PASS: static UI validation")
    print(f"Runtime Qt validation: {optional_runtime_validate()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
