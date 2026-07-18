# Validation report

- Validated Python: 3.14.5; required range: `>=3.14,<3.15`
- Validated direct dependencies: PySide6 6.11.1, requests 2.34.2, websockets 16.1
- UI XML, root widget, required object names, structural contract, and empty-state contract: PASS
- Runtime Qt loading in offscreen mode: PASS
- Dependency policy, source import boundaries, UI/source contract, and Python syntax: PASS
- Typed configuration, environment-only credentials, log rotation, idempotence, and redaction: PASS
- Binance and Bitget production REST request, signing, timeout, and error contracts: PASS
- Binance and Bitget production WebSocket subscription, authentication-message, heartbeat, reconnect, dispatch, redaction, and lifecycle contracts: PASS
- Binance and Bitget spot/USDT-perpetual product parsing, Decimal rules, cross-exchange matching, quantization, and invalid-data contracts: PASS
- Binance and Bitget spot/USDT-perpetual best quotes, depth snapshots and updates, funding rates, Decimal precision, and sequence-gap recovery: PASS
- Bidirectional spot/perpetual depth fills, common-quantity normalization, fees, slippage, gross/net profit, ROI, stale data, and insufficient depth: PASS
- Standard-library unittest suite: PASS (130 tests)
- `.\venv\Scripts\python.exe -m app.main` window creation and normal close: PASS

No global Python or alternate virtual environment was used for validation.
