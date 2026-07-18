"""Application composition root."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path

from app.container import ApplicationRuntime
from app.infrastructure.config.configuration import load_config
from app.infrastructure.config.paths import live_config_path
from app.infrastructure.logging.logging_config import configure_logging, shutdown_logging
from app.infrastructure.security.credential_store import load_api_credentials
from app.ui.presenters.main_window_presenter import MainWindowPresenter
from app.ui.views.main_window import MainWindowView


def build_application(
    config_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> ApplicationRuntime:
    """Build the UI object graph without creating any trading services."""
    environment = os.environ if environ is None else environ
    configuration = load_config(config_path or live_config_path(), environ=environment)
    credentials = load_api_credentials(environment)
    logger = configure_logging(configuration.logging, credentials.secret_values())
    logger.info("Configuration loaded; credentials complete=%s", credentials.is_complete())
    main_window = None
    try:
        main_window = MainWindowView()
        presenter = MainWindowPresenter(main_window)
        presenter.bind()
        return ApplicationRuntime(
            main_window=main_window,
            main_window_presenter=presenter,
            configuration=configuration,
            credentials=credentials,
            logger=logger,
        )
    except Exception:
        if main_window is not None:
            main_window.dispose()
        shutdown_logging(logger)
        raise
