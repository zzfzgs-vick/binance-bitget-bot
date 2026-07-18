# UI architecture

## Formal location

`app/ui/forms/mainwindow.ui`

## Separation

```text
mainwindow.ui     layout and stable objectName contract
      ↓
QUiLoader         runtime XML loading
      ↓
MainWindowView    widget binding, UI signals, display-only methods
      ↓
Presenter         model association and explicit application orchestration
      ↓
Application       future use cases
```

No `ui_mainwindow.py` is generated or manually maintained.

The stylesheet is stored separately at `app/ui/styles/dark.qss` and applied by `MainWindowView`.

## View composition

`MainWindowView` inherits `QObject`, not `QMainWindow`. It owns the loaded `QMainWindow` as `view.window`. This avoids copying or stealing a central widget from a temporary loaded window and keeps runtime loading deterministic.

## Composition and lifetime

`build_application()` is the single Composition Root. It creates the View,
Presenters, five table models, focused execution worker, and four production-only
trading adapters, then returns `ApplicationRuntime`. Construction performs no
network request. The runtime keeps these objects alive and provides an
idempotent `shutdown()` that closes the worker, REST connection pools, Qt window,
and logging handlers.

Blocking order execution always runs in `ExecutionWorker`. Completion and error
events return through Qt Signal, so Presenter slots update models and labels on
the GUI thread. Existing WebSocket clients continue to own an independent
background-thread asyncio loop and never receive widgets. The Composition Root
wires normalized account, opportunity, price, and private order events through
`LiveEventBridge`; it does not choose instruments or start network connections
at application construction time.

## LIVE-only empty state

The UI starts with empty tables, `—` for unavailable business values,
disconnected exchange status, and disabled trading actions. An executable
opportunity enables the first LIVE preparation action; a second explicit GUI
confirmation triggers opening. Manual close is emitted only by the position
table action column and requires current reference prices. The legacy objectName
values are unchanged. An uncertain opening replaces the preparation action with
a query-only action for the original order until its state is reconciled.
`paperModeButton` and `paperOrderButton` remain only to preserve the `.ui`
contract; visible text and Python fields use LIVE semantics and do not provide a
mode switch.
