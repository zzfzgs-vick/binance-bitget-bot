# Binance + Bitget Bot：UI 集成骨架

这是一个**仅完成 Qt Designer UI 与 Python 源码关联、不包含交易功能**的项目骨架。

## 固定技术栈

- Python `3.14.x`
- PySide6 `6.11.1`
- websockets `16.1`
- requests `2.34.2`
- Python 标准库：`asyncio`、`decimal`、`sqlite3`、`logging`、`unittest` 等

> 注意：PyPI 当前发布的是 `websockets 16.1`，不存在 `16.1.1`，因此依赖已修正为可安装的 `websockets==16.1`。

项目不直接采用其他第三方框架或 SDK：不使用 `httpx`、`aiohttp`、`CCXT`、`SQLAlchemy`、`aiosqlite`、`pydantic`、`orjson`、`keyring`、`structlog`、`pytest`、`ruff`、`mypy` 或 `PyInstaller`。

## 已完成

- `mainwindow.ui` 固定位于 `app/ui/forms/mainwindow.ui`。
- UI 与 Python 源码分离，不生成、也不维护 `ui_mainwindow.py`。
- 使用 `PySide6.QtUiTools.QUiLoader` 在运行时加载 `.ui`。
- `MainWindowView` 仅负责加载 UI、绑定控件、暴露信号和绑定表格模型。
- `MainWindowWidgets` 集中维护 `objectName` 契约并在启动时检查遗漏。
- 主窗口控件已按“套利机会 / 双腿下单 / 当前仓位 / 顶部状态”划分归属。
- 五个 `QTableView` 已绑定空只读模型及正式表头。
- QSS 独立位于 `app/ui/styles/dark.qss`。
- Binance、Bitget、行情、执行和持久化目录仅保留架构占位，不含业务功能。

## 创建环境并启动

```bash
python3.14 -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python scripts/validate_ui.py
python -m unittest discover -s tests -p "test_*.py"
python -m app.main
```

## UI 维护规则

1. 仅使用 Qt Designer 修改 `app/ui/forms/mainwindow.ui`。
2. `objectName` 是 UI 与源码的稳定契约；修改时同步更新 `MainWindowWidgets` 与测试。
3. 布局、控件和静态文本放在 `.ui`；主题放在 `.qss`。
4. View 不得直接访问 Binance、Bitget、行情、数据库或执行模块。
5. Presenter 负责界面编排，但当前不实现交易功能。
6. 领域层不得导入 PySide6、requests 或 websockets。
7. 后续 HTTP 直接使用 `requests`；WebSocket 直接使用 `websockets`，不增加封装型网络依赖。
