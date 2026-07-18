"""Validate dependency policy, Python syntax, and UI/source contracts."""

from __future__ import annotations

import ast
import compileall
from pathlib import Path
import sys
import tomllib
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
EXPECTED_PYTHON = ">=3.14,<3.15"
FORBIDDEN_RUNTIME_PATHS = {
    ".env.example",
    "app/paper",
    "app/ui/styles/paper_mode.qss",
    "config/default.toml",
    "config/development.toml",
    "config/paper.toml",
    "scripts/reset_paper_database.py",
    "scripts/run_paper.py",
}
LIVE_ONLY_TERMS = {"paper", "testnet", "demo", "sandbox"}
LEGACY_UI_NAMES = {"papermodebutton", "paperorderbutton"}
VIEW_FORBIDDEN_IMPORTS = {
    "app.exchanges",
    "app.execution",
    "app.market_data",
    "app.persistence",
    "app.infrastructure.network",
    "sqlite3",
    "tomllib",
}
DOMAIN_FORBIDDEN_IMPORTS = {"PySide6", "requests", "websockets"}


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

    with (PROJECT_ROOT / "pyproject.toml").open("rb") as pyproject_file:
        project = tomllib.load(pyproject_file)["project"]
    if project.get("requires-python") != EXPECTED_PYTHON:
        failures.append(f"Python constraint mismatch: {project.get('requires-python')}")
    if set(project.get("dependencies", ())) != EXPECTED_REQUIREMENTS:
        failures.append(f"pyproject dependency mismatch: {project.get('dependencies')}")

    requirements = {
        line.strip() for line in (PROJECT_ROOT / "requirements.txt").read_text(
            encoding="utf-8"
        ).splitlines() if line.strip() and not line.startswith("#")
    }
    if requirements != EXPECTED_REQUIREMENTS:
        failures.append(f"requirements mismatch: {sorted(requirements)}")

    for relative_path in FORBIDDEN_RUNTIME_PATHS:
        if (PROJECT_ROOT / relative_path).exists():
            failures.append(f"forbidden runtime path exists: {relative_path}")

    for path in (PROJECT_ROOT / "app").rglob("*.py"):
        unexpected = external_imports(path) - ALLOWED_EXTERNAL
        if unexpected:
            failures.append(f"unexpected imports in {path}: {sorted(unexpected)}")

    for path in (PROJECT_ROOT / "app" / "ui" / "views").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        found = sorted(item for item in VIEW_FORBIDDEN_IMPORTS if item in source)
        if found:
            failures.append(f"view boundary violation in {path}: {found}")

    for path in (PROJECT_ROOT / "app" / "domain").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        found = sorted(item for item in DOMAIN_FORBIDDEN_IMPORTS if item in source)
        if found:
            failures.append(f"domain boundary violation in {path}: {found}")

    runtime_suffixes = {".py", ".qss", ".toml", ".ui"}
    for directory in ("app", "config", "scripts"):
        for path in (PROJECT_ROOT / directory).rglob("*"):
            if not path.is_file() or path.suffix.lower() not in runtime_suffixes:
                continue
            if path == PROJECT_ROOT / "scripts" / "check_project.py":
                continue
            text = path.read_text(encoding="utf-8").lower()
            for legacy_name in LEGACY_UI_NAMES:
                text = text.replace(legacy_name, "")
            found = sorted(term for term in LIVE_ONLY_TERMS if term in text)
            if found:
                failures.append(f"non-LIVE runtime text in {path}: {found}")

    scan_suffixes = {".py", ".toml", ".txt", ".md", ".ini"}
    exemptions = {
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT / "docs" / "technology-stack.md",
        PROJECT_ROOT / "scripts" / "check_project.py",
    }
    for path in PROJECT_ROOT.rglob("*"):
        if (
            not path.is_file()
            or path.suffix.lower() not in scan_suffixes
            or path in exemptions
            or "venv" in path.parts
            or ".git" in path.parts
        ):
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
