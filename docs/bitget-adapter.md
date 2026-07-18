# Bitget adapter boundary

- REST transport: direct `requests` usage.
- WebSocket transport: direct `websockets` usage.
- No exchange SDK or alternate HTTP/WebSocket framework.
- Public production clients support subscriptions, unsubscriptions, application
  ping/pong, bounded reconnect, and subscription restore.
- Private production clients construct the signed login message from in-memory
  credentials on every connection. Authentication data is never logged.
- Messages remain raw JSON plus parsed Python objects; no market, account, or order
  normalization is performed here.
- UTA spot and USDT-futures instrument payloads are normalized into domain
  instruments. Spot steps derive from official precisions; perpetual steps use
  official multipliers validated against those precisions. Unknown status and
  incomplete or conflicting rule data are errors.
