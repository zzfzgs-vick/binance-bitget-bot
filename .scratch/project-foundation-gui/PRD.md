# 阶段 1 PRD：项目基础与 GUI 关联

## 文档元数据

- **Status:** `ready-for-agent`
- **阶段：** 1 / 10——项目基础与 GUI 关联
- **Issue tracker：** Local Markdown
- **实施前 Git 基线：** `cf1e1a4`
- **基线完整提交：** `cf1e1a414ff58f7f6b0e2abb360f262771b18c9b`
- **PRD 路径：** `.scratch/project-foundation-gui/PRD.md`
- **文档日期：** 2026-07-18
- **适用约束：** 根目录 `AGENTS.md`、`CONTEXT.md` 以及 ADR-0001 至 ADR-0004
- **官方 API 参考：** 本阶段不实现交易所接口，因此不读取 Binance、Bitget 官方 API 参考仓库

实施代理开始工作前，必须确认 `git rev-parse --short HEAD` 为 `cf1e1a4`。允许工作区已有本 PRD；若还存在其他未说明变更，必须先报告，不得把不明变更混入阶段 1。

## 背景

项目目标是使用 PySide6 构建连接 Binance 与 Bitget 正式生产环境的套利桌面应用。仓库已经包含完整的目录骨架、Qt Designer 主窗口、运行时 UI 加载器、集中控件注册、View、主 Presenter、五个表格模型和一组 UI 测试，因此阶段 1 不是从空仓库重新设计架构。

当前骨架同时保留了大量演示数据和模拟交易遗留内容：主窗口显示虚构余额、价格、仓位、盈亏和连接状态；生产源码中存在 `app/paper/`；配置、脚本和样式中存在 PAPER 模式；View 和控件注册使用 PAPER 语义。它们与 `AGENTS.md`、`CONTEXT.md` 和 ADR-0002 的 LIVE-only 决策冲突。

阶段 1 的问题是：在不改变现有 GUI 布局和 UI 契约的前提下，把现有骨架收敛为可启动、可验证、生命周期明确、只表达 LIVE 正式环境且不伪造业务状态的 GUI 基础，为后续阶段接入真实领域与交易所功能提供单一基础。

## 当前仓库状态

### Git 与路径状态

- 当前 `HEAD` 为固定基线 `cf1e1a4`。
- 编写本 PRD前工作区干净。
- 用户指定的所有必查文件和目录都实际存在；没有需要以“路径缺失”记录的项目。
- 仓库已经包含 330 个受 Git 跟踪的文件，不是空仓库。
- 根目录虚拟环境 `venv/` 存在并被 `.gitignore` 排除。

### 项目与依赖状态

- `pyproject.toml` 已精确声明 `PySide6==6.11.1`、`requests==2.34.2`、`websockets==16.1`，但 Python 约束写成 `==3.14.*`，未使用项目要求的规范文本 `>=3.14,<3.15`。
- `requirements.txt` 已且仅包含三项允许的直接依赖，并已精确锁定正确版本。
- `README.md` 将项目描述为 UI 集成骨架，但创建环境和执行命令使用 `.venv/`、激活脚本和全局 `python`，与根目录 `venv/` 约束冲突。
- `.gitignore` 已排除 `venv/`、`.venv/`、`env/`、`.env`、运行数据和日志；本阶段直接复用，不需要修改。

### 启动与 Composition Root 状态

- `app.main` 已提供 `main()`，创建或复用 `QApplication`，调用 `build_application()`，显示窗口，并在事件循环退出后调用 `runtime.shutdown()`。
- `app.bootstrap` 已是最小 Composition Root：创建 `MainWindowView`、创建 `MainWindowPresenter`、调用 `bind()` 并返回 `ApplicationRuntime`；没有创建交易所或业务服务。
- `app.container.ApplicationRuntime` 已持有 View 与 Presenter，但 `shutdown()` 只有一次 `close()`，没有显式幂等状态和完整 Qt 对象清理语义。
- `scripts/run_dev.py` 与 `scripts/run_live.py` 都直接调用 `app.main.main`；规范启动入口仍应是 `python -m app.main`。

### UI 加载与控件契约状态

- `app/ui/forms/mainwindow.ui` 实际存在，根控件为 `QMainWindow`，`objectName` 为 `MainWindow`。
- `.ui` 中共有 171 个 widget。
- 三个现有 `QSplitter` 为：
  - `mainVerticalSplitter`：`Qt::Vertical`
  - `tradingHorizontalSplitter`：`Qt::Horizontal`
  - `positionHorizontalSplitter`：`Qt::Horizontal`
- `app.ui.loader.ui_loader` 已直接使用 `QUiLoader`，能报告文件不存在、文件无法打开、加载失败和根控件类型错误。
- `app.ui.loader.widget_registry.MainWindowWidgets` 已集中绑定布局、筛选、双腿订单、五个表格、顶部按钮和状态标签，并通过 `required_child()` 同时校验 objectName 与 Qt 类型。
- `paperModeButton`、`paperOrderButton` 确实存在于 `.ui`，属于必须保留的遗留 objectName 契约。

### View、Presenter 与 Model 状态

