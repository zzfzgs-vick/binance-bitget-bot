"""Typed, non-sensitive application configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import os
from pathlib import Path
import tomllib


class ConfigurationError(ValueError):
    """Raised when a configuration field is invalid."""


def _string(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ConfigurationError(f"{field_name}: expected string")
    if not value.strip():
        raise ConfigurationError(f"{field_name}: must not be empty")
    return value


def _level(value: object, field_name: str) -> str:
    name = _string(value, field_name).upper()
    if name not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ConfigurationError(f"{field_name}: invalid logging level {value!r}")
    return name


def _path(value: object, field_name: str) -> Path:
    if isinstance(value, Path):
        return value
    return Path(_string(value, field_name))


def _integer(value: object, field_name: str, minimum: int) -> int:
    if type(value) is not int:
        raise ConfigurationError(f"{field_name}: expected integer")
    if value < minimum:
        raise ConfigurationError(f"{field_name}: must be >= {minimum}")
    return value


def _environment_integer(
    environment: Mapping[str, str],
    variable: str,
    fallback: object,
    field_name: str,
    minimum: int,
) -> int:
    if variable not in environment:
        return _integer(fallback, field_name, minimum)
    try:
        value = int(environment[variable])
    except (TypeError, ValueError) as error:
        raise ConfigurationError(
            f"{field_name}: {variable} must be an integer"
        ) from error
    return _integer(value, field_name, minimum)


def _reject_unknown(
    values: Mapping[str, object],
    allowed: set[str],
    prefix: str = "",
) -> None:
    unknown = sorted(set(values) - allowed)
    if unknown:
        field_name = f"{prefix}.{unknown[0]}" if prefix else unknown[0]
        reason = "unknown field" if prefix else "unknown section"
        raise ConfigurationError(f"{field_name}: {reason}")


def _table(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ConfigurationError(f"{field_name}: expected table")
    return value


@dataclass(frozen=True, slots=True)
class ApplicationSettings:
    mode: str = "live"


@dataclass(frozen=True, slots=True)
class LoggingSettings:
    level: str = "INFO"
    third_party_level: str = "WARNING"
    directory: Path = Path("logs")
    file_name: str = "application.log"
    max_bytes: int = 5_000_000
    backup_count: int = 3


@dataclass(frozen=True, slots=True)
class AppConfig:
    application: ApplicationSettings = field(default_factory=ApplicationSettings)
    logging: LoggingSettings = field(default_factory=LoggingSettings)


def load_config(
    path: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> AppConfig:
    """Load non-sensitive TOML configuration."""
    try:
        with path.open("rb") as config_file:
            values = tomllib.load(config_file)
    except tomllib.TOMLDecodeError as error:
        raise ConfigurationError(f"{path}: invalid TOML: {error}") from error
    defaults = AppConfig()
    _reject_unknown(values, {"application", "logging"})
    application = _table(values.get("application", {}), "application")
    logging_values = _table(values.get("logging", {}), "logging")
    _reject_unknown(application, {"mode"}, "application")
    _reject_unknown(
        logging_values,
        {
            "level",
            "third_party_level",
            "directory",
            "file_name",
            "max_bytes",
            "backup_count",
        },
        "logging",
    )
    environment = os.environ if environ is None else environ
    mode = _string(application.get("mode", defaults.application.mode), "application.mode")
    if mode != "live":
        raise ConfigurationError("application.mode: only 'live' is supported")
    return AppConfig(
        application=ApplicationSettings(mode=mode),
        logging=LoggingSettings(
            level=_level(
                environment.get(
                    "APP_LOG_LEVEL",
                    logging_values.get("level", defaults.logging.level),
                ),
                "logging.level",
            ),
            third_party_level=_level(
                environment.get(
                    "APP_THIRD_PARTY_LOG_LEVEL",
                    logging_values.get(
                        "third_party_level", defaults.logging.third_party_level
                    ),
                ),
                "logging.third_party_level",
            ),
            directory=_path(
                environment.get(
                    "APP_LOG_DIRECTORY",
                    logging_values.get("directory", defaults.logging.directory),
                ),
                "logging.directory",
            ),
            file_name=_string(
                environment.get(
                    "APP_LOG_FILE",
                    logging_values.get("file_name", defaults.logging.file_name),
                ),
                "logging.file_name",
            ),
            max_bytes=_environment_integer(
                environment,
                "APP_LOG_MAX_BYTES",
                logging_values.get("max_bytes", defaults.logging.max_bytes),
                "logging.max_bytes",
                1,
            ),
            backup_count=_environment_integer(
                environment,
                "APP_LOG_BACKUP_COUNT",
                logging_values.get("backup_count", defaults.logging.backup_count),
                "logging.backup_count",
                0,
            ),
        ),
    )
