"""Runtime object graph for the UI-only skeleton."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.ui.presenters.main_window_presenter import MainWindowPresenter
from app.ui.views.main_window import MainWindowView


@dataclass(slots=True)
class ApplicationRuntime:
    """Objects kept alive for the lifetime of the Qt application."""

    main_window: MainWindowView
    main_window_presenter: MainWindowPresenter
    _is_shutdown: bool = field(default=False, init=False, repr=False)

    def shutdown(self) -> None:
        """Release UI resources. Business workers will be added later."""
        if self._is_shutdown:
            return
        self._is_shutdown = True
        self.main_window.dispose()
