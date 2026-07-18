# Title: 明确网络与 Qt GUI 的线程边界

**Status:** Accepted

## Context

`requests` 执行阻塞式 REST 调用，`websockets` 基于 `asyncio` 运行。若在 Qt GUI 主线程执行网络工作，界面会被阻塞；若后台线程直接修改 Qt 控件，则会破坏 Qt 的线程约束。

## Decision

REST 请求在后台执行环境运行。WebSocket 在后台线程中的独立 `asyncio` 事件循环内运行。后台线程只通过 Qt Signal 与 GUI 主线程通信，不直接修改 Qt 控件。

## Consequences

- REST 调用必须通过后台线程、`QThread` 或标准库后台执行器调度。
- 每个 WebSocket 后台运行环境需要明确管理其事件循环、启动和关闭生命周期。
- GUI 更新集中在主线程，通过 Signal/Slot 接收后台结果和错误。
