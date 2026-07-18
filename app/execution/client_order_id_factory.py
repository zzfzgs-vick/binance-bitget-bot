"""Generate short process-unique client order identifiers."""

from collections.abc import Callable
import itertools
import threading
import time

from app.domain.orders.client_order_id import ClientOrderId


class ClientOrderIdFactory:
    def __init__(
        self,
        prefix: str = "arb",
        *,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self._prefix = prefix
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self._counter = itertools.count()
        self._lock = threading.Lock()

    def create(self, leg: str) -> ClientOrderId:
        with self._lock:
            sequence = next(self._counter)
        return ClientOrderId(
            f"{self._prefix}-{self._clock_ms()}-{sequence}-{leg}"
        )
