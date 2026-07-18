"""Runtime object graph for the UI-only skeleton."""

from __future__ import annotations

from dataclasses import dataclass

from app.ui.presenters.main_window_presenter import MainWindowPresenter
from app.ui.views.main_window import MainWindowView


@dataclass(slots=True)
class ApplicationRuntime:
    """Objects kept alive for the lifetime of the Qt application."""

    main_window: MainWindowView
    main_window_presenter: MainWindowPresenter

    def shutdown(self) -> None:
        """Release UI resources. Business workers will be added later."""
        self.main_window.close()
