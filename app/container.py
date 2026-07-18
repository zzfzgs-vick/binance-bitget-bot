"""Runtime object graph for the UI-only skeleton."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging

from app.infrastructure.config.configuration import AppConfig
from app.infrastructure.logging.logging_config import shutdown_logging
from app.infrastructure.security.credential_store import ApiCredentials
from app.ui.presenters.main_window_presenter import MainWindowPresenter
from app.ui.views.main_window import MainWindowView


@dataclass(slots=True)
class ApplicationRuntime:
    """Objects kept alive for the lifetime of the Qt application."""

    main_window: MainWindowView
    main_window_presenter: MainWindowPresenter
    configuration: AppConfig
    credentials: ApiCredentials
    logger: logging.Logger
    _is_shutdown: bool = field(default=False, init=False, repr=False)

    def shutdown(self) -> None:
        """Release UI resources. Business workers will be added later."""
        if self._is_shutdown:
            return
        self._is_shutdown = True
        try:
            self.main_window.dispose()
        finally:
            shutdown_logging(self.logger)
