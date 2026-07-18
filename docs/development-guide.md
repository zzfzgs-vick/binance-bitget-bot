# Development guide

1. 使用 Python `>=3.14,<3.15`，虚拟环境固定为仓库根目录 `venv/`。
2. 只安装 `requirements.txt` 中精确锁定的依赖：`.\venv\Scripts\python.exe -m pip install -r requirements.txt`。
3. 仅使用 Qt Designer 修改 `app/ui/forms/mainwindow.ui` 的允许显示属性，不改变布局、层级、位置、objectName 或 QSplitter。
4. `objectName` 是稳定 UI 契约；`paperModeButton` 与 `paperOrderButton` 是遗留名称，不表示存在模拟能力。
5. 每次 UI 变更后运行 `.\venv\Scripts\python.exe scripts\validate_ui.py`。
6. 运行 `.\venv\Scripts\python.exe scripts\check_project.py`。
7. 运行 `.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"`。
8. 使用 `.\venv\Scripts\python.exe -m app.main` 启动应用。
9. 保持业务逻辑在 `app/ui/views` 之外。
10. `app/domain` 不得导入 PySide6、requests 或 websockets。
11. 后续 REST 直接使用 requests；WebSocket 直接使用 websockets。
