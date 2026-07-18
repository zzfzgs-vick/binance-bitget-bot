# Development guide

1. Use Python 3.14.x.
2. Install only the pinned packages in `requirements.txt`.
3. Modify UI only in Qt Designer.
4. Keep `objectName` stable or update `MainWindowWidgets` and tests together.
5. Run `python scripts/validate_ui.py` after every UI change.
6. Run `python -m unittest discover -s tests -p "test_*.py"`.
7. Keep business logic outside `app/ui/views`.
8. Do not import PySide6, requests, or websockets from `app/domain`.
9. Future REST code must use requests directly.
10. Future WebSocket code must use websockets directly.
