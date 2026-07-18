"""Table headers for in-flight order groups."""

from app.ui.models.base_table_model import ReadOnlyTableModel

EXECUTING_ORDER_COLUMNS = (
    "订单组",
    "交易对",
    "路径",
    "现货状态",
    "永续状态",
    "已成交数量",
    "状态",
    "更新时间",
)


class ExecutingOrderTableModel(ReadOnlyTableModel):
    def __init__(self) -> None:
        super().__init__(EXECUTING_ORDER_COLUMNS)
