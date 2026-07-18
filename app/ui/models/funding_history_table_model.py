"""Table headers for funding payments."""

from app.ui.models.base_table_model import ReadOnlyTableModel

FUNDING_HISTORY_COLUMNS = (
    "时间",
    "组合编号",
    "交易对",
    "永续交易所",
    "资金费率",
    "名义价值",
    "到账金额",
)


class FundingHistoryTableModel(ReadOnlyTableModel):
    def __init__(self) -> None:
        super().__init__(FUNDING_HISTORY_COLUMNS)
