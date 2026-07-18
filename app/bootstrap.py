"""Application composition root."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path

from app.container import ApplicationRuntime
from app.domain.enums import Exchange, MarketType
from app.exchanges.binance.rest.futures_trading_client import (
    BinanceFuturesTradingClient,
)
from app.exchanges.binance.rest.spot_trading_client import BinanceSpotTradingClient
from app.exchanges.bitget.rest.futures_trading_client import (
    BitgetFuturesTradingClient,
)
from app.exchanges.bitget.rest.spot_trading_client import BitgetSpotTradingClient
from app.infrastructure.config.configuration import load_config
from app.infrastructure.config.paths import live_config_path
from app.infrastructure.logging.logging_config import configure_logging, shutdown_logging
from app.infrastructure.security.credential_store import load_api_credentials
from app.ui.presenters.main_window_presenter import MainWindowPresenter
from app.ui.views.main_window import MainWindowView
from app.workers.execution_worker import ExecutionWorker
from app.workers.worker_signals import LiveEventBridge


def build_application(
    config_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> ApplicationRuntime:
    """Build LIVE adapters without starting network activity or placing orders."""
    environment = os.environ if environ is None else environ
    configuration = load_config(config_path or live_config_path(), environ=environment)
    credentials = load_api_credentials(environment)
    logger = configure_logging(configuration.logging, credentials.secret_values())
    logger.info("Configuration loaded; credentials complete=%s", credentials.is_complete())
    main_window = None
    worker = None
    live_events = None
    trading_clients = {}
    try:
        trading_clients = {
            (Exchange.BINANCE, MarketType.SPOT): BinanceSpotTradingClient(
                credentials=credentials
            ),
            (
                Exchange.BINANCE,
                MarketType.USDT_PERPETUAL,
            ): BinanceFuturesTradingClient(credentials=credentials),
            (Exchange.BITGET, MarketType.SPOT): BitgetSpotTradingClient(
                credentials=credentials
            ),
            (
                Exchange.BITGET,
                MarketType.USDT_PERPETUAL,
            ): BitgetFuturesTradingClient(credentials=credentials),
        }
        worker = ExecutionWorker(trading_clients=trading_clients)
        main_window = MainWindowView()
        presenter = MainWindowPresenter(
            main_window,
            execution_worker=worker,
        )
        presenter.bind()
        live_events = LiveEventBridge(parent=presenter)
        live_events.opportunities_updated.connect(presenter.set_opportunities)
        live_events.account_states_updated.connect(presenter.set_account_states)
        live_events.position_prices_updated.connect(presenter.mark_position)
        live_events.open_order_event.connect(worker.reconcile_open)
        live_events.close_order_event.connect(worker.reconcile_close)
        live_events.status_updated.connect(main_window.set_status)
        return ApplicationRuntime(
            main_window=main_window,
            main_window_presenter=presenter,
            configuration=configuration,
            credentials=credentials,
            logger=logger,
            execution_worker=worker,
            trading_clients=trading_clients,
            live_events=live_events,
        )
    except Exception:
        if worker is not None:
            worker.shutdown()
        for client in trading_clients.values():
            client.close()
        if main_window is not None:
            main_window.dispose()
        shutdown_logging(logger)
        raise
