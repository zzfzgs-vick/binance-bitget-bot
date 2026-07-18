import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication, QMainWindow
except ModuleNotFoundError:
    QApplication = None
    QMainWindow = None


@unittest.skipUnless(QApplication is not None, "PySide6 is not installed")
class MainWindowRuntimeTests(unittest.TestCase):
    def test_mainwindow_runtime_load(self) -> None:
        from app.ui.loader.ui_loader import load_typed_ui
        from app.ui.loader.widget_registry import MainWindowWidgets

        app = QApplication.instance() or QApplication([])
        window = load_typed_ui(Path("app/ui/forms/mainwindow.ui"), QMainWindow)
        MainWindowWidgets.bind(window)
        window.close()
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
