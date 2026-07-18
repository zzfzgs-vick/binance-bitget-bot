# Title: 仅接入正式生产环境

**Status:** Accepted

## Context

本项目的目标是连接 Binance 与 Bitget 正式生产环境。模拟盘、测试网和 Demo Trading 会引入不同的端点、字段、行为和运行分支，与当前产品范围不一致。

## Decision

只接入 Binance 和 Bitget 正式生产环境，不提供 PAPER、TESTNET、DEMO、SANDBOX、模拟盘或测试网切换。

## Consequences

- 生产代码只保留正式生产环境的 REST 和 WebSocket 配置与流程。
- 不实现模拟余额、模拟仓位、虚拟成交或模拟撮合。
- 单元测试可以使用 `unittest.mock` 隔离网络，但测试替身不得进入生产运行路径。