- `MainWindowView` 已保持为薄边界：运行时加载 UI、集中绑定控件、加载外部 `dark.qss`、暴露 Signal、连接控件并提供五个 Model 绑定方法。
- View 当前暴露 `paper_order_requested` 和 `mode_change_requested`，控件字段使用 `paper_order_button`、`paper_mode_button`，与 LIVE-only 语义冲突。
- `MainWindowPresenter` 已创建五个空模型并绑定到五个 `QTableView`，但每次调用 `bind()` 都会再次连接机会表选择信号，存在重复 Signal 连接风险。
- `ReadOnlyTableModel` 已实现 `rowCount`、`columnCount`、`data` 和 `headerData`，并由五个具体表格模型复用正式表头。
- `ReadOnlyTableModel` 尚未显式实现只读 `flags()`、安全的全量行替换、`beginResetModel()/endResetModel()` 和行列数量校验。
- `account_presenter.py`、`connection_presenter.py`、`opportunity_presenter.py`、`order_entry_presenter.py`、`position_presenter.py` 目前只是占位文件；本阶段不把它们连接到不存在的业务服务。
- `OpportunityFilterProxyModel` 目前只是无自定义行为的占位；筛选业务留到后续阶段。

### 当前显示状态

主窗口不是准确的空状态，而是展示了完整的虚构业务场景，包括但不限于：

- Binance 与 Bitget 的四组虚构 USDT 余额。
- `ETHUSDT` 套利机会、现货/永续价格、深度、手续费和资金费。
- 虚构投入金额、数量、杠杆、保证金、价差、收益和 ROI。
- 虚构套利仓位 `ARB001`、两条交易腿、累计资金费和净盈亏。
- 虚构连接状态、WebSocket 延迟、更新时间和“系统就绪”。
- `paperModeButton` 的可见文本为 `PAPER ▾`。
- `paperOrderButton` 的可见文本为 `模拟下单`。
- 未实现的刷新、下单和其他业务按钮默认可用。

五个表格模型本身当前为空，但周边标签和输入控件仍使用户误以为已有真实业务数据。

### 测试与验证状态

- 现有可执行 UI 测试共 7 项，覆盖根 UI XML、外部 QSS、offscreen 运行时加载、必需 objectName、五个表格绑定、View 导入边界和 Domain 第三方依赖边界。
- `tests/fault_injection/` 和 `tests/replay/` 下的文件当前只是未来阶段占位，不提供阶段 1 验收价值。
- `scripts/validate_ui.py` 已检查 XML、根控件、部分 objectName、外部 QSS 和可选运行时加载，但尚未验证完整结构不变量、空状态、LIVE 可见语义或控件禁用状态。
- `scripts/check_project.py` 已检查依赖集合、源码外部导入、部分禁用依赖文本、UI 根控件、外部 QSS 和 Python 语法，但尚未检查 Python 约束规范文本或 LIVE-only 生产路径。

## 已有实现清单

### 1. 已存在且应直接复用

| 能力 | 当前实现 | 处理原则 |
| --- | --- | --- |
| Qt Designer 主窗口 | `mainwindow.ui`、171 个 widget、三个既定 QSplitter | 保留布局、层级、位置、objectName 和 QSplitter 契约，只改允许的显示属性 |
| 运行时 UI 加载 | `load_ui()`、`load_typed_ui()`、`UiLoadError` | 直接复用，只补测试覆盖，不生成 `ui_mainwindow.py` |
| 资源路径解析 | UI/QSS 路径辅助函数 | 直接复用，不新增资源框架 |
| 集中控件绑定 | `MainWindowWidgets.bind()`、`required_child()` | 复用绑定机制，清除 Python 侧 PAPER 字段命名 |
| View 边界 | `MainWindowView` | 在现有类上收敛 Signal、空状态和生命周期，不创建平行 View |
| Composition Root | `build_application()` | 作为最高层测试接缝和最小对象图入口直接复用 |
| 五个表格模型 | 机会、仓位、执行中订单、订单历史、资金费历史模型 | 保留现有表头和继承结构，增强共同基类 |
| 主 Presenter | `MainWindowPresenter` | 在现有 Presenter 上实现幂等绑定和初始空状态，不创建新编排层 |
| 基础 UI 测试 | `tests/ui/` 现有测试 | 扩展现有测试，不改用其他测试框架 |
| 主样式 | `dark.qss` | 视觉规则保持不变；遗留 objectName 选择器可以保留 |
| 依赖清单 | `requirements.txt` | 已符合精确依赖约束，保持不变 |
| 忽略规则 | `.gitignore` | 已正确忽略根目录虚拟环境和运行产物，保持不变 |

### 2. 已存在但违反约束，需要修正

- Python 约束规范文本。
- README 中 `.venv/`、激活式和全局 Python 命令。
- `mainwindow.ui` 中 PAPER 可见文本、虚构业务数据和未实现操作的启用状态。
- View、控件注册中的 PAPER Python 命名和“模式切换”Signal。
- Presenter 的重复 Signal 连接。
- Runtime shutdown 缺少明确幂等语义。
- 基础表格模型缺少只读 flags、原子行替换和列宽校验。
- 生产源码、配置、脚本、样式和环境示例中的 PAPER 内容。
- 验证脚本缺少阶段 1 的 Python 约束、空状态、LIVE-only 和结构不变量检查。
- UI 架构、控件归属、开发指南和项目树文档中的旧语义或旧命令。

### 3. 本阶段缺少且必须新增

- 针对控件缺失和 Qt 类型错误的明确失败测试。
- 基础表格模型的只读 flags、完整行替换、reset 信号和列数校验测试。
- 由实际控件操作触发 View Signal 的 offscreen 测试。
- Presenter `bind()` 重复调用不重复连接的测试。
- Composition Root 构建、五表绑定、准确空状态和重复 shutdown 的集成测试。
- LIVE-only 文件与运行路径静态验证。
- 对 UI 结构签名、全部 objectName 集合和三个 QSplitter 契约的回归验证。

