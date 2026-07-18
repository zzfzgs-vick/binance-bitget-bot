# Binance adapter boundary

- REST transport: direct `requests` usage.
- WebSocket transport: direct `websockets` usage.
- No exchange SDK or alternate HTTP/WebSocket framework.
- Spot and USDⓈ-M public WebSocket clients support production subscriptions,
  unsubscriptions, protocol ping/pong, bounded reconnect, and subscription restore.
- Private WebSocket classes expose production entry points only. Existing futures
  listen keys can be supplied, but acquiring, renewing, or deleting them is outside
  this stage. Spot session authentication is also deferred.
- WebSocket transport messages remain available as raw JSON. Stage 6 additionally
  maps the supported public market messages into domain market-data events; account
  and order normalization remain out of scope.
- Spot and USDⓈ-M exchange-information payloads are normalized into domain
  instruments from official asset, status, price-filter, lot-size, and minimum-
  notional fields. Missing, invalid, duplicate, or conflicting rules are errors.
- Spot and USDⓈ-M `bookTicker`, 24-hour ticker, depth, and USDⓈ-M mark-price
  messages emit Decimal best-quote, order-book, and funding-rate events. Depth
  synchronization checks `lastUpdateId + 1` against the first spot `[U, u]`, but
  checks `lastUpdateId` against the first USDⓈ-M `[U, u]`; later USDⓈ-M updates
  require `pu` to equal the previously applied `u`.
