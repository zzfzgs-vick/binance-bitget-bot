"""PySide6 application entry point."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.bootstrap import build_application


def main() -> int:
    """Start the UI-only desktop application."""
    qt_app = QApplication.instance() or QApplication(sys.argv)
    qt_app.setApplicationName("Binance + Bitget 套利终端")
    qt_app.setOrganizationName("Arbitrage Terminal")

    runtime = None
    try:
        runtime = build_application()
        runtime.main_window.show()
        return qt_app.exec()
    finally:
        if runtime is not None:
            runtime.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