### 4. 明确保留到后续阶段

- 占位的账户、连接、机会、双腿下单和仓位 Presenter，不在本阶段接入业务。
- 机会筛选代理模型的真实筛选逻辑。
- Domain、交易所、行情、执行、持久化、Worker 和策略目录中的后续阶段能力；本阶段不得为其补业务实现。
- fault-injection、replay 和交易所 integration 测试占位；不把它们伪装成本阶段已完成测试。
- 固定 LIVE 配置文件可以保留为后续配置阶段的输入，但本阶段不实现配置加载或模式选择。

### 5. 应在本阶段删除的模拟交易生产内容

- `app/paper/` 生产包及其中全部占位模块。
- `config/paper.toml`。
- `config/development.toml`，因为它当前唯一语义是 `mode = "paper"`。
- `config/default.toml`，因为它同时声明 PAPER 模式并提供尚未确定的虚构策略、执行和数据库默认值，且当前没有运行时代码读取它。
- `scripts/run_paper.py`。
- `scripts/reset_paper_database.py`。
- `app/ui/styles/paper_mode.qss`。
- `.env.example`，因为其唯一环境模式声明是 `APP_MODE=paper`，而本阶段不实现环境配置或凭据管理。

## 现有约束冲突清单

| 编号 | 现状 | 违反的约束 | 阶段 1 处理 |
| --- | --- | --- | --- |
| C-01 | `app/paper/` 可作为生产包导入 | 禁止运行时模拟交易所、虚拟余额、虚拟仓位和虚拟成交 | 删除整个包并验证不存在生产导入 |
| C-02 | PAPER 配置、启动和重置脚本存在 | 禁止实盘/模拟盘切换与模拟运行入口 | 删除 PAPER 配置和脚本；不提供替代模拟入口 |
| C-03 | `.env.example`、默认配置和开发配置声明 PAPER | LIVE-only；不得保留运行模式选择 | 删除未使用且误导性的文件；保留固定 LIVE 文件但不实现选择器 |
| C-04 | `paper_mode.qss` 和 PAPER 可见文本存在 | GUI 必须明确表达 LIVE 正式环境 | 删除 PAPER 样式；可见文本改为 LIVE，遗留 objectName 保留 |
| C-05 | View Signal、字段和模式切换语义使用 `paper_*` | Python 名称应使用 `live_*` 或中性语义，生产代码不得切换模式 | Python 属性和 Signal 改为 LIVE/中性命名，删除模式切换行为 |
| C-06 | UI 显示虚构余额、价格、费用、仓位、盈亏和状态 | 无真实业务数据时必须显示准确空状态 | 清空业务值，使用 `—`、`未连接`、`暂无数据` 等不冒充真实数据的文本 |
| C-07 | 未实现业务按钮默认可用 | 当前阶段不实现刷新、账户或下单业务 | 保留位置和 objectName，设置 disabled，并用 tooltip 说明尚未接入 |
| C-08 | Presenter `bind()` 可重复连接选择 Signal | 重复绑定会使一次操作触发多次 | 使 `bind()` 幂等，并以 Signal 计数测试证明 |
| C-09 | shutdown 无显式重复调用保护 | 阶段目标要求可重复调用且 Qt 生命周期明确 | 增加幂等状态和安全 close/deleteLater 流程 |
| C-10 | 表格模型缺少显式只读 flags、reset 和列数验证 | Model 最低接口要求未满足 | 在共同基类集中实现并覆盖五个模型 |
| C-11 | `pyproject.toml` 使用 `==3.14.*` | 项目要求规范文本 `>=3.14,<3.15` | 修改 requires-python，依赖版本保持不变 |
| C-12 | README 使用 `.venv` 和全局 Python | 虚拟环境必须为根目录 `venv/` | 所有 Windows 命令改用固定解释器绝对相对路径 |
| C-13 | 验证脚本只验证部分 UI 契约和依赖 | 17 项验收不能被当前脚本完整证明 | 扩展现有脚本和 unittest，不增加工具或框架 |

## 目标

1. 保留并收敛现有项目启动入口和最小 Composition Root。
2. 继续通过 `QUiLoader` 运行时加载 `mainwindow.ui`。
3. 集中完成 UI 控件绑定、存在性校验和 Qt 类型校验。
4. 完成 View、Presenter 和五个 `QAbstractTableModel` 的基础关联。
5. 将 GUI 用户操作暴露为 Qt Signal，不在 View 中执行业务。
6. 在没有真实业务数据时显示准确、无歧义的空状态。
7. 明确 Qt 对象所有权，并使 shutdown 可安全重复调用。
8. 使用 `unittest`/`unittest.mock` 完成本阶段自动化测试。
9. 修正本阶段直接相关的 README、UI 架构、控件归属、开发指南和项目树文档。
10. 清除生产运行路径中的 PAPER、TESTNET、DEMO、SANDBOX 和模拟交易实现或入口。

## 非目标

本阶段不得实现或提前设计：

- API 凭据管理。
- 完整配置系统或环境切换器。
- 日志业务功能。
- Binance REST 或 Bitget REST。
- Binance WebSocket 或 Bitget WebSocket。
- 交易对匹配。
- 交易规则归一化。
- 行情、深度或资金费率接入。
- 手续费、滑点、价差、利润或 ROI 计算。
- 账户、余额、保证金或仓位同步。
- 下单、撤单、订单查询或成交对账。
- 套利仓位建立、跟踪或平仓。
- 数据库业务功能或迁移。
- 任何业务风控、止损、止盈、仓位上限、自动停止或风险评分。
- 通用 Worker 框架。
- 通用异步任务框架。
- 插件系统。
- 依赖注入框架。
- 未经批准的第三方依赖。
- pandas 或其他第三方数据模型。
- Binance 或 Bitget SDK、CLI、Skill、代理运行时或中间工具。
- 任何交易策略、交易对、阈值或业务触发规则。

