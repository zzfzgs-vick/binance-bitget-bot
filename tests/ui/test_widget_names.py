from pathlib import Path
import unittest
from xml.etree import ElementTree as ET

REQUIRED = {
    "opportunityTableView",
    "positionTableView",
    "executingOrdersTableView",
    "orderHistoryTableView",
    "fundingHistoryTableView",
    "spotInvestmentDoubleSpinBox",
    "leverageSpinBox",
    "marginModeComboBox",
    "refreshQuoteButton",
    "paperOrderButton",
    "confirmDualLegButton",
}


class WidgetNameTests(unittest.TestCase):
    def test_required_widget_names_exist(self) -> None:
        root = ET.parse(Path("app/ui/forms/mainwindow.ui")).getroot()
        names = {node.get("name") for node in root.iter() if node.get("name")}
        self.assertFalse(REQUIRED - names)


if __name__ == "__main__":
    unittest.main()
