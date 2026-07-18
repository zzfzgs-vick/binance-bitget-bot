# Validation report

- Target Python: 3.14.x
- Direct dependencies: PySide6 6.11.1, websockets 16.1, requests 2.34.2
- UI XML: PASS
- Required widget object names: PASS
- QSS externalization: PASS
- Source import policy: PASS
- Forbidden dependency scan: PASS
- Python syntax compile: PASS
- Standard-library unittest suite: PASS (Qt runtime tests skip when PySide6 is unavailable)
- Project checker: PASS
- Runtime Qt rendering in build environment: not guaranteed because the exact target stack was not installed.

## websockets version correction

The requested `websockets 16.1.1` isn't a published PyPI release. The package uses the available `websockets==16.1`.
