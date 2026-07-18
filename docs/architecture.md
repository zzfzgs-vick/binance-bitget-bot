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
depth-aware arbitrage calculation, normalized account/order reconciliation,
arbitrage-position state, and explicit manual two-leg execution.
Each WebSocket client owns one background thread and one asyncio event loop; it
does not touch Qt objects. Exchange mappers translate raw product and market
payloads into domain values. The domain owns matching, Decimal quantization, and
sequence-aware order-book state, and Decimal opportunity results without depending
on Qt or networking libraries. The strategy calculation seam accepts two normalized
book snapshots plus one explicit request and returns a result without side effects.

The GUI execution path is:

```text
Qt control -> View Signal -> Presenter -> ExecutionWorker
                                      -> synchronous LIVE REST adapter
background result -> Qt Signal -> Presenter -> QAbstractTableModel / labels
```

`ExecutionWorker` owns a single focused REST thread pool. It never receives Qt
widgets and cannot update the GUI directly. Existing WebSocket clients retain
their independent background-thread asyncio event loops; normalized private
events enter the GUI/application boundary through the Composition Root's
`LiveEventBridge` and can be submitted to the open or close reconciler through
the worker.

The Composition Root creates production-only Binance/Bitget spot and USDT
perpetual trading adapters and the worker without starting connections or
orders. Opening requires the existing two-step GUI confirmation. Closing
requires a double-click on the position action column and current explicit
reference prices. If an order submission is uncertain, the GUI exposes a
query-only recovery action for the original client order id; it never retries
the create request blindly.
