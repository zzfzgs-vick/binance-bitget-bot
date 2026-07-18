# Binance + Bitget Bot：UI 集成骨架

这是一个 LIVE-only 桌面应用骨架，已完成 Qt Designer UI 关联、非敏感配置、日志和内存 API 凭据加载，尚未实现交易功能。启动时只显示真实空状态，不提供模拟盘、测试网或 Demo Trading。

## 固定技术栈

- Python `>=3.14,<3.15`
- PySide6 `6.11.1`
- websockets `16.1`
- requests `2.34.2`
- Python 标准库：`asyncio`、`decimal`、`sqlite3`、`logging`、`unittest` 等

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
- `config/live.toml` 只保存非敏感 LIVE 与日志设置，并支持环境变量覆盖。
- API 凭据只从进程环境变量读取并保存在内存中，日志输出会脱敏。
- Binance、Bitget、行情、执行和持久化目录仅保留架构占位，不含业务功能。

## 配置与凭据

日志配置项为 `level`、`third_party_level`、`directory`、`file_name`、`max_bytes` 和 `backup_count`。对应环境变量覆盖为：

```text
APP_LOG_LEVEL
APP_THIRD_PARTY_LOG_LEVEL
APP_LOG_DIRECTORY
APP_LOG_FILE
APP_LOG_MAX_BYTES
APP_LOG_BACKUP_COUNT
```

API 凭据只读取以下环境变量，不得写入 TOML：

```text
BINANCE_API_KEY
BINANCE_API_SECRET
BITGET_API_KEY
BITGET_API_SECRET
BITGET_API_PASSPHRASE
```

## 创建环境并启动

```text
# Windows：仅首次创建根目录虚拟环境
py -3.14 -m venv venv

.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe scripts\validate_ui.py
.\venv\Scripts\python.exe scripts\check_project.py
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\venv\Scripts\python.exe -m app.main
```

## UI 维护规则

1. 仅使用 Qt Designer 修改 `app/ui/forms/mainwindow.ui`。
2. `objectName` 是 UI 与源码的稳定契约；修改时同步更新 `MainWindowWidgets` 与测试。
3. 布局、控件和静态文本放在 `.ui`；主题放在 `.qss`。
4. View 不得直接访问 Binance、Bitget、行情、数据库或执行模块。
5. Presenter 负责界面编排，但当前不实现交易功能。
6. 领域层不得导入 PySide6、requests 或 websockets。
7. 后续 HTTP 直接使用 `requests`；WebSocket 直接使用 `websockets`，不增加封装型网络依赖。
8. `paperModeButton` 与 `paperOrderButton` 仅是遗留 objectName；界面与 Python 语义始终为 LIVE，不存在模式切换。
