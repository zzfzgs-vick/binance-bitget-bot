"""Display normalized account balances and position summaries."""

from PySide6.QtCore import QObject

from app.domain.accounts.account_snapshot import AccountState
from app.domain.enums import Exchange, MarketType
from app.ui.views.main_window import MainWindowView


class AccountPresenter(QObject):
    def __init__(self, view: MainWindowView) -> None:
        super().__init__(view)
        self._view = view

    def set_states(self, states: tuple[AccountState, ...]) -> None:
        if not all(isinstance(state, AccountState) for state in states):
            raise TypeError("states must contain AccountState values")
        by_exchange = {state.exchange: state for state in states}
        self._set_exchange(Exchange.BINANCE, by_exchange.get(Exchange.BINANCE))
        self._set_exchange(Exchange.BITGET, by_exchange.get(Exchange.BITGET))

    def _set_exchange(
        self, exchange: Exchange, state: AccountState | None
    ) -> None:
        widgets = self._view.widgets
        spot_label, perp_label = (
            (
                widgets.binance_spot_balance_value_label,
                widgets.binance_perp_balance_value_label,
            )
            if exchange is Exchange.BINANCE
            else (
                widgets.bitget_spot_balance_value_label,
                widgets.bitget_perp_balance_value_label,
            )
        )
        if state is None:
            spot_label.setText("—")
            perp_label.setText("—")
            return
        spot = tuple(
            balance
            for balance in state.balances
            if balance.market_type in (MarketType.SPOT, None)
        )
        perp = tuple(
            balance
            for balance in state.balances
            if balance.market_type in (MarketType.USDT_PERPETUAL, None)
        )
        spot_label.setText(_balances(spot))
        position_count = len(state.positions)
        perp_label.setText(
            f"{_balances(perp)} | 持仓 {position_count}"
            if position_count
            else _balances(perp)
        )
        perp_label.setToolTip(
            "\n".join(
                f"{position.instrument.raw_symbol} {position.side.value} "
                f"{position.quantity}"
                for position in state.positions
            )
            or "暂无永续持仓"
        )


def _balances(balances) -> str:
    if not balances:
        return "—"
    return " | ".join(
        f"{balance.asset} 可用 {balance.available} / 总额 {balance.total}"
        for balance in balances
    )