## 用户或维护者可观察行为

1. 作为维护者，我希望使用根目录 `venv` 中的 Python 运行应用，以便开发命令与仓库约束一致。
2. 作为维护者，我希望 `python -m app.main` 成为可用的标准启动方式，以便不依赖额外启动器。
3. 作为用户，我希望主窗口保持现有布局和视觉结构，以便阶段 1 不造成 GUI 重设计。
4. 作为用户，我希望窗口明确显示 LIVE 正式环境语义，以免误以为应用支持模拟盘。
5. 作为用户，我希望未接入真实业务数据时看到 `—`、`暂无数据` 或 `未连接`，而不是虚构余额、价格或盈亏。
6. 作为用户，我希望尚未实现的刷新和下单操作处于 disabled 状态，并能从 tooltip 得知尚未接入。
7. 作为维护者，我希望 `.ui` 缺失、无法加载或根类型错误时得到包含路径、期望类型和实际类型的清晰异常。
8. 作为维护者，我希望必需控件缺失或类型错误时立即失败并指出 objectName 与期望 Qt 类型。
9. 作为维护者，我希望所有 Python 侧控件引用集中在一个注册对象中，以便 objectName 契约可统一审查。
10. 作为维护者，我希望 View 只暴露 Qt Signal 和显示方法，以便未来 Presenter 编排不会把业务逻辑推入 View。
11. 作为维护者，我希望五个表格在启动后都绑定正确模型，以便后续阶段只需提供真实行数据。
12. 作为维护者，我希望模型能原子替换全部行并拒绝列数错误的数据，以免 GUI 得到结构不一致的行。
13. 作为维护者，我希望模型默认不可编辑，以免 UI 骨架意外修改展示数据。
14. 作为维护者，我希望 Presenter 重复调用 `bind()` 不会重复连接 Signal，以便重入或测试不会放大用户操作。
15. 作为维护者，我希望实际控件操作能够触发且只触发一次对应 View Signal，以便后续编排拥有稳定输入边界。
16. 作为维护者，我希望 Composition Root 返回的运行时对象持有所有 Qt 对象，并允许 shutdown 重复调用，以便退出和异常路径一致。
17. 作为审查者，我希望自动验证 View 不导入交易所、行情或执行实现，Domain 不依赖 GUI/网络库，以便架构边界不退化。
18. 作为审查者，我希望自动验证生产运行路径不存在可执行 PAPER/TESTNET/DEMO/SANDBOX 模式，以便 LIVE-only 决策可以持续执行。
19. 作为维护者，我希望相关文档与实际启动命令、控件归属和遗留 objectName 说明一致，以便后续阶段不重复发现同一冲突。

## 功能需求

### FR-01：实施基线与范围保护

- 实施必须从提交 `cf1e1a4` 开始。
- 实施前若存在本 PRD 之外的未说明改动，必须先报告。
- 不得生成 `ui_mainwindow.py`，不得新增第三方依赖，不得创建新的虚拟环境目录。

### FR-02：启动入口与 Composition Root

- `python -m app.main` 必须创建或复用一个 `QApplication`，构建一次应用对象图，显示主窗口并进入 Qt 事件循环。
- 现有 `build_application()` 是唯一 Composition Root；本阶段只组装 View、Presenter 和表格模型相关对象。
- Composition Root 不得构造交易所、行情、账户、执行、数据库、Worker 或配置服务。
- 若构建、显示或事件循环退出路径发生异常，已创建的运行时对象仍必须进入安全 shutdown。

### FR-03：运行时 UI 加载

- 必须继续使用 `QUiLoader` 从 `mainwindow.ui` 运行时加载根窗口。
- UI 文件不存在、无法打开、加载器返回空对象或根控件不是 `QMainWindow` 时必须抛出清晰异常。
- 异常消息必须包含足以定位问题的文件路径；类型错误必须包含期望与实际类型。
- 不得用 Python 代码复制或重建 `.ui` 布局。

### FR-04：集中控件绑定

- 所有阶段 1 直接使用的控件必须继续由单一 `MainWindowWidgets` 注册对象按 objectName 绑定。
- 绑定必须同时验证控件存在和 Qt 类型；失败信息必须包含 objectName 与期望类型。
- 遗留 objectName `paperModeButton`、`paperOrderButton` 必须按原字符串查找，但 Python 字段改为 `live_mode_button`、`live_order_button` 或等价中性名称。
- 不得在 View、Presenter 或其他模块散落重复的 `findChild()` 调用。

### FR-05：View 行为

- View 只能加载 UI、绑定控件、应用既有样式、暴露 Signal、设置显示状态和绑定 Qt Model。
- 用户可操作输入应通过明确 Qt Signal 暴露；至少一个测试必须通过实际控件操作触发对应 Signal，而不是直接调用 Signal 的 `emit()`。
- PAPER Signal/方法命名必须删除或改为 LIVE/中性命名；不得保留“模式切换”能力。
- View 必须提供集中设置初始空状态的方法，且该方法可安全重复调用。
- View 不得导入或调用交易所、行情、执行、持久化、配置或数据库实现。

### FR-06：Presenter 行为

