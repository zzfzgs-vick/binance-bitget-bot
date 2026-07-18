# Title: 使用 QUiLoader 运行时加载 Qt UI

**Status:** Accepted

## Context

主窗口界面已在 `app/ui/forms/mainwindow.ui` 中定义。项目需要保持 UI 与 Python 业务代码分离，并避免维护由工具生成的重复 Python 界面代码。

## Decision

使用 `QUiLoader` 在运行时加载 `mainwindow.ui`。不生成、不维护 `ui_mainwindow.py`，Python 代码通过现有控件及其 `objectName` 建立界面关联。

## Consequences

- `mainwindow.ui` 是主窗口结构的唯一来源。
- 业务接入不得通过 Python 代码重建主窗口或改变运行时加载方式。
- UI 控件名称和层级成为 View 与 Presenter 关联时必须保持稳定的接口。
