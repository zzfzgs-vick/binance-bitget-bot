"""Static and optional runtime validation for mainwindow.ui."""

from __future__ import annotations

import hashlib
import json
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

EXPECTED_STRUCTURAL_HASH = "e7e4b8fa796a64da26c942fe1c9d975aadf50d3a3c0ccb8d04b4c84337c7c9f1"
EXPECTED_OBJECT_NAME_HASH = "8d17cd5bf6f70474baa34cf9e9a7b926904dea8a0e1b3446753b81fa1bce0189"
STRUCTURAL_TAGS = {"widget", "layout", "spacer", "action", "addaction"}


def _contains_structure(element: ET.Element) -> bool:
    return element.tag in STRUCTURAL_TAGS or any(
        _contains_structure(child) for child in element
    )


def _structural_contract(element: ET.Element) -> tuple[object, ...]:
    extra = None
    if element.tag == "widget" and element.get("class") == "QSplitter":
        orientation = element.find("./property[@name='orientation']/enum")
        extra = orientation.text if orientation is not None else None

    children: list[tuple[object, ...]] = []
    for child in element:
        if child.tag == "item":
            nested = tuple(
                _structural_contract(item)
                for item in child
                if _contains_structure(item)
            )
            if nested:
                children.append(("item", tuple(sorted(child.attrib.items())), nested))
        elif _contains_structure(child):
            children.append(_structural_contract(child))

    return (
        element.tag,
        tuple(sorted(element.attrib.items())),
        extra,
        tuple(children),
    )


def structural_hash(root: ET.Element) -> str:
    root_widget = root.find("./widget")
    if root_widget is None:
        return ""
    payload = json.dumps(
        _structural_contract(root_widget),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def object_name_hash(root: ET.Element) -> str:
    names = sorted(
        {
            node.get("name")
            for node in root.iter()
            if node.tag in STRUCTURAL_TAGS and node.get("name")
        }
    )
    return hashlib.sha256("\n".join(names).encode()).hexdigest()


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

    if structural_hash(root) != EXPECTED_STRUCTURAL_HASH:
        failures.append("UI widget/layout structure differs from planning baseline")
    if object_name_hash(root) != EXPECTED_OBJECT_NAME_HASH:
        failures.append("UI objectName contract differs from planning baseline")

    widgets = {widget.get("name"): widget for widget in root.iter("widget")}

    def text(name: str) -> str:
        node = widgets[name].find("./property[@name='text']/string")
        return "" if node is None or node.text is None else node.text

    def enabled(name: str) -> bool:
        node = widgets[name].find("./property[@name='enabled']/bool")
        return node is None or node.text == "true"

    def positive(name: str) -> bool:
        node = widgets[name].find("./property[@name='positive']/bool")
        return node is not None and node.text == "true"

    if text("paperModeButton") != "LIVE 正式实盘":
        failures.append("legacy paperModeButton must display fixed LIVE semantics")
    if text("paperOrderButton") != "LIVE 下单（未接入）":
        failures.append("legacy paperOrderButton must display LIVE unavailable semantics")

    for name, widget in widgets.items():
        if name.endswith("ValueLabel") and text(name) != "—":
            failures.append(f"business value isn't empty: {name}")
        if (
            (name.endswith("ValueLabel") or "未连接" in text(name) or text(name).endswith("—"))
            and positive(name)
        ):
            failures.append(f"empty or disconnected value is styled positive: {name}")
        if widget.get("class") in {
            "QCheckBox",
            "QComboBox",
            "QDoubleSpinBox",
            "QLineEdit",
            "QSpinBox",
        } and enabled(name):
            failures.append(f"unimplemented input must be disabled: {name}")
        if widget.get("class") == "QComboBox" and widget.findall("./item"):
            failures.append(f"unimplemented combo contains sample values: {name}")

    for name in (
        "paperModeButton",
        "refreshProductsButton",
        "refreshAccountsButton",
        "settingsButton",
        "systemLogButton",
        "refreshQuoteButton",
        "paperOrderButton",
        "confirmDualLegButton",
    ):
        if enabled(name):
            failures.append(f"unimplemented action must be disabled: {name}")

    minimum_funding = widgets["minimumFundingDoubleSpinBox"].find(
        "./property[@name='minimum']/double"
    )
    if minimum_funding is None or minimum_funding.text != "-100.000000000000000":
        failures.append("minimum funding input range differs from UI contract")
    leverage = widgets["leverageSpinBox"].find("./property[@name='minimum']/number")
    if leverage is None or leverage.text != "1":
        failures.append("leverage input range differs from UI contract")

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
