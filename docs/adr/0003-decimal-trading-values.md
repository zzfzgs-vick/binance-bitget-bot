# Title: 交易相关数值统一使用 Decimal

**Status:** Accepted

## Context

价格、数量、金额、费率和成交结果需要遵守交易所给出的十进制精度与步长。二进制浮点数不能可靠表达这些交易数值。

## Decision

所有交易相关数值使用 Python 标准库的 `Decimal` 存储、计算和比较，禁止使用 `float`。API 数字字符串直接转换为 `Decimal`，禁止 `Decimal(float_value)`。

## Consequences

- GUI 数值输入和 API 响应必须从字符串直接解析为 `Decimal`。
- 下单前集中处理 tick size、quantity step、minimum quantity、minimum notional 和 contract multiplier。
- 价格、数量、费率、手续费、价差、滑点、盈亏、余额和仓位的类型边界必须保持为 `Decimal`。
