from pathlib import Path
import unittest
from xml.etree import ElementTree as ET


class MainWindowStaticTests(unittest.TestCase):
    def test_mainwindow_ui_is_well_formed(self) -> None:
        root = ET.parse(Path("app/ui/forms/mainwindow.ui")).getroot()
        self.assertIsNotNone(
            root.find("./widget[@class='QMainWindow'][@name='MainWindow']")
        )

    def test_stylesheet_is_external(self) -> None:
        root = ET.parse("app/ui/forms/mainwindow.ui").getroot()
        self.assertIsNone(root.find("./widget/property[@name='styleSheet']"))
        self.assertTrue(
            Path("app/ui/styles/dark.qss").read_text(encoding="utf-8").strip()
        )

    def test_ui_structure_contract_matches_planning_baseline(self) -> None:
        from scripts.validate_ui import object_name_hash, structural_hash

        root = ET.parse("app/ui/forms/mainwindow.ui").getroot()
        self.assertEqual(
            structural_hash(root),
            "e7e4b8fa796a64da26c942fe1c9d975aadf50d3a3c0ccb8d04b4c84337c7c9f1",
        )
        self.assertEqual(
            object_name_hash(root),
            "8d17cd5bf6f70474baa34cf9e9a7b926904dea8a0e1b3446753b81fa1bce0189",
        )

    def test_ui_starts_live_empty_and_disables_unimplemented_actions(self) -> None:
        root = ET.parse("app/ui/forms/mainwindow.ui").getroot()
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

        self.assertEqual(text("paperModeButton"), "LIVE 正式实盘")
        self.assertEqual(text("paperOrderButton"), "LIVE 正式下单")

        value_labels = [
            name for name in widgets
            if name.endswith("ValueLabel")
        ]
        self.assertTrue(value_labels)
        self.assertEqual({text(name) for name in value_labels}, {"—"})

        for name in (
            "binancePublicStatusLabel",
            "binancePrivateStatusLabel",
            "bitgetPublicStatusLabel",
            "bitgetPrivateStatusLabel",
            "webSocketLatencyStatusLabel",
        ):
            self.assertIn("未连接", text(name))
            self.assertFalse(positive(name), name)

        for name in value_labels:
            self.assertFalse(positive(name), name)
        self.assertFalse(positive("topLatencyLabel"))
        self.assertFalse(positive("webSocketLatencyStatusLabel"))

        minimum_funding = widgets["minimumFundingDoubleSpinBox"]
        leverage = widgets["leverageSpinBox"]
        self.assertEqual(
            minimum_funding.find("./property[@name='minimum']/double").text,
            "-100.000000000000000",
        )
        self.assertEqual(
            leverage.find("./property[@name='minimum']/number").text,
            "1",
        )

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
            self.assertFalse(enabled(name), name)

        for name, widget in widgets.items():
            if widget.get("class") in {
                "QCheckBox",
                "QComboBox",
                "QDoubleSpinBox",
                "QLineEdit",
                "QSpinBox",
            }:
                self.assertFalse(enabled(name), name)

        for widget in root.iter("widget"):
            if widget.get("class") == "QComboBox":
                self.assertEqual(widget.findall("./item"), [], widget.get("name"))


if __name__ == "__main__":
    unittest.main()
