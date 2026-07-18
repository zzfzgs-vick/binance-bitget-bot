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

The current archive implements only UI loading, widget binding, empty table models,
and Presenter association. Trading-related modules remain placeholders.
