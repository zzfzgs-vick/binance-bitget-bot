"""Errors shared by the synchronous REST adapters."""

from __future__ import annotations


class ExchangeRestError(RuntimeError):
    """Base class for a safe-to-display REST failure."""


class ExchangeCredentialsError(ExchangeRestError):
    """Required in-memory credentials are missing."""


class ExchangeTimeoutError(ExchangeRestError):
    """A REST request exceeded its configured timeout."""


class ExchangeResponseError(ExchangeRestError):
    """The exchange returned a response that could not be decoded."""


class ExchangeHttpError(ExchangeRestError):
    """An HTTP response had a non-success status."""

    def __init__(
        self,
        exchange: str,
        status_code: int,
        api_code: object = None,
        api_message: str = "",
    ) -> None:
        self.exchange = exchange
        self.status_code = status_code
        self.api_code = api_code
        self.api_message = api_message
        detail = _api_detail(api_code, api_message)
        super().__init__(f"{exchange} REST HTTP {status_code}{detail}")


class ExchangeApiError(ExchangeRestError):
    """An HTTP-success response contained an exchange error code."""

    def __init__(self, exchange: str, api_code: object, api_message: str) -> None:
        self.exchange = exchange
        self.api_code = api_code
        self.api_message = api_message
        super().__init__(
            f"{exchange} REST API error{_api_detail(api_code, api_message)}"
        )


def _api_detail(api_code: object, api_message: str) -> str:
    parts = []
    if api_code is not None:
        parts.append(f"code={api_code}")
    if api_message:
        parts.append(f"message={api_message}")
    return f" ({', '.join(parts)})" if parts else ""
