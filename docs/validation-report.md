# Validation report

- Validated Python: 3.14.5; required range: `>=3.14,<3.15`
- Validated direct dependencies: PySide6 6.11.1, requests 2.34.2, websockets 16.1
- UI XML, root widget, required object names, structural contract, and empty-state contract: PASS
- Runtime Qt loading in offscreen mode: PASS
- Dependency policy, source import boundaries, UI/source contract, and Python syntax: PASS
- Standard-library unittest suite: PASS (21 tests)
- `.\venv\Scripts\python.exe -m app.main` window creation and normal close: PASS

No global Python or alternate virtual environment was used for validation.
