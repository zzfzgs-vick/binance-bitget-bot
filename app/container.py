"""Runtime object graph for the UI-only skeleton."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from PySide6.QtCore import QCoreApplication, QEvent

from app.domain.enums import Exchange, MarketType
from app.exchanges.base.trading_client import TradingClient
from app.infrastructure.config.configuration import AppConfig
from app.infrastructure.logging.logging_config import shutdown_logging
from app.infrastructure.security.credential_store import ApiCredentials
from app.ui.presenters.main_window_presenter import MainWindowPresenter
from app.ui.views.main_window import MainWindowView
from app.workers.execution_worker import ExecutionWorker
from app.workers.worker_signals import LiveEventBridge
from app.workers.market_data_worker import LiveDataWorker


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
    live_data_worker: LiveDataWorker | None = None
    closeable_clients: tuple[object, ...] = ()
    _is_started: bool = field(default=False, init=False, repr=False)
    _is_shutdown: bool = field(default=False, init=False, repr=False)

    def start(self) -> None:
        if self._is_shutdown:
            raise RuntimeError("application runtime is shut down")
        if self._is_started:
            return
        self._is_started = True
        self.main_window.set_live_capabilities(
            accounts_available=self.credentials.is_complete()
        )
        if self.live_data_worker is not None:
            self.live_data_worker.start()
        if self.execution_worker is not None:
            self.execution_worker.recover_pending()

    def shutdown(self) -> None:
        """Release background execution, REST pools, and Qt resources once."""
        if self._is_shutdown:
            return
        self._is_shutdown = True
        application = QCoreApplication.instance()
        first_error: Exception | None = None

        def attempt(action) -> None:
            nonlocal first_error
            try:
                action()
            except Exception as exc:
                if first_error is None:
                    first_error = exc

        if self.live_data_worker is not None:
            try:
                self.main_window_presenter.positions_changed.disconnect(
                    self.live_data_worker.track_positions
                )
            except (RuntimeError, TypeError):
                pass
            attempt(self.live_data_worker.shutdown)
        if self.live_events is not None:
            attempt(self.live_events.disconnect_all)
        if application is not None:
            attempt(application.processEvents)
        attempt(self.main_window_presenter.shutdown)
        if application is not None:
            attempt(application.processEvents)
        for client in dict.fromkeys(
            (*self.trading_clients.values(), *self.closeable_clients)
        ):
            close = getattr(client, "close", None)
            if close is not None:
                attempt(close)
        try:
            attempt(self.main_window.dispose)
            if application is not None:
                attempt(lambda: QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete))
                attempt(application.processEvents)
        finally:
            attempt(lambda: shutdown_logging(self.logger))
        if first_error is not None:
            raise first_error
