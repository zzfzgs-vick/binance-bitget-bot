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
Presenter         model association and later application orchestration
      ↓
Application       future use cases
```

No `ui_mainwindow.py` is generated or manually maintained.

The stylesheet is stored separately at `app/ui/styles/dark.qss` and applied by `MainWindowView`.

## View composition

`MainWindowView` inherits `QObject`, not `QMainWindow`. It owns the loaded `QMainWindow` as `view.window`. This avoids copying or stealing a central widget from a temporary loaded window and keeps runtime loading deterministic.

## Composition and lifetime

`build_application()` is the single Composition Root for the current stage. It creates the View and main Presenter, binds the five table models, and returns `ApplicationRuntime`. The runtime keeps the Qt objects alive and provides an idempotent `shutdown()`; no exchange, market-data, execution, database, worker, or configuration modules are composed yet.

## LIVE-only empty state

The UI starts with empty tables, `—` for unavailable business values, disconnected exchange status, and disabled future actions. The legacy objectName values `paperModeButton` and `paperOrderButton` remain only to preserve the `.ui` contract; visible text and Python fields use LIVE semantics and do not provide a mode switch.
