# Trading rules

`TradingRules` is the single domain boundary for order-value normalization. Its
tick size, quantity step, minimum quantity, optional maximum quantity, minimum
notional, and contract multiplier are finite positive `Decimal` values. A missing
official rule is an error; adapters do not invent fallbacks.

`normalize_order(price, quantity)` accepts `Decimal` values only. Price is rounded
down to an exact multiple of tick size, and quantity is rounded down to an exact
multiple of quantity step. The normalized quantity is then checked against its
minimum and maximum, and `price * quantity * contract_multiplier` is checked
against minimum notional.

Binance rules come from `PRICE_FILTER`, `LOT_SIZE`, and `MIN_NOTIONAL` or
`NOTIONAL`. Conflicting notional filters are rejected. Bitget spot steps are
derived from its documented precision fields; Bitget USDT perpetual steps use
the explicit price and quantity multipliers and must agree with those precisions.
Bitget `maxOrderQty` equal to zero is represented as no published maximum. Product
list parsers skip delivery contracts and non-USDT perpetuals outside this model's
scope while continuing to reject incomplete target products.
