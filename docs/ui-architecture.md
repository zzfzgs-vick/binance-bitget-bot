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
