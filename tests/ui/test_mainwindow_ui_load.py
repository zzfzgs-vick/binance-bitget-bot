import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

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

    def test_runtime_loader_reports_wrong_root_type(self) -> None:
        from app.ui.loader.ui_loader import UiLoadError, load_typed_ui

        with TemporaryDirectory() as temporary_directory:
            ui_path = Path(temporary_directory) / "wrong-root.ui"
            ui_path.write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<ui version="4.0">
 <class>Form</class>
 <widget class="QWidget" name="Form"/>
 <resources/>
 <connections/>
</ui>
""",
                encoding="utf-8",
            )
            with self.assertRaises(UiLoadError) as raised:
                load_typed_ui(ui_path, QMainWindow)
            message = str(raised.exception)
            self.assertIn(str(ui_path.resolve()), message)
            self.assertIn("期望 QMainWindow, 实际 QWidget", message)

    def test_widget_binding_reports_missing_and_wrong_types(self) -> None:
        from PySide6.QtWidgets import QLabel, QPushButton, QWidget

        from app.ui.loader.widget_registry import WidgetBindingError, required_child

        root = QWidget()
        wrong_type = QLabel(root)
        wrong_type.setObjectName("liveActionButton")

        with self.assertRaisesRegex(
            WidgetBindingError,
            r"missingButton.*QPushButton",
        ):
            required_child(root, QPushButton, "missingButton")

        with self.assertRaisesRegex(
            WidgetBindingError,
            r"liveActionButton.*QPushButton.*QLabel",
        ):
            required_child(root, QPushButton, "liveActionButton")

    def test_application_runtime_shutdown_is_idempotent(self) -> None:
        from app.container import ApplicationRuntime

        view = Mock()
        runtime = ApplicationRuntime(
            main_window=view,
            main_window_presenter=Mock(),
        )

        runtime.shutdown()
        runtime.shutdown()

        view.dispose.assert_called_once_with()

    def test_python_ui_interface_uses_live_not_paper_semantics(self) -> None:
        from app.ui.views.main_window import MainWindowView

        app = QApplication.instance() or QApplication([])
        view = MainWindowView()

        self.assertTrue(hasattr(view.widgets, "live_mode_button"))
        self.assertTrue(hasattr(view.widgets, "live_order_button"))
        self.assertTrue(hasattr(view, "live_order_requested"))
        self.assertFalse(hasattr(view, "paper_order_requested"))
        self.assertFalse(hasattr(view, "mode_change_requested"))

        view.close()
        app.processEvents()

    def test_live_button_action_is_exposed_as_view_signal(self) -> None:
        from app.ui.views.main_window import MainWindowView

        app = QApplication.instance() or QApplication([])
        view = MainWindowView()
        requested = Mock()
        view.live_order_requested.connect(requested)
        view.widgets.live_order_button.setEnabled(True)

        view.widgets.live_order_button.click()

        requested.assert_called_once_with()
        view.close()
        app.processEvents()

    def test_composition_root_builds_empty_models_and_shuts_down_twice(self) -> None:
        from app.bootstrap import build_application

        app = QApplication.instance() or QApplication([])
        runtime = build_application()
        tables = (
            runtime.main_window.widgets.opportunity_table,
            runtime.main_window.widgets.position_table,
            runtime.main_window.widgets.executing_orders_table,
            runtime.main_window.widgets.order_history_table,
            runtime.main_window.widgets.funding_history_table,
        )

        self.assertTrue(all(table.model().rowCount() == 0 for table in tables))
        runtime.shutdown()
        runtime.shutdown()
        app.processEvents()

    def test_initial_state_disables_and_explains_business_inputs(self) -> None:
        from app.bootstrap import build_application

        app = QApplication.instance() or QApplication([])
        runtime = build_application()
        widgets = runtime.main_window.widgets
        business_inputs = (
            widgets.symbol_search,
            widgets.scan_amount,
            widgets.minimum_pnl,
            widgets.minimum_funding,
            widgets.profitable_only,
            widgets.executable_only,
            widgets.favorites_only,
            widgets.spot_investment,
            widgets.spot_max_slippage,
            widgets.spot_order_type,
            widgets.spot_limit_price,
            widgets.margin_mode,
            widgets.leverage,
            widgets.perpetual_max_slippage,
            widgets.perpetual_order_type,
            widgets.perpetual_limit_price,
            widgets.margin_buffer,
        )

        for widget in business_inputs:
            self.assertFalse(widget.isEnabled())
            self.assertIn("后续阶段", widget.toolTip())
        runtime.shutdown()
        app.processEvents()

    def test_main_shuts_down_runtime_when_event_loop_fails(self) -> None:
        from app.main import main

        qt_app = Mock()
        qt_app.exec.side_effect = RuntimeError("event loop failed")
        runtime = Mock()

        with (
            patch("app.main.QApplication.instance", return_value=qt_app),
            patch("app.main.build_application", return_value=runtime),
            self.assertRaisesRegex(RuntimeError, "event loop failed"),
        ):
            main()

        runtime.main_window.show.assert_called_once_with()
        runtime.shutdown.assert_called_once_with()

    def test_composition_root_disposes_view_when_binding_fails(self) -> None:
        from app.bootstrap import build_application

        view = Mock()
        presenter = Mock()
        presenter.bind.side_effect = RuntimeError("binding failed")

        with (
            patch("app.bootstrap.MainWindowView", return_value=view),
            patch("app.bootstrap.MainWindowPresenter", return_value=presenter),
            self.assertRaisesRegex(RuntimeError, "binding failed"),
        ):
            build_application()

        view.dispose.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
