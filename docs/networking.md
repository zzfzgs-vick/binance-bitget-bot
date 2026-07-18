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
reconnection, and subscription restoration. They do not update Qt objects and are
not connected to the GUI in this stage.
