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
from app.exchanges.binance.rest.spot_market_client import BinanceSpotMarketClient
from app.exchanges.binance.rest.futures_market_client import BinanceFuturesMarketClient
from app.exchanges.bitget.rest.spot_market_client import BitgetSpotMarketClient
from app.exchanges.bitget.rest.futures_market_client import BitgetFuturesMarketClient
from app.exchanges.binance.rest.account_client import (
    BinanceSpotAccountClient,
    BinanceFuturesAccountClient,
)
from app.exchanges.bitget.rest.account_client import BitgetAccountClient
from app.exchanges.binance.websocket.spot_public_ws import BinanceSpotPublicWebSocketClient
from app.exchanges.binance.websocket.futures_public_ws import BinanceFuturesPublicWebSocketClient
from app.exchanges.bitget.websocket.spot_public_ws import BitgetSpotPublicWebSocketClient
from app.exchanges.bitget.websocket.futures_public_ws import BitgetFuturesPublicWebSocketClient
from app.exchanges.binance.websocket.spot_private_ws import BinanceSpotPrivateWebSocketClient
from app.exchanges.binance.websocket.futures_private_ws import BinanceFuturesPrivateStream
from app.exchanges.bitget.websocket.spot_private_ws import BitgetSpotPrivateWebSocketClient
from app.exchanges.bitget.mappers.account_mapper import private_subscriptions as bitget_account_subscriptions
from app.exchanges.bitget.mappers.order_mapper import private_subscriptions as bitget_order_subscriptions
from app.execution.execution_coordinator import OpenExecutionCoordinator
from app.execution.position_close_executor import PositionCloseExecutor
from app.execution.order_recovery_service import IdempotentOrderService
from app.infrastructure.config.configuration import load_config
from app.infrastructure.config.paths import live_config_path
from app.infrastructure.logging.logging_config import configure_logging, shutdown_logging
from app.infrastructure.security.credential_store import load_api_credentials
from app.ui.presenters.main_window_presenter import MainWindowPresenter
from app.ui.views.main_window import MainWindowView
from app.workers.execution_worker import ExecutionWorker
from app.workers.worker_signals import LiveEventBridge
from app.workers.market_data_worker import LiveDataWorker


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
    closeable_clients = []
    live_data = None
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
        recovery = IdempotentOrderService(
            journal_path=Path(__file__).resolve().parents[1]
            / "data"
            / "order-recovery.json",
            logger=logger,
        )
        worker = ExecutionWorker(
            trading_clients=trading_clients,
            open_executor=OpenExecutionCoordinator(recovery),
            close_executor=PositionCloseExecutor(recovery),
            recovery_service=recovery,
        )
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
        live_events.private_order_event.connect(worker.reconcile_private_order)
        live_events.status_updated.connect(main_window.set_status)
        market_clients = {
            (Exchange.BINANCE, MarketType.SPOT): BinanceSpotMarketClient(),
            (Exchange.BINANCE, MarketType.USDT_PERPETUAL): BinanceFuturesMarketClient(),
            (Exchange.BITGET, MarketType.SPOT): BitgetSpotMarketClient(),
            (Exchange.BITGET, MarketType.USDT_PERPETUAL): BitgetFuturesMarketClient(),
        }
        account_clients = {}
        if credentials.binance_api_key and credentials.binance_api_secret:
            account_clients.update(
                {
                    (Exchange.BINANCE, MarketType.SPOT): BinanceSpotAccountClient(credentials=credentials),
                    (Exchange.BINANCE, MarketType.USDT_PERPETUAL): BinanceFuturesAccountClient(credentials=credentials),
                }
            )
        if (
            credentials.bitget_api_key
            and credentials.bitget_api_secret
            and credentials.bitget_api_passphrase
        ):
            account_clients[(Exchange.BITGET, None)] = BitgetAccountClient(credentials=credentials)
        closeable_clients.extend((*market_clients.values(), *account_clients.values()))

        holder = {}
        def market_message(key):
            return lambda _raw, parsed: holder["worker"].handle_market_message(key, parsed)
        def private_message(exchange):
            return lambda _raw, parsed: holder["worker"].handle_private_message(exchange, parsed)
        def stream_error(error):
            live_events.publish_status(f"WebSocket 异常：{type(error).__name__}")

        public_websockets = {
            (Exchange.BINANCE, MarketType.SPOT): BinanceSpotPublicWebSocketClient(
                on_message=market_message((Exchange.BINANCE, MarketType.SPOT)), on_error=stream_error
            ),
            (Exchange.BINANCE, MarketType.USDT_PERPETUAL): BinanceFuturesPublicWebSocketClient(
                on_message=market_message((Exchange.BINANCE, MarketType.USDT_PERPETUAL)), on_error=stream_error
            ),
            (Exchange.BITGET, MarketType.SPOT): BitgetSpotPublicWebSocketClient(
                on_message=market_message((Exchange.BITGET, MarketType.SPOT)), on_error=stream_error
            ),
            (Exchange.BITGET, MarketType.USDT_PERPETUAL): BitgetFuturesPublicWebSocketClient(
                on_message=market_message((Exchange.BITGET, MarketType.USDT_PERPETUAL)), on_error=stream_error
            ),
        }
        private_streams = {}
        if credentials.binance_api_key and credentials.binance_api_secret:
            private_streams[(Exchange.BINANCE, MarketType.SPOT)] = (
                BinanceSpotPrivateWebSocketClient(
                    credentials=credentials,
                    on_message=private_message(Exchange.BINANCE),
                    on_error=stream_error,
                )
            )
            private_streams[(Exchange.BINANCE, MarketType.USDT_PERPETUAL)] = (
                BinanceFuturesPrivateStream(
                    trading_clients[(Exchange.BINANCE, MarketType.USDT_PERPETUAL)],
                    on_message=private_message(Exchange.BINANCE),
                    on_error=stream_error,
                )
            )
        if (
            credentials.bitget_api_key
            and credentials.bitget_api_secret
            and credentials.bitget_api_passphrase
        ):
            bitget_private = BitgetSpotPrivateWebSocketClient(
                credentials,
                on_message=private_message(Exchange.BITGET),
                on_error=stream_error,
            )
            bitget_private.subscribe(
                *bitget_account_subscriptions(), *bitget_order_subscriptions()
            )
            private_streams[(Exchange.BITGET, None)] = bitget_private
        live_data = LiveDataWorker(
            bridge=live_events,
            market_clients=market_clients,
            account_clients=account_clients,
            trading_clients=trading_clients,
            public_websockets=public_websockets,
            private_streams=private_streams,
            logger=logger,
        )
        holder["worker"] = live_data
        worker.set_readiness_check(live_data.is_execution_ready)
        presenter.positions_changed.connect(live_data.track_positions)
        main_window.refresh_products_requested.connect(live_data.refresh_products)
        main_window.refresh_accounts_requested.connect(live_data.refresh_accounts)
        def request_quote() -> None:
            try:
                live_data.select_symbol(
                    main_window.widgets.symbol_search.text(),
                    main_window.widgets.spot_investment.cleanText(),
                )
            except (RuntimeError, ValueError) as exc:
                main_window.set_status(str(exc), warning=True)

        main_window.refresh_quote_requested.connect(request_quote)
        return ApplicationRuntime(
            main_window=main_window,
            main_window_presenter=presenter,
            configuration=configuration,
            credentials=credentials,
            logger=logger,
            execution_worker=worker,
            trading_clients=trading_clients,
            live_events=live_events,
            live_data_worker=live_data,
            closeable_clients=tuple(closeable_clients),
        )
    except Exception:
        if live_data is not None:
            live_data.shutdown()
        if worker is not None:
            worker.shutdown()
        for client in trading_clients.values():
            client.close()
        for client in closeable_clients:
            client.close()
        if main_window is not None:
            main_window.dispose()
        shutdown_logging(logger)
        raise
