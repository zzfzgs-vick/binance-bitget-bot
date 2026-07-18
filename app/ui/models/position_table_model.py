"""Table headers for current arbitrage positions."""

from app.ui.models.base_table_model import ReadOnlyTableModel

POSITION_COLUMNS = (
    "组合编号",
    "交易对",
    "路径",
    "现货数量",
    "永续空仓",
    "对冲比",
    "现货均价",
    "永续均价",
    "当前价差",
    "累计资金费",
    "组合净盈亏",
    "状态",
    "操作",
)


class PositionTableModel(ReadOnlyTableModel):
    def __init__(self) -> None:
        super().__init__(POSITION_COLUMNS)
