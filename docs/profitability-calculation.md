# Profitability calculation

`calculate_opportunity(buy_book, sell_book, request)` is the stage 7 calculation
seam. It accepts valid normalized order-book snapshots for different exchanges and
an `OpportunityRequest` containing exactly one target (`base_quantity` or
`quote_amount`), explicit fee rates, the observation time, and the maximum accepted
market-data age. It performs no network, account, order, GUI, or persistence work.

The requested common base-asset quantity is rounded down to a step executable by
both legs. Each leg's exchange order quantity is `base quantity / contract
multiplier`. The buy side consumes asks from low to high; the sell side consumes
bids from high to low. Each level contributes `price * base quantity` to its leg's
notional. A quote-amount request is interpreted as the buy-leg notional budget,
excluding fees, and is converted through the same ask depth before quantity
normalization.

For each leg:

```text
average price = executed notional / common base quantity
fee           = executed notional * explicit fee rate
buy slippage  = executed buy notional - best ask * quantity
sell slippage = best bid * quantity - executed sell notional
```

The opportunity result uses these formulas:

```text
gross profit = sell notional - buy notional
total fee    = buy fee + sell fee
net profit   = gross profit - total fee
ROI          = net profit / buy notional
```

Slippage is reported separately but is already reflected in executed notionals and
therefore must not be subtracted from net profit again. Zero and negative results
remain observable. Missing fee rates, incompatible instruments, invalid or stale
books, insufficient depth, and violations of minimum quantity, maximum quantity,
quantity step, or minimum notional raise `ArbitrageCalculationError` rather than
producing an executable opportunity.
