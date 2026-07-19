"""Standard-library console and rotating-file logging configuration."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from app.infrastructure.config.configuration import LoggingSettings
from app.infrastructure.security.secret_redactor import redact_secrets


LOGGER_NAME = "binance_bitget_bot"
_HANDLER_MARKER = "_binance_bitget_bot_handler"
_THIRD_PARTY_LOGGERS = ("requests", "urllib3", "websockets", "PySide6")


class _RedactingFormatter(logging.Formatter):
    def __init__(self, secrets: tuple[str, ...]) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s %(message)s")
        self._secrets = secrets

    def format(self, record: logging.LogRecord) -> str:
        return redact_secrets(super().format(record), self._secrets)


def configure_logging(
    settings: LoggingSettings,
    secrets: tuple[str, ...] = (),
    *,
    logger_name: str = LOGGER_NAME,
) -> logging.Logger:
    """Configure one application logger once and return it."""
    logger = logging.getLogger(logger_name)
    logger.setLevel(settings.level)
    logger.propagate = False
    for third_party_name in _THIRD_PARTY_LOGGERS:
        third_party = logging.getLogger(third_party_name)
        if third_party_name == "websockets":
            # DEBUG protocol records contain complete frames, including private
            # authentication messages. Keep them outside every application sink.
            third_party.setLevel(
                max(logging.WARNING, logging.getLevelName(settings.third_party_level))
            )
            third_party.propagate = False
            if not third_party.handlers:
                third_party.addHandler(logging.NullHandler())
        else:
            third_party.setLevel(settings.third_party_level)
    managed_handlers = tuple(
        handler
        for handler in logger.handlers
        if getattr(handler, _HANDLER_MARKER, False)
    )
    existing_secrets = tuple(
        secret
        for handler in managed_handlers
        for secret in getattr(handler.formatter, "_secrets", ())
    )
    formatter = _RedactingFormatter(
        tuple(dict.fromkeys((*existing_secrets, *secrets)))
    )
    if managed_handlers:
        for handler in managed_handlers:
            handler.setLevel(settings.level)
            handler.setFormatter(formatter)
        return logger

    settings.directory.mkdir(parents=True, exist_ok=True)
    console = logging.StreamHandler()
    rotating_file = RotatingFileHandler(
        settings.directory / settings.file_name,
        maxBytes=settings.max_bytes,
        backupCount=settings.backup_count,
        encoding="utf-8",
    )
    for handler in (console, rotating_file):
        handler.setLevel(settings.level)
        handler.setFormatter(formatter)
        setattr(handler, _HANDLER_MARKER, True)
        logger.addHandler(handler)
    return logger


def shutdown_logging(logger: logging.Logger) -> None:
    """Close and remove only handlers created by this module."""
    for handler in tuple(logger.handlers):
        if not getattr(handler, _HANDLER_MARKER, False):
            continue
        logger.removeHandler(handler)
        handler.close()
