# Architecture baseline

Dependency direction:

```text
UI -> Application -> Domain
                  ^
Infrastructure / Exchange adapters
```

Approved infrastructure libraries:

```text
Qt GUI       PySide6 6.11.1
REST         requests 2.34.2
WebSocket    websockets 16.1
Persistence  Python sqlite3 (future)
```

The current implementation includes UI loading and association, configuration,
logging, environment-only credentials, synchronous REST foundations, threaded
WebSocket foundations, exchange product normalization, market-event processing,
and depth-aware arbitrage calculation.
Each WebSocket client owns one background thread and one asyncio event loop; it
does not touch Qt objects. Exchange mappers translate raw product and market
payloads into domain values. The domain owns matching, Decimal quantization, and
sequence-aware order-book state, and Decimal opportunity results without depending
on Qt or networking libraries. The strategy calculation seam accepts two normalized
book snapshots plus one explicit request and returns a result without side effects.
