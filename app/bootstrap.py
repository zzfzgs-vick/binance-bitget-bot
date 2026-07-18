"""Application composition root."""

from __future__ import annotations

from app.container import ApplicationRuntime
from app.ui.presenters.main_window_presenter import MainWindowPresenter
from app.ui.views.main_window import MainWindowView


def build_application() -> ApplicationRuntime:
    """Build the UI object graph without creating any trading services."""
    main_window = MainWindowView()
    try:
        presenter = MainWindowPresenter(main_window)
        presenter.bind()
        return ApplicationRuntime(
            main_window=main_window,
            main_window_presenter=presenter,
        )
    except Exception:
        main_window.dispose()
        raise
