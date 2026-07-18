# Networking boundary

The project reserves two direct transport choices only:

```text
REST / HTTPS  -> requests 2.34.2
WebSocket     -> websockets 16.1
```

Exchange adapters may wrap these packages behind project-owned interfaces, but they
must not replace them with another HTTP/WebSocket client or exchange SDK.

No network functionality is implemented in this UI-only archive.
