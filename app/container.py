"""Runtime object graph for the UI-only skeleton."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging

from app.domain.enums import Exchange, MarketType
from app.exchanges.base.trading_client import TradingClient
from app.infrastructure.config.configuration import AppConfig
from app.infrastructure.logging.logging_config import shutdown_logging
from app.infrastructure.security.credential_store import ApiCredentials
from app.ui.presenters.main_window_presenter import MainWindowPresenter
from app.ui.views.main_window import MainWindowView
from app.workers.execution_worker import ExecutionWorker
from app.workers.worker_signals import LiveEventBridge


@dataclass(slots=True)
class ApplicationRuntime:
    """Objects kept alive for the lifetime of the Qt application."""

    main_window: MainWindowView
    main_window_presenter: MainWindowPresenter
    configuration: AppConfig
    credentials: ApiCredentials
    logger: logging.Logger
    execution_worker: ExecutionWorker | None = None
    trading_clients: dict[
        tuple[Exchange, MarketType], TradingClient
    ] = field(default_factory=dict)
    live_events: LiveEventBridge | None = None
    _is_shutdown: bool = field(default=False, init=False, repr=False)

    def shutdown(self) -> None:
        """Release background execution, REST pools, and Qt resources once."""
        if self._is_shutdown:
            return
        self._is_shutdown = True
        try:
            self.main_window_presenter.shutdown()
            for client in self.trading_clients.values():
                close = getattr(client, "close", None)
                if close is not None:
                    close()
        finally:
            try:
                self.main_window.dispose()
            finally:
                shutdown_logging(self.logger)
