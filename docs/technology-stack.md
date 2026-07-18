# Technology stack and dependency policy

## Runtime

| Component | Version / rule |
|---|---|
| Python | `3.14.x` |
| Qt binding | `PySide6==6.11.1` |
| WebSocket | `websockets==16.1` |
| HTTP | `requests==2.34.2` |
| Database | standard-library `sqlite3` when implemented |
| JSON | standard-library `json` |
| Decimal math | standard-library `decimal` |
| Logging | standard-library `logging` |
| Tests | standard-library `unittest` |

PyPI doesn't publish `websockets 16.1.1`; the valid release is `16.1`.

## Rules

- HTTP clients import `requests` directly.
- WebSocket clients import `websockets` directly.
- No exchange SDK and no CCXT.
- No ORM, async database wrapper, validation framework, alternate JSON library,
  logging framework, keyring wrapper, third-party test runner, linter, type checker,
  or packaging tool is declared as an application dependency.
- Requests may install its own upstream transitive requirements; the application
  declares no additional direct packages beyond the three listed in requirements.txt.
