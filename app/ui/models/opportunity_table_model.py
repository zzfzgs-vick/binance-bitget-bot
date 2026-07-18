"""Table headers for arbitrage opportunities."""

from app.ui.models.base_table_model import ReadOnlyTableModel

OPPORTUNITY_COLUMNS = (
    "交易对",
    "路径",
    "现货Ask",
    "永续Bid",
    "资金费",
    "手续费",
    "滑点",
    "预计净利润",
    "资金ROI",
    "状态",
)


class OpportunityTableModel(ReadOnlyTableModel):
    def __init__(self) -> None:
        super().__init__(OPPORTUNITY_COLUMNS)
