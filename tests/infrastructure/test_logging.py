from logging.handlers import RotatingFileHandler
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


class LoggingConfigurationTests(unittest.TestCase):
    def _close_logger(self, logger: logging.Logger) -> None:
        for handler in tuple(logger.handlers):
            logger.removeHandler(handler)
            handler.close()

    def test_initialization_creates_directory_console_and_rotating_file_handlers(self) -> None:
        from app.infrastructure.config.configuration import LoggingSettings
        from app.infrastructure.logging.logging_config import configure_logging

        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory) / "new" / "logs"
            settings = LoggingSettings(directory=directory)

            logger = configure_logging(
                settings,
                logger_name="tests.logging.directory",
            )
            try:
                self.assertTrue(directory.is_dir())
                self.assertTrue(
                    any(type(handler) is logging.StreamHandler for handler in logger.handlers)
                )
                self.assertTrue(
                    any(isinstance(handler, RotatingFileHandler) for handler in logger.handlers)
                )
            finally:
                self._close_logger(logger)

    def test_initialization_is_idempotent(self) -> None:
        from app.infrastructure.config.configuration import LoggingSettings
        from app.infrastructure.logging.logging_config import configure_logging

        with TemporaryDirectory() as temporary_directory:
            settings = LoggingSettings(directory=Path(temporary_directory))
            logger = configure_logging(settings, logger_name="tests.logging.idempotent")
            try:
                first_handlers = tuple(logger.handlers)

                same_logger = configure_logging(
                    settings,
                    logger_name="tests.logging.idempotent",
                )

                self.assertIs(same_logger, logger)
                self.assertEqual(tuple(logger.handlers), first_handlers)
                self.assertEqual(len(logger.handlers), 2)
            finally:
                self._close_logger(logger)

    def test_idempotent_reinitialization_redacts_new_credentials(self) -> None:
        from app.infrastructure.config.configuration import LoggingSettings
        from app.infrastructure.logging.logging_config import configure_logging

        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            settings = LoggingSettings(directory=directory)
            logger = configure_logging(
                settings,
                ("old-credential",),
                logger_name="tests.logging.new-credentials",
            )
            try:
                configure_logging(
                    settings,
                    ("new-credential",),
                    logger_name="tests.logging.new-credentials",
                )
                logger.error("old=%s new=%s", "old-credential", "new-credential")
                for handler in logger.handlers:
                    handler.flush()

                content = (directory / "application.log").read_text(encoding="utf-8")
                self.assertNotIn("old-credential", content)
                self.assertNotIn("new-credential", content)
            finally:
                self._close_logger(logger)

    def test_credentials_are_redacted_from_messages_and_exceptions(self) -> None:
        from app.infrastructure.config.configuration import LoggingSettings
        from app.infrastructure.logging.logging_config import configure_logging

        secrets = (
            "binance-key-in-log-test",
            "binance-secret-in-log-test",
            "bitget-passphrase-in-log-test",
        )
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            settings = LoggingSettings(directory=directory, file_name="redacted.log")
            logger = configure_logging(
                settings,
                secrets,
                logger_name="tests.logging.redaction",
            )
            try:
                logger.error("credentials: %s %s", secrets[0], secrets[1])
                try:
                    raise RuntimeError(f"failed with {secrets[2]}")
                except RuntimeError:
                    logger.exception("credential failure")
                for handler in logger.handlers:
                    handler.flush()

                content = (directory / "redacted.log").read_text(encoding="utf-8")
                for secret in secrets:
                    self.assertNotIn(secret, content)
                self.assertIn("[REDACTED]", content)
            finally:
                self._close_logger(logger)

    def test_third_party_log_level_is_configurable(self) -> None:
        from app.infrastructure.config.configuration import LoggingSettings
        from app.infrastructure.logging.logging_config import configure_logging

        third_party_names = ("requests", "urllib3", "websockets", "PySide6")
        previous_levels = {
            name: logging.getLogger(name).level for name in third_party_names
        }
        with TemporaryDirectory() as temporary_directory:
            settings = LoggingSettings(
                directory=Path(temporary_directory),
                third_party_level="ERROR",
            )
            logger = configure_logging(
                settings,
                logger_name="tests.logging.third-party",
            )
            try:
                for name in third_party_names:
                    self.assertEqual(logging.getLogger(name).level, logging.ERROR)
            finally:
                self._close_logger(logger)
                for name, level in previous_levels.items():
                    logging.getLogger(name).setLevel(level)

    def test_websocket_debug_frames_never_propagate(self) -> None:
        from app.infrastructure.config.configuration import LoggingSettings
        from app.infrastructure.logging.logging_config import configure_logging

        with TemporaryDirectory() as temporary_directory:
            logger = configure_logging(
                LoggingSettings(
                    directory=Path(temporary_directory),
                    third_party_level="DEBUG",
                ),
                logger_name="tests.logging.websocket-frames",
            )
            try:
                websocket_logger = logging.getLogger("websockets.client")
                self.assertGreaterEqual(websocket_logger.getEffectiveLevel(), logging.WARNING)
                self.assertFalse(logging.getLogger("websockets").propagate)
            finally:
                self._close_logger(logger)


if __name__ == "__main__":
    unittest.main()