- 主 Presenter 负责绑定五个模型、连接 View Signal 和设置初始界面状态。
- `bind()` 必须幂等；同一 Presenter 调用两次或更多次时，每个用户操作仍只产生一次上层 Signal/处理调用。
- Presenter 不得调用不存在的业务服务，不得创建虚构 DTO 或填充假业务数据。
- 当前阶段只使用主 Presenter；其他占位 Presenter 不接入对象图。

### FR-07：表格模型

- 继续使用现有 `QAbstractTableModel` 共同基类和五个具体表格模型。
- 共同基类必须正确实现 `rowCount`、`columnCount`、`data`、`headerData` 和默认只读 `flags`。
- 无效 parent、index、row、column 或非显示 role 必须安全返回 Qt 约定值，不得抛出索引异常。
- 提供安全替换全部行的方法；替换必须先验证每行列数与表头列数一致。
- 列数错误必须抛出包含期望列数、实际列数和出错行索引的清晰异常，且原有行数据保持不变。
- 合法替换必须以 `beginResetModel()`/`endResetModel()` 包围，并使 View 立即看到新的行数和数据。
- 不得引入第三方数据模型。

### FR-08：准确空状态

- 启动时五个表格均为零行。
- 所有余额、价格、数量、资金费率、费用、价差、滑点、保证金、盈亏、收益率、仓位和订单示例值必须清除。
- 空状态不得用数值 `0` 冒充真实查询结果；优先使用 `—`、`暂无数据`、`未连接`、`尚未选择套利机会` 等明确文本。
- 四个交易所连接状态必须显示未连接；不得显示虚构延迟、更新时间或“系统就绪”。
- 未实现的业务输入和操作按钮必须 disabled；tooltip 必须说明该能力将在后续阶段接入。
- `paperModeButton` 可见文本必须改为明确的 `LIVE`/`正式实盘` 语义，不得带可切换下拉含义。
- `paperOrderButton` 可见文本必须改为 LIVE 实盘语义并保持 disabled；不得执行或暗示模拟下单。

### FR-09：Qt 生命周期与 shutdown

- `ApplicationRuntime` 必须明确持有主窗口和 Presenter，使其在 Qt 事件循环期间不会被回收。
- `shutdown()` 第一次调用时关闭主窗口并安排适当的 Qt 对象清理；后续调用不得抛异常、重复执行不可重入清理或访问已删除 Qt 对象。
- 主启动函数必须以异常安全方式调用 shutdown。
- offscreen 测试必须证明连续调用 shutdown 两次以上安全。

### FR-10：项目基础与文档

- `requires-python` 必须精确写为 `>=3.14,<3.15`。
- 直接依赖必须且只能是 `PySide6==6.11.1`、`requests==2.34.2`、`websockets==16.1`。
- README 和开发指南中的 Windows 命令必须优先使用根目录 `venv`：
  - `.\venv\Scripts\python.exe`
  - `.\venv\Scripts\python.exe -m pip`
- 文档不得指导创建或使用 `.venv/`、`env/`，不得指导使用全局 Python 冒充项目环境。
- README 必须包含 `.\venv\Scripts\python.exe -m app.main` 启动方式。
- UI 架构文档必须记录 Composition Root、View/Presenter/Model 边界、Qt 生命周期和 LIVE-only 空状态。
- 控件归属文档必须说明两个 PAPER objectName 只是遗留 UI 契约，不表示存在模拟交易能力。

### FR-11：LIVE-only 清理

- 删除所有可运行或可导入的模拟交易生产模块、配置、启动脚本和 PAPER 样式。
- 生产运行路径不得存在模式选择分支、虚拟余额、虚拟仓位、虚拟成交、模拟撮合或模拟 Broker。
- 描述禁用模式的约束文档和测试断言可以出现 PAPER/TESTNET/DEMO/SANDBOX 文本。
- 两个遗留 objectName 及其绑定字符串、结构测试和 QSS 选择器可以保留；必须有文档解释，并且 Python 公共字段/Signal 不得继续采用 PAPER 语义。
- LIVE-only 静态检查不得因为上述明确允许的遗留 objectName 产生误报。

### FR-12：验证脚本

- 扩展现有 `validate_ui.py`，验证 XML、根控件、完整 objectName 契约、控件类型、三个 QSplitter 契约、允许变更后的结构签名、空状态文本、LIVE 文本和 disabled 状态。
- 扩展现有 `check_project.py`，验证 Python 约束、精确依赖、架构导入边界和 LIVE-only 生产路径。
- 两个脚本失败时必须逐项输出清晰原因并返回非零退出码。
- 验证脚本不得使用全局 Python、外部 CLI 或新增依赖。

## 架构边界

### View

View 只能负责：

- 通过 `QUiLoader` 加载 UI。
- 使用集中注册对象绑定控件。
- 暴露 Qt Signal。
- 设置空状态、文本、tooltip、enabled 状态等显示状态。
- 将五个 `QAbstractTableModel` 绑定到现有 `QTableView`。
- 显示和关闭主窗口。

View 不得执行：

- REST 或 WebSocket。
- Binance 或 Bitget 调用。
- 行情、资金费率、手续费、滑点、价差、利润或数量计算。
- 配置持久化或环境模式切换。
- 数据库操作。
- 下单、撤单、订单查询或成交对账。
- 虚构业务数据生成。

### Presenter

Presenter 只负责：

- 连接 View Signal。
- 绑定五个表格 Model。
- 设置初始空状态。
- 编排当前阶段允许的纯 UI 交互。
- 保证绑定幂等。

Presenter 不得：

