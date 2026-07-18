# Instrument matching

`Instrument` records exchange, market type, raw symbol, base asset, quote asset,
settlement asset, trading status, raw status, and normalized `TradingRules`.
Adapters support Binance and Bitget spot products and USDT-settled perpetuals.

`match_instruments(left, right)` accepts only different exchanges and instruments
whose normalized status is trading. Base, quote, and settlement assets must match
exactly. The supported market combinations are spot/spot, USDT perpetual/USDT
perpetual, and spot/USDT perpetual in either order.

Raw symbol text is deliberately excluded from compatibility decisions. Therefore,
symbols such as `BTCUSDT` and `BTC-USDT` can match when their asset and market
semantics agree, while visually similar symbols cannot match when those semantics
differ. Known non-trading statuses remain observable as unavailable instruments;
unknown statuses and missing or conflicting product fields are rejected.
