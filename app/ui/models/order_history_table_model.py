"""Table headers for historical order groups."""

from app.ui.models.base_table_model import ReadOnlyTableModel

ORDER_HISTORY_COLUMNS = (
    "订单组",
    "交易对",
    "路径",
    "开仓时间",
    "结束时间",
    "结果",
    "净盈亏",
)


class OrderHistoryTableModel(ReadOnlyTableModel):
    def __init__(self) -> None:
        super().__init__(ORDER_HISTORY_COLUMNS)
