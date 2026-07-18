# Binance adapter boundary

- REST transport: direct `requests` usage.
- WebSocket transport: direct `websockets` usage.
- No exchange SDK or alternate HTTP/WebSocket framework.
- Spot and USDⓈ-M public WebSocket clients support production subscriptions,
  unsubscriptions, protocol ping/pong, bounded reconnect, and subscription restore.
- Private WebSocket classes expose production entry points only. Existing futures
  listen keys can be supplied, but acquiring, renewing, or deleting them is outside
  this stage. Spot session authentication is also deferred.
- Messages remain raw JSON plus parsed Python objects; no market, account, or order
  normalization is performed here.