- 调用不存在的业务服务。
- 创建假账户、假行情、假订单或假套利仓位。
- 直接访问 Qt Designer 控件之外的交易实现。
- 提前实现后续阶段的 Presenter 业务。

### Model

- 共同基类继续继承 `QAbstractTableModel`。
- 五个具体模型继续只声明各自表头并复用共同基类。
- Model 接收普通不可变行序列，不依赖 pandas、数据库 ORM 或交易所响应对象。
- Model 不计算业务值，不格式化尚未定义的交易规则，不持有交易所客户端。

### Composition Root 与生命周期

- `build_application()` 是阶段 1 的最高测试接缝和唯一对象组装位置。
- `ApplicationRuntime` 是 Qt 生命周期持有者和 shutdown 边界。
- 不新增容器框架、服务定位器或依赖注入框架。

## GUI 不变量

本阶段不得修改：

- 主窗口整体排版。
- 主窗口上下或左右区域划分。
- `QSplitter` 结构、数量或方向。
- 控件层级及容器关系。
- 控件位置。
- 任一现有控件 `objectName`。
- 表格、标签页、按钮和输入框的位置。
- 现有 QSS 视觉设计、颜色、间距和尺寸。
- UI 与源码分离方式。
- `QUiLoader` 运行时加载方式。

不得：

- 用 Python 代码重建主窗口。
- 生成或维护 `ui_mainwindow.py`。
- 将交易所、行情、下单或业务逻辑写入 View。
- 为接入功能重新设计 GUI。

允许修改 `.ui` 的范围仅限：

- 清除虚假业务示例值。
- 将 PAPER 可见文本改成 LIVE 正式实盘语义。
- 设置准确的空状态、placeholder 和 tooltip。
- 对尚未实现的操作设置 disabled 状态。

结构回归测试必须对基线 `cf1e1a4` 的 UI XML 建立规范化结构签名。签名忽略上述允许修改的显示属性和 ComboBox 示例 item，但必须覆盖 widget/layout 树、控件 class、全部 objectName、容器父子关系、三个 QSplitter 的名称与方向。实现后的签名必须与基线一致。

## LIVE-only 清理计划

| 实际路径或符号 | 当前状态 | 明确处理方式 |
| --- | --- | --- |
| `app/paper/` | 可导入的模拟交易生产包 | **删除目录** |
| `app/paper/__init__.py` | 声明 `app.paper` 包 | **删除** |
| `app/paper/fault_simulator.py` | 模拟故障占位 | **删除** |
| `app/paper/paper_account.py` | 虚拟账户占位 | **删除** |
| `app/paper/paper_broker.py` | 模拟 Broker 占位 | **删除** |
| `app/paper/paper_fill_engine.py` | 虚拟成交占位 | **删除** |
| `app/paper/paper_order_book.py` | 模拟订单簿占位 | **删除** |
| `config/paper.toml` | PAPER 模式配置 | **删除** |
| `config/development.toml` | 内容为 `mode = "paper"` | **删除** |
| `config/default.toml` | PAPER 模式及虚构业务默认值，且无代码读取 | **删除**；不在本阶段设计替代配置系统 |
| `config/live.toml` | 固定 `mode = "live"` | **保留到后续阶段**；本阶段不加载、不提供选择器 |
| `scripts/run_paper.py` | 可执行 PAPER 启动入口 | **删除** |
| `scripts/reset_paper_database.py` | PAPER 数据库入口占位 | **删除** |
| `app/ui/styles/paper_mode.qss` | PAPER 模式样式 | **删除** |
| `app/ui/styles/live_mode.qss` | 未启用的 LIVE 样式资产 | **保留 LIVE 语义**；不得作为运行时模式切换分支 |
| `.env.example` | 声明 `APP_MODE=paper`，当前无环境配置加载 | **删除**；凭据与完整配置系统留到后续阶段 |
| `.ui` 中 `paperModeButton` | 遗留 objectName；可见文本为 PAPER | **因 UI 契约保留名称**；可见文本改为 `LIVE 正式实盘`，移除下拉/切换暗示 |
| `.ui` 中 `paperOrderButton` | 遗留 objectName；可见文本为模拟下单 | **因 UI 契约保留名称**；可见文本改为 LIVE 语义并 disabled |
| `MainWindowWidgets.paper_mode_button` | Python 字段为 PAPER 语义 | **改为 LIVE 语义**，绑定字符串仍为 `paperModeButton` |
| `MainWindowWidgets.paper_order_button` | Python 字段为 PAPER 语义 | **改为 LIVE 语义**，绑定字符串仍为 `paperOrderButton` |
| `MainWindowView.paper_order_requested` | PAPER Signal | **改为 LIVE/中性 Signal**；本阶段按钮 disabled，不执行下单 |
| `MainWindowView.mode_change_requested` | 暗示运行模式切换 | **删除或改为非切换的 LIVE 信息 Signal**；不得改变运行环境 |
| `dark.qss` 中 `#paperModeButton` | 使用遗留 objectName 的选择器 | **因 UI 契约暂时保留名称**；不得解释为模拟能力，不改变视觉值 |
| `validate_ui.py`、结构测试中的两个 objectName | 验证稳定 UI 契约 | **保留名称**并补充遗留说明，不视为 LIVE-only 失败 |
| `docs/widget-ownership.md` 中的两个 objectName | 记录控件归属 | **保留名称**并明确说明仅为遗留 UI 契约 |
| `docs/project-tree.txt` 中 PAPER 文件 | 删除后的陈旧目录清单 | **修正**为阶段 1 完成后的真实树 |

