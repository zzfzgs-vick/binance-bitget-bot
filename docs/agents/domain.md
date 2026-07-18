# Domain docs

工程技能探索代码库前，应按以下规则读取领域文档。

## 开始探索前

- 读取仓库根目录的 `CONTEXT.md`
- 读取 `docs/adr/` 中与当前工作范围有关的 ADR

如果这些文件尚不存在，继续工作即可，不需要预先建议创建。`domain-modeling` 等技能会在术语或架构决策实际形成时按需创建它们。

## 当前布局

本仓库采用 single-context 布局：

```text
/
├── AGENTS.md
├── CONTEXT.md
├── app/
├── config/
├── docs/
│   ├── agents/
│   └── adr/
├── scripts/
└── tests/
```

## 使用领域词汇

Issue 标题、重构建议、假设和测试名称应使用 `CONTEXT.md` 定义的领域术语，避免改用其中明确排除的同义词。

如果需要的概念尚未出现在词汇表中，应重新确认是否正在创造项目未使用的语言；若确实存在领域缺口，将其交给 `domain-modeling` 处理。

## 标明 ADR 冲突

如果输出与现有 ADR 冲突，应明确指出冲突，而不是静默覆盖既有决策。
