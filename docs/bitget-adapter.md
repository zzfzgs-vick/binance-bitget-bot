# Bitget adapter boundary

- REST transport: direct `requests` usage.
- WebSocket transport: direct `websockets` usage.
- No exchange SDK or alternate HTTP/WebSocket framework.
- Public production clients support subscriptions, unsubscriptions, application
  ping/pong, bounded reconnect, and subscription restore.
- Private production clients construct the signed login message from in-memory
  credentials on every connection. Authentication data is never logged.
- WebSocket transport messages remain available as raw JSON. Stage 6 additionally
  maps the supported public market messages into domain market-data events; account
  and order normalization remain out of scope.
- UTA spot and USDT-futures instrument payloads are normalized into domain
  instruments. Spot steps derive from official precisions; perpetual steps use
  official multipliers validated against those precisions. Unknown status and
  incomplete or conflicting rule data are errors.
- UTA spot and USDT-futures `ticker` and `books` messages emit Decimal best-quote
  and order-book events. USDT-futures ticker messages also emit funding rate and
  next settlement time. After a snapshot, the snapshot `seq` must fall within the
  first update's `[pseq, seq]` range; later updates require `pseq` to equal the
  prior `seq`. Resets or gaps require a new snapshot.
