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
WebSocket foundations, and exchange product normalization. Each WebSocket client
owns one background thread and one asyncio event loop; it does not touch Qt
objects. Exchange mappers translate raw product payloads into domain `Instrument`
and `TradingRules` values; the domain owns matching and Decimal quantization and
does not depend on Qt or networking libraries.