清理完成后，任何生产入口都只能启动同一个 LIVE-only GUI 基础。不得增加 `--paper`、环境变量切换、配置文件切换或隐藏模拟分支作为替代。

## 文件级影响范围

### 直接复用且预计不修改

- `.gitignore`
- `requirements.txt`
- `app/ui/loader/ui_loader.py`
- 五个具体表格模型及其现有表头文件
- `app/infrastructure/config/paths.py`
- `app/ui/styles/dark.qss` 的视觉规则
- `scripts/run_dev.py`
- `scripts/run_live.py`
- 后续阶段的交易所、行情、执行、持久化、策略、Worker 和 Domain 占位模块（`app/paper/` 除外）
- fault-injection、replay 和 integration 测试占位

### 必须修改

- `pyproject.toml`
- `README.md`
- `app/main.py`
- `app/bootstrap.py`（仅在保证单一 Composition Root 与生命周期所需时修改）
- `app/container.py`
- `app/ui/forms/mainwindow.ui`（仅允许显示属性范围）
- `app/ui/loader/widget_registry.py`
- `app/ui/views/main_window.py`
- `app/ui/presenters/main_window_presenter.py`
- `app/ui/models/base_table_model.py`
- `scripts/check_project.py`
- `scripts/validate_ui.py`
- `tests/ui/test_architecture_boundaries.py`
- `tests/ui/test_mainwindow_ui_load.py`
- `tests/ui/test_mainwindow_ui_static.py`
- `tests/ui/test_model_binding.py`
- `tests/ui/test_widget_names.py`
- `docs/ui-architecture.md`
- `docs/widget-ownership.md`
- `docs/development-guide.md`
- `docs/project-tree.txt`

### 必须删除

- `.env.example`
- `app/paper/` 下全部六个 Python 文件及该目录
- `config/default.toml`
- `config/development.toml`
- `config/paper.toml`
- `scripts/run_paper.py`
- `scripts/reset_paper_database.py`
- `app/ui/styles/paper_mode.qss`

### 可新增的阶段 1 测试文件

为了保持测试职责清晰，可以在 `tests/ui/` 新增以下聚焦测试；也可以把等价用例并入现有文件，但不得创建平行测试框架：

- 控件绑定失败与类型错误测试。
- 表格模型行为与 reset 测试。
- View 实际控件 Signal 测试。
- ApplicationRuntime 生命周期与 shutdown 幂等测试。
- LIVE-only 生产路径测试。

不得新增生产模块，除非现有阶段 1 类确实无法承载指定行为；在这种情况下必须先证明无法复用现有 seam。

## 测试要求

### 测试决策

- 只使用 `unittest` 和 `unittest.mock` 作为测试框架和替身工具。
- Qt 运行时测试设置 `QT_QPA_PLATFORM=offscreen`，并复用单个 `QApplication`。
- 最高层测试 seam 是现有 `build_application()`：从该入口验证对象图、五表绑定、准确空状态和 shutdown。
- 聚焦 seam 仅限：`load_typed_ui()`、`MainWindowWidgets.bind()`、`ReadOnlyTableModel`、`MainWindowView` Signal、`MainWindowPresenter.bind()` 和 `ApplicationRuntime.shutdown()`。
- 优先断言外部可观察行为，不断言不影响契约的私有实现细节。
- 现有 UI 测试是 prior art，应扩展而不是替换。
- 禁止网络访问、真实交易所调用、数据库创建、模拟 Broker 或假业务数据。

### 必须覆盖的测试行为

1. XML 可解析，根控件 class/name 正确。
2. 全部既有 objectName 集合保持不变。
3. 控件注册能绑定所有阶段 1 必需控件。
4. 删除一个必需控件的临时测试 UI 时，绑定抛出包含 objectName 和期望类型的异常。
5. 把必需控件替换为错误 Qt 类型的临时测试 UI 时，绑定抛出清晰异常。
6. offscreen 下可从 Composition Root 构建完整 GUI 基础。
7. 五个表格分别绑定正确具体模型。
8. 每个模型表头和列数正确；合法行替换更新数据；非法列数不改变原数据。
9. 模型 flags 默认只读，无效索引安全。
10. 至少一个实际控件动作只触发一次对应 View Signal。
11. Presenter 连续调用 `bind()` 两次后，操作仍只触发一次。
12. 所有业务展示值为空状态，五表零行，未实现控件 disabled。
13. View 不导入交易所、行情、执行、数据库或业务服务。
14. Domain 不导入 PySide6、requests 或 websockets。
15. shutdown 连续调用至少两次不抛异常。
16. PAPER 生产包、配置、脚本和样式不存在，且不存在可运行模式选择。
17. UI 规范化结构签名、三个 QSplitter 和全部 objectName 与基线一致。

## 验收标准

以下每项都必须可由指定脚本、unittest 或启动命令验证；任一项失败则阶段 1 未完成。

