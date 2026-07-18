"""Validate dependency policy, Python syntax, and UI/source contracts."""

from __future__ import annotations

import ast
import compileall
from pathlib import Path
import sys
from xml.etree import ElementTree as ET

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALLOWED_EXTERNAL = {"PySide6", "requests", "websockets"}
FORBIDDEN_TEXT = {
    "httpx", "aiohttp", "ccxt", "sqlalchemy", "aiosqlite", "pydantic",
    "orjson", "keyring", "structlog", "pytest", "pytest-qt", "ruff",
    "mypy", "pyinstaller", "hatchling",
}
EXPECTED_REQUIREMENTS = {
    "PySide6==6.11.1",
    "websockets==16.1",
    "requests==2.34.2",
}


def external_imports(path: Path) -> set[str]:
    imports: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    return {
        name for name in imports
        if name not in sys.stdlib_module_names and name != "app"
    }


def main() -> int:
    failures: list[str] = []

    requirements = {
        line.strip() for line in (PROJECT_ROOT / "requirements.txt").read_text(
            encoding="utf-8"
        ).splitlines() if line.strip() and not line.startswith("#")
    }
    if requirements != EXPECTED_REQUIREMENTS:
        failures.append(f"requirements mismatch: {sorted(requirements)}")

    for path in (PROJECT_ROOT / "app").rglob("*.py"):
        unexpected = external_imports(path) - ALLOWED_EXTERNAL
        if unexpected:
            failures.append(f"unexpected imports in {path}: {sorted(unexpected)}")

    scan_suffixes = {".py", ".toml", ".txt", ".md", ".ini"}
    exemptions = {
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT / "docs" / "technology-stack.md",
        PROJECT_ROOT / "scripts" / "check_project.py",
    }
    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in scan_suffixes or path in exemptions:
            continue
        text = path.read_text(encoding="utf-8").lower()
        found = sorted(term for term in FORBIDDEN_TEXT if term in text)
        if found:
            failures.append(f"forbidden dependency references in {path}: {found}")

    ui_path = PROJECT_ROOT / "app/ui/forms/mainwindow.ui"
    qss_path = PROJECT_ROOT / "app/ui/styles/dark.qss"
    try:
        root = ET.parse(ui_path).getroot()
    except Exception as exc:
        failures.append(f"UI XML invalid: {exc}")
    else:
        if root.find("./widget[@class='QMainWindow'][@name='MainWindow']") is None:
            failures.append("UI root isn't QMainWindow/MainWindow")
        if root.find("./widget/property[@name='styleSheet']") is not None:
            failures.append("root stylesheet isn't external")
    if not qss_path.is_file() or not qss_path.read_text(encoding="utf-8").strip():
        failures.append("dark.qss missing or empty")

    if not compileall.compile_dir(PROJECT_ROOT / "app", quiet=1):
        failures.append("Python compile check failed")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1

    print("PASS: dependency policy")
    print("PASS: source import boundary")
    print("PASS: UI/source contract")
    print("PASS: Python syntax")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
