import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


class ApplicationConfigurationIntegrationTests(unittest.TestCase):
    def test_composition_root_loads_configuration_credentials_and_logging(self) -> None:
        from app.bootstrap import build_application

        app = QApplication.instance() or QApplication([])
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config_path = root / "settings.toml"
            log_directory = root / "logs"
            config_path.write_text("", encoding="utf-8")
            environment = {
                "APP_LOG_DIRECTORY": str(log_directory),
                "BINANCE_API_KEY": "integration-binance-key",
                "BINANCE_API_SECRET": "integration-binance-secret",
                "BITGET_API_KEY": "integration-bitget-key",
                "BITGET_API_SECRET": "integration-bitget-secret",
                "BITGET_API_PASSPHRASE": "integration-bitget-passphrase",
            }

            runtime = build_application(config_path=config_path, environ=environment)
            try:
                self.assertEqual(runtime.configuration.application.mode, "live")
                self.assertTrue(runtime.credentials.is_complete())
                self.assertEqual(len(runtime.logger.handlers), 2)
                self.assertTrue((log_directory / "application.log").is_file())
                self.assertEqual(len(runtime.trading_clients), 4)
                self.assertFalse(runtime.execution_worker.is_shutdown)
                self.assertIsNotNone(runtime.live_events)
            finally:
                runtime.shutdown()
                runtime.shutdown()
                app.processEvents()

            self.assertEqual(runtime.logger.handlers, [])
            self.assertTrue(runtime.execution_worker.is_shutdown)


if __name__ == "__main__":
    unittest.main()
