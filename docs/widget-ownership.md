# Main-window widget ownership

## Opportunity scan

Owner: `OpportunityPresenter` and `OpportunityTableModel`

- `symbolSearchLineEdit`
- `scanAmountComboBox`
- `minimumPnlDoubleSpinBox`
- `minimumFundingDoubleSpinBox`
- `profitableOnlyCheckBox`
- `executableOnlyCheckBox`
- `favoritesOnlyCheckBox`
- `opportunityTableView`

## Dual-leg order entry

Owner: `OrderEntryPresenter`

- `spotInvestmentDoubleSpinBox`
- `spotMaxSlippageDoubleSpinBox`
- `spotOrderTypeComboBox`
- `spotLimitPriceDoubleSpinBox`
- `marginModeComboBox`
- `leverageSpinBox`
- `perpetualMaxSlippageDoubleSpinBox`
- `perpetualOrderTypeComboBox`
- `perpetualLimitPriceDoubleSpinBox`
- `marginBufferDoubleSpinBox`
- `refreshQuoteButton`
- `paperOrderButton`
- `confirmDualLegButton`

`paperOrderButton` is a legacy Qt Designer objectName. Python binds it as
`live_order_button`; it prepares the selected LIVE opportunity, while
`confirmDualLegButton` is the separate explicit order trigger. Neither control
provides simulated ordering.

## Position and history area

Owner: `PositionPresenter`

- `positionTableView`
- `executingOrdersTableView`
- `orderHistoryTableView`
- `fundingHistoryTableView`
- `positionTabWidget`

The existing position table `操作` column emits the manual close request on a
double-click. No new widget, layout change, or automatic close path is used.

## Global shell and connections

Owner: `MainWindowPresenter`, future `ConnectionPresenter`, `AccountPresenter`

- `paperModeButton`
- `refreshProductsButton`
- `refreshAccountsButton`
- `settingsButton`
- `systemLogButton`
- connection and status labels

All bindings are centralized in `app/ui/loader/widget_registry.py`.

`paperModeButton` is also a legacy objectName. Python binds it as `live_mode_button`; its visible text identifies the fixed LIVE production environment and it never switches runtime mode.
