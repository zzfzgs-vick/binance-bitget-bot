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


if __name__ == "__main__":
    unittest.main()
