"""Runtime loader for Qt Designer `.ui` files."""

from __future__ import annotations

from pathlib import Path
from typing import TypeVar, cast

from PySide6.QtCore import QFile
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QWidget

TWidget = TypeVar("TWidget", bound=QWidget)


class UiLoadError(RuntimeError):
    """Raised when a Qt Designer file cannot be loaded safely."""


def load_ui(ui_path: Path, parent: QWidget | None = None) -> QWidget:
    """Load a `.ui` file and return its root widget."""
    resolved_path = ui_path.expanduser().resolve()
    if not resolved_path.is_file():
        raise UiLoadError(f"UI 文件不存在: {resolved_path}")

    ui_file = QFile(str(resolved_path))
    if not ui_file.open(QFile.OpenModeFlag.ReadOnly):
        raise UiLoadError(f"无法打开 UI 文件: {resolved_path}")

    loader = QUiLoader()
    try:
        widget = loader.load(ui_file, parent)
    finally:
        ui_file.close()

    if widget is None:
        detail = loader.errorString() or "未知错误"
        raise UiLoadError(f"加载 UI 文件失败: {resolved_path}; {detail}")

    return widget


def load_typed_ui(
    ui_path: Path,
    expected_type: type[TWidget],
    parent: QWidget | None = None,
) -> TWidget:
    """Load a `.ui` file and verify its root widget type."""
    widget = load_ui(ui_path, parent)
    if not isinstance(widget, expected_type):
        widget.deleteLater()
        raise UiLoadError(
            f"UI 根控件类型错误: {ui_path.expanduser().resolve()}; "
            f"期望 {expected_type.__name__}, 实际 {type(widget).__name__}"
        )
    return cast(TWidget, widget)
