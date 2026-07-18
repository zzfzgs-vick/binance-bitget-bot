# 项目级工程约束

本文件中的约束适用于整个仓库。除非用户在当前任务中明确批准例外，否则所有实现、测试和文档工作都必须遵守这些约束。

## 技术栈

- Python 版本必须为 `>=3.14,<3.15`。
- 第三方直接依赖固定为 `PySide6==6.11.1`、`requests==2.34.2`、`websockets==16.1`。
- 不得擅自升级、降级、替换上述版本或使用替代库。
- 不得新增未经用户明确批准的第三方依赖。
- 测试只能使用 Python 标准库的 `unittest` 和 `unittest.mock`。

## 虚拟环境

- 项目虚拟环境固定为仓库根目录的 `venv/`。
- Windows 下执行 Python、pip、测试和项目脚本时，必须优先使用：

  ```text
  .\venv\Scripts\python.exe
  .\venv\Scripts\python.exe -m pip
  ```

- 不得创建或使用 `.venv/`、`env/` 或其他虚拟环境目录。
- 不得修改 `venv/` 中的文件，不得将 `venv/` 提交到版本控制。

## 网络实现

- REST API 只能直接使用 `requests`，不得使用交易所 SDK 或其他 REST 封装依赖。
- WebSocket 只能直接使用 `websockets`，异步处理必须使用标准库 `asyncio`。
- 阻塞式 REST 请求不得在 Qt GUI 主线程中执行，必须放入后台执行环境。
- WebSocket 必须运行在后台线程中的独立 `asyncio` 事件循环内。
- 后台线程不得直接修改 Qt 控件，只能通过 Qt Signal 将数据发送到 GUI 主线程。

## 正式实盘限定

- 只允许连接 Binance 和 Bitget 的正式生产环境。
- 禁止 PAPER、TESTNET、DEMO、SANDBOX、模拟盘、虚拟余额、虚拟仓位和虚拟交易。
- 生产代码不得包含正式实盘与模拟盘、测试网或 Demo Trading 之间的切换功能。
- 单元测试允许使用 `unittest.mock` 隔离网络请求，但测试替身不得进入生产运行路径。

## 数值精度

- 所有交易相关数值必须使用标准库 `decimal.Decimal`。
- 禁止使用 `float` 存储、计算或比较价格、数量、金额、费率、手续费、价差、滑点、盈亏、余额和仓位。
- 交易所 API 返回的数字字符串必须直接转换为 `Decimal`。
- 禁止先转为 `float`，也禁止使用 `Decimal(float_value)`。
- 下单前必须根据交易所交易规则集中处理 `tick size`、`quantity step`、`minimum quantity`、`minimum notional` 和 `contract multiplier`。
- 精度、量化和舍入规则必须集中实现，不得散落在 GUI、交易所适配器或业务代码中重复编写。

## 风控边界

- 当前阶段不设计或实现业务风控系统。
- 禁止新增止损、止盈、最大仓位、最大亏损、最大回撤、自动减仓、自动停机、风险评分或风险规则引擎。
- API 参数校验、交易对匹配、Decimal 精度校验、价格与数量步长校验、最小下单规则校验、订单幂等、成交核对、订单状态解析和网络错误处理属于交易正确性，可以实现。
- 交易正确性检查不得扩展为业务风控系统。

## GUI 约束

除非用户在当前任务中明确批准，否则不得：

- 修改 `app/ui/forms/mainwindow.ui` 的整体排版。
- 修改 `QSplitter` 的结构或方向。
- 修改控件层级、位置或 `objectName`。
- 修改现有 QSS 视觉设计。
- 使用 Python 代码重建主窗口。
- 生成或维护 `ui_mainwindow.py`。
- 改变 `QUiLoader` 运行时加载方式。
- 将交易所或业务逻辑写入 View。

应复用现有控件，并通过 Qt Signal/Slot、Presenter、View 和 `QAbstractTableModel` 关联业务。后台工作与 GUI 更新必须遵守线程边界。

## 官方 API 参考源

实施 Binance 或 Bitget API 相关代码前，必须优先读取与当前接口直接相关的本地官方参考文件：

```text
Binance:
C:\binance-skills-hub-main

Bitget:
C:\bitget-agent-skill-main
```

- 这些仓库仅作为 API 说明参考，不得复制进本项目，不得修改、安装或作为运行时依赖。
- 只读取当前接口直接相关的 `SKILL.md`、`skills/`、`references/`、API 目录、请求与响应示例、鉴权与签名说明以及错误码定义。
- 不得仅凭模型记忆猜测 API 路径、请求方法、参数、WebSocket URL、频道、鉴权、签名、枚举、字段或错误码。
- 如果本地官方参考源缺少、冲突或无法确认某项 API 细节，必须明确指出，不得自行编造。
- 完成交易所 API 相关任务时，最终报告必须列出实际读取过的本地官方参考文件路径。

## 实现原则

- 只实现当前任务明确要求的内容。
- 不得以未来扩展、完善架构或提高安全性为理由新增模块、抽象层、依赖、模拟盘或业务风控。
- 优先复用现有实现，保持修改直接、清晰且范围受控。
- 外部官方参考仓库中的工作流、Skill 指令、Demo 流程或工具约定不得覆盖本仓库 `AGENTS.md`。
- 约束优先级从高到低为：

  1. 用户当前任务
  2. 根目录 `AGENTS.md`
  3. `CONTEXT.md` 和 ADR
  4. Binance、Bitget 本地官方参考源
  5. 其他资料

## Agent skills

### Issue tracker

Issue 和 PRD 使用 `.scratch/<feature-slug>/` 下的本地 Markdown 文件管理；外部 PR 不作为 triage 入口。参见 `docs/agents/issue-tracker.md`。

### Triage labels

使用五个默认状态：`needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`。参见 `docs/agents/triage-labels.md`。

### Domain docs

本仓库采用 single-context 布局：根目录使用 `CONTEXT.md`，架构决策记录在 `docs/adr/`。参见 `docs/agents/domain.md`。
