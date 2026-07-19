# Networking boundary

The project reserves two direct transport choices only:

```text
REST / HTTPS  -> requests 2.34.2
WebSocket     -> websockets 16.1
```

Exchange adapters may wrap these packages behind project-owned interfaces, but they
must not replace them with another HTTP/WebSocket client or exchange SDK.

REST clients are synchronous and must not run on the Qt GUI thread. WebSocket
clients own a background thread and a private asyncio event loop. They provide
JSON/raw-message dispatch, protocol or application heartbeat handling, bounded
reconnection, and subscription restoration. They never update Qt objects directly.
`ApplicationRuntime` starts the production data clients, and normalized events cross
to GUI presenters only through Qt Signals. Public-market subscriptions are built
from normalized instruments and passed to the existing clients.

For the first Binance spot update, `lastUpdateId + 1` must fall within `[U, u]`;
later updates continue across the same range fields. For Binance futures, the
snapshot update ID must fall within the first `[U, u]` range and every later `pu`
must equal the prior `u`. For Bitget full-depth data, the snapshot `seq` must fall
within the first incremental update's `[pseq, seq]` range; each later update
requires its `pseq` to equal the prior update's `seq`. Duplicate and stale updates
are ignored explicitly. A sequence gap invalidates the local book, and no
incremental update is accepted until a new snapshot is applied.
