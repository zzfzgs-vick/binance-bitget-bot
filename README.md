# Binance + Bitget LIVE 套利桌面应用

这是一个 LIVE-only 桌面应用，已具备 Qt Designer UI 关联、配置与凭据、Binance/Bitget REST 和 WebSocket 适配、交易规则、实时行情、套利计算、账户同步、双腿订单执行、成交对账、套利仓位及手动双腿平仓能力。启动时先显示真实空状态并连接正式数据源，但不会自动下单或生成虚假业务数据，也不提供模拟盘、测试网或 Demo Trading。

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
- Binance 现货和 USDⓈ-M REST 客户端支持生产环境公共/私有请求、HMAC 签名、服务器时间和原始产品信息。
- Bitget REST 客户端支持生产环境公共/私有请求、HMAC 签名、服务器时间和原始产品信息。
- Binance 与 Bitget WebSocket 客户端在后台线程的独立 `asyncio` 事件循环运行，支持公共订阅、取消订阅、心跳、有限重连和订阅恢复。
- Bitget 私有入口支持登录确认；Binance 现货私有入口校验签名订阅确认，USDⓈ-M 私有入口创建、续期、重建并关闭 listen key。
- Binance、Bitget 现货与 USDT 永续产品信息可归一化为统一的 `Instrument` 和 `TradingRules`；所有交易规则数值均为 `Decimal`。
- 跨交易所匹配依据 base、quote、结算资产及市场语义，不依赖原始 symbol 拼写；价格与数量按官方步长集中向下量化。
- Binance 与 Bitget 的现货/USDT 永续 ticker、最优买卖价、深度和永续资金费率可转换为统一 Decimal 事件。
- 本地订单簿按官方更新序列处理快照和增量，支持零量删除、排序、限深、重复/乱序忽略以及缺口后重新同步。
- 套利计算支持双交易所方向及现货/USDT 永续组合，按订单簿逐档计算成交均价、滑点、手续费、利润和 ROI。
- 账户余额、账户持仓、套利机会和套利仓位通过现有 Presenter、Qt Signal 与只读表格模型接入 GUI。
- 正式双腿开仓采用“准备 LIVE 下单 → 明确确认开仓”两步操作；不存在自动开仓路径。
- 套利仓位只根据两腿实际成交创建，记录成交均价、数量、手续费、开仓时间、剩余数量和盈亏。
- 手动平仓从实际剩余仓位生成反向订单，复用交易规则量化、幂等客户端订单号及 REST/WebSocket 对账。
- 一条腿已关闭而另一条腿失败时，后续手动重试只提交仍有实际余量的交易腿。
- 客户端订单号、未知订单和双腿执行上下文写入本地恢复日志；重启时先查询原订单，再恢复原状态机，不会盲目重复创建订单。
- Composition Root 由 `ApplicationRuntime` 统一启动产品、账户、公共/私有 WebSocket、订单簿、机会计算和 GUI 事件链；具体交易对行情仍由用户输入后订阅。
- 阻塞式 REST 下单在专用后台线程池中执行，后台结果只通过 Qt Signal 返回 GUI。
- Composition Root 创建四个正式生产交易适配器；启动会连接正式数据源，但不会自动发送订单。

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
5. Presenter 只负责界面编排；交易执行通过后台 Worker 调用应用与执行模块。
6. 领域层不得导入 PySide6、requests 或 websockets。
7. HTTP 直接使用 `requests`；WebSocket 直接使用 `websockets`，不增加封装型网络依赖。
8. `paperModeButton` 与 `paperOrderButton` 仅是遗留 objectName；界面与 Python 语义始终为 LIVE，不存在模式切换。
