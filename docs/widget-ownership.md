# Main-window widget ownership

## Opportunity scan

Owner: future `OpportunityPresenter` and `OpportunityTableModel`

- `symbolSearchLineEdit`
- `scanAmountComboBox`
- `minimumPnlDoubleSpinBox`
- `minimumFundingDoubleSpinBox`
- `profitableOnlyCheckBox`
- `executableOnlyCheckBox`
- `favoritesOnlyCheckBox`
- `opportunityTableView`

## Dual-leg order entry

Owner: future `OrderEntryPresenter`

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

`paperOrderButton` is a legacy Qt Designer objectName. Python binds it as `live_order_button`; the control is disabled until a later LIVE order stage and does not provide simulated ordering.

## Position and history area

Owner: future `PositionPresenter`

- `positionTableView`
- `executingOrdersTableView`
- `orderHistoryTableView`
- `fundingHistoryTableView`
- `positionTabWidget`

## Global shell and connections

Owner: `MainWindowPresenter`, future `ConnectionPresenter`, future `AccountPresenter`

- `paperModeButton`
- `refreshProductsButton`
- `refreshAccountsButton`
- `settingsButton`
- `systemLogButton`
- connection and status labels

All bindings are centralized in `app/ui/loader/widget_registry.py`.

`paperModeButton` is also a legacy objectName. Python binds it as `live_mode_button`; its visible text identifies the fixed LIVE production environment and it never switches runtime mode.