1. **UI XML 可解析：** `validate_ui.py` 与 unittest 均能解析 `.ui`，无 XML 错误。
2. **根控件正确：** 根 widget 必须是 `QMainWindow` 且 name 为 `MainWindow`。
3. **必需 objectName 存在：** 完整 objectName 集合与基线一致，包括 `paperModeButton` 和 `paperOrderButton`。
4. **集中绑定成功：** `MainWindowWidgets.bind()` 对真实主窗口返回完整注册对象，View/Presenter 不出现散落的控件查找。
5. **缺失/类型错误异常清晰：** 两类失败测试都断言异常类型及消息中的 objectName、期望 Qt 类型；根类型错误还断言实际类型。
6. **offscreen 可加载：** 设置 `QT_QPA_PLATFORM=offscreen` 后，`build_application()` 能构建窗口且不显示平台插件错误。
7. **五表绑定正确：** 机会、仓位、执行中订单、订单历史、资金费历史表各自绑定正确模型实例。
8. **模型行为正确：** 表头、列数、行数、显示数据、只读 flags、合法 reset 和非法列数原子失败均有断言。
9. **View Signal 来自实际操作：** 测试通过控件 API 或 Qt 测试事件执行真实用户动作，Signal 计数恰为 1；不得直接调用被测 Signal 的 `emit()` 伪装通过。
10. **Presenter 无重复连接：** 同一 Presenter 至少调用两次 `bind()`，一次实际操作仍只产生一次 Signal/处理调用。
11. **无虚拟业务数据：** 启动后不得显示虚拟余额、价格、仓位、盈亏、订单、延迟或更新时间；表格均为零行；空值不使用 `0` 冒充查询结果。
12. **View 导入边界：** 静态测试证明 View 不导入 `app.exchanges`、`app.execution`、`app.market_data`、`app.persistence` 或相应业务实现。
13. **Domain 依赖边界：** 静态测试证明 `app/domain/` 不导入 PySide6、requests 或 websockets。
14. **shutdown 幂等：** 构建运行时后连续调用 shutdown 两次以上，调用均成功且 Qt 事件处理不访问已删除对象。
15. **生产路径 LIVE-only：** `app/paper/`、PAPER 配置、PAPER 脚本、PAPER 样式均不存在；生产入口无 paper/testnet/demo/sandbox 参数、配置选择或代码分支；仅允许两个遗留 objectName 及其绑定、测试和说明文档出现 PAPER 名称。
16. **版本约束正确：** `requires-python` 精确为 `>=3.14,<3.15`，直接依赖集合和版本与 AGENTS.md 完全一致。
17. **GUI 契约未变化：** 规范化 UI 结构签名与基线一致；三个 QSplitter 名称、方向和父子位置不变；全部 objectName 不变；QSS 视觉值未变化。

## 验证命令

所有命令必须从仓库根目录执行，并使用根目录虚拟环境：

```text
.\venv\Scripts\python.exe scripts\validate_ui.py
.\venv\Scripts\python.exe scripts\check_project.py
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\venv\Scripts\python.exe -m app.main
```

前三条命令必须以退出码 `0` 完成。第四条命令必须成功显示主窗口，窗口呈现准确 LIVE-only 空状态，并在用户关闭后以退出码 `0` 结束。

如果实际环境无法运行任一命令，实施报告必须写明命令、实际解释器路径、退出码和原始失败原因；不得改用全局 Python、其他 Python 版本、`.venv/` 或其他环境伪装通过。

## 风险和实施注意事项

- **UI 契约回归：** 清理 171 个 widget 中的示例值时容易误改布局、容器或 objectName；必须由规范化结构签名和完整 objectName 集合阻止。
- **遗留名称误报：** LIVE-only 扫描若简单禁止字符串 `paper`，会错误拒绝两个必须保留的 objectName；检查必须基于允许清单，只允许 UI 契约、测试和说明文档引用。
- **Signal 重复连接：** `bind()` 当前每次新建 lambda 并连接，重复调用会放大事件；幂等状态必须在连接前生效并有计数测试。
- **Qt 生命周期：** `QObject` parent、Python 强引用、顶层 `QMainWindow`、`close()` 与 `deleteLater()` 的组合处理不当会导致提前回收或重复删除；测试必须处理 Qt 事件队列。
- **空状态误导：** 用 `0`、默认交易对或默认订单参数替代示例值仍会被用户理解为真实结果；空状态必须使用非数值占位并禁用后续业务操作。
- **删除遗留文件后的陈旧引用：** 删除 PAPER 文件后，项目树、控件归属、README、脚本检查和测试中的引用必须同步审查，避免文档或启动命令指向不存在路径。
- **验证脚本副作用：** 验证可以生成被 `.gitignore` 排除的 Python 缓存，但不得生成源码、UI 派生文件、数据库或运行配置。
- **范围膨胀：** 现有大量后续模块只是占位；阶段 1 不得因为这些文件存在而实现服务、Worker、网络、数据库或策略。

以上均为实施回归和工程边界风险，不是业务风控需求，不得据此新增风险规则或阻断业务调试的逻辑。

## 未决事项

- 没有阻塞阶段 1 的未决产品或策略问题。
- `paperModeButton`、`paperOrderButton` 的 objectName 是否在未来迁移不属于本阶段；本阶段决定是无条件保留，并在 Python/API/可见文本层使用 LIVE 或中性语义。
- 真实交易策略、交易对、阈值、订单类型、保证金模式、杠杆和默认投入金额均未确定，必须保持为空并留给后续相应阶段。

## 后续阶段边界

阶段 1 完成后，仓库只应提供可启动、可关闭、可测试、LIVE-only、无虚构业务数据的 GUI 基础。阶段 2 才处理核心领域模型与 Decimal 精度规则；阶段 3 及以后依次处理交易规则、REST、WebSocket、账户、套利机会、双腿订单和成交对账。

阶段 1 不得为后续阶段预先实现接口客户端、通用 Worker、异步任务框架、配置系统、数据库业务、交易策略或风险逻辑。后续阶段必须继续复用本阶段确立的 Composition Root、View/Presenter/Model 边界、UI objectName 契约和 Qt 生命周期边界。
