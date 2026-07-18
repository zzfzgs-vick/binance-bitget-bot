"""Resource path resolution for development and frozen executables."""

from __future__ import annotations

from pathlib import Path
import sys


def package_root() -> Path:
    """Return the root containing the installed `app` package."""
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        candidate = Path(frozen_root) / "app"
        if candidate.exists():
            return candidate
    return Path(__file__).resolve().parents[2]


def ui_form_path(filename: str) -> Path:
    """Return an absolute path to one Qt Designer form."""
    return package_root() / "ui" / "forms" / filename


def ui_style_path(filename: str) -> Path:
    """Return an absolute path to one QSS file."""
    return package_root() / "ui" / "styles" / filename


def live_config_path() -> Path:
    """Return the fixed LIVE configuration file path."""
    return package_root().parent / "config" / "live.toml"
