import os
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QItemSelectionModel, QModelIndex, Qt
    from PySide6.QtWidgets import QApplication
except ModuleNotFoundError:
    QApplication = None


@unittest.skipUnless(QApplication is not None, "PySide6 is not installed")
class ModelBindingTests(unittest.TestCase):
    def test_presenter_binds_all_table_models(self) -> None:
        from app.ui.models.executing_order_table_model import (
            EXECUTING_ORDER_COLUMNS,
            ExecutingOrderTableModel,
        )
        from app.ui.models.funding_history_table_model import (
            FUNDING_HISTORY_COLUMNS,
            FundingHistoryTableModel,
        )
        from app.ui.models.opportunity_table_model import (
            OPPORTUNITY_COLUMNS,
            OpportunityTableModel,
        )
        from app.ui.models.order_history_table_model import (
            ORDER_HISTORY_COLUMNS,
            OrderHistoryTableModel,
        )
        from app.ui.models.position_table_model import POSITION_COLUMNS, PositionTableModel
        from app.ui.presenters.main_window_presenter import MainWindowPresenter
        from app.ui.views.main_window import MainWindowView

        app = QApplication.instance() or QApplication([])
        view = MainWindowView()
        presenter = MainWindowPresenter(view)
        presenter.bind()
        bindings = (
            (view.widgets.opportunity_table, OpportunityTableModel, OPPORTUNITY_COLUMNS),
            (view.widgets.position_table, PositionTableModel, POSITION_COLUMNS),
            (
                view.widgets.executing_orders_table,
                ExecutingOrderTableModel,
                EXECUTING_ORDER_COLUMNS,
            ),
            (view.widgets.order_history_table, OrderHistoryTableModel, ORDER_HISTORY_COLUMNS),
            (
                view.widgets.funding_history_table,
                FundingHistoryTableModel,
                FUNDING_HISTORY_COLUMNS,
            ),
        )
        for table, model_type, headers in bindings:
            model = table.model()
            self.assertIsInstance(model, model_type)
            self.assertEqual(model.columnCount(), len(headers))
            self.assertEqual(
                tuple(
                    model.headerData(index, Qt.Orientation.Horizontal)
                    for index in range(model.columnCount())
                ),
                headers,
            )
        view.close()
        app.processEvents()

    def test_presenter_bind_is_idempotent_for_real_table_selection(self) -> None:
        from app.ui.presenters.main_window_presenter import MainWindowPresenter
        from app.ui.views.main_window import MainWindowView

        app = QApplication.instance() or QApplication([])
        view = MainWindowView()
        presenter = MainWindowPresenter(view)
        presenter.bind()
        presenter.bind()
        selection_changed = Mock()
        view.opportunity_selection_changed.connect(selection_changed)

        model = view.widgets.opportunity_table.model()
        model.replace_rows((("ETHUSDT",) * model.columnCount(),))
        view.widgets.opportunity_table.selectionModel().select(
            model.index(0, 0),
            QItemSelectionModel.SelectionFlag.ClearAndSelect,
        )

        selection_changed.assert_called_once_with()
        view.close()
        app.processEvents()

    def test_table_model_replaces_rows_atomically_and_stays_read_only(self) -> None:
        from app.ui.models.base_table_model import ReadOnlyTableModel

        model = ReadOnlyTableModel(("交易对", "状态"), (("BTCUSDT", "旧"),))
        model_reset = Mock()
        model.modelReset.connect(model_reset)

        model.replace_rows((("ETHUSDT", "新"),))

        self.assertEqual(model.rowCount(), 1)
        self.assertEqual(model.columnCount(), 2)
        self.assertEqual(model.data(model.index(0, 0)), "ETHUSDT")
        self.assertEqual(model.headerData(1, Qt.Orientation.Horizontal), "状态")
        self.assertEqual(model.headerData(0, Qt.Orientation.Vertical), 1)
        self.assertEqual(model.data(QModelIndex()), None)
        self.assertEqual(model.flags(QModelIndex()), Qt.ItemFlag.NoItemFlags)
        self.assertFalse(model.flags(model.index(0, 0)) & Qt.ItemFlag.ItemIsEditable)
        model_reset.assert_called_once_with()

        with self.assertRaisesRegex(
            ValueError,
            r"第 0 行列数错误: 期望 2, 实际 1",
        ):
            model.replace_rows((("INVALID",),))

        self.assertEqual(model.data(model.index(0, 0)), "ETHUSDT")


if __name__ == "__main__":
    unittest.main()
