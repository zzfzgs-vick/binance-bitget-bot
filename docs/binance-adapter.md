# Binance adapter boundary

- REST transport: direct `requests` usage.
- WebSocket transport: direct `websockets` usage.
- No exchange SDK or alternate HTTP/WebSocket framework.
- Spot and USDⓈ-M public WebSocket clients support production subscriptions,
  unsubscriptions, protocol ping/pong, bounded reconnect, and subscription restore.
- Private WebSocket classes expose production entry points only. Spot validates the
  signed user-data subscription acknowledgement. USDⓈ-M creates, periodically
  renews, rebuilds after expiry, and closes its listen key.
- WebSocket transport messages remain available as raw JSON and supported public,
  account, position, order, and fill messages are normalized before application
  state or execution reconciliation consumes them.
- Spot and USDⓈ-M exchange-information payloads are normalized into domain
  instruments from official asset, status, price-filter, lot-size, and minimum-
  notional fields. Missing, invalid, duplicate, or conflicting rules are errors.
- Spot and USDⓈ-M `bookTicker`, 24-hour ticker, depth, and USDⓈ-M mark-price
  messages emit Decimal best-quote, order-book, and funding-rate events. Depth
  synchronization checks `lastUpdateId + 1` against the first spot `[U, u]`, but
  checks `lastUpdateId` against the first USDⓈ-M `[U, u]`; later USDⓈ-M updates
  require `pu` to equal the previously applied `u`.
