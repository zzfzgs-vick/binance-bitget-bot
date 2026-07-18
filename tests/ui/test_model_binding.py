import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
except ModuleNotFoundError:
    QApplication = None


@unittest.skipUnless(QApplication is not None, "PySide6 is not installed")
class ModelBindingTests(unittest.TestCase):
    def test_presenter_binds_all_table_models(self) -> None:
        from app.ui.presenters.main_window_presenter import MainWindowPresenter
        from app.ui.views.main_window import MainWindowView

        app = QApplication.instance() or QApplication([])
        view = MainWindowView()
        presenter = MainWindowPresenter(view)
        presenter.bind()
        self.assertIsNotNone(view.widgets.opportunity_table.model())
        self.assertIsNotNone(view.widgets.position_table.model())
        self.assertIsNotNone(view.widgets.executing_orders_table.model())
        self.assertIsNotNone(view.widgets.order_history_table.model())
        self.assertIsNotNone(view.widgets.funding_history_table.model())
        view.close()
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
