"""Synchronous Binance REST request and authentication foundation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import logging
import time
from typing import Any
from urllib.parse import urlencode

import requests

from app.exchanges.base.exchange_errors import (
    ExchangeApiError,
    ExchangeCredentialsError,
    ExchangeHttpError,
    ExchangeResponseError,
    ExchangeTimeoutError,
)
from app.exchanges.binance.signer import sign_query
from app.infrastructure.security.credential_store import ApiCredentials
from app.infrastructure.security.secret_redactor import redact_secrets


_LOGGER = logging.getLogger("binance_bitget_bot.exchanges.binance.rest")


class BinanceRestClient:
    """Minimal synchronous client; callers must run it outside the GUI thread."""

    BASE_URL = ""

    def __init__(
        self,
        *,
        credentials: ApiCredentials | None = None,
        session: requests.Session | None = None,
        timeout: float = 10.0,
        clock_ms: Callable[[], int] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        if not self.BASE_URL:
            raise TypeError("BinanceRestClient requires a concrete production market client")
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        self._credentials = credentials or ApiCredentials()
        self._owns_session = session is None
        self._session = session or requests.Session()
        self._closed = False
        self._timeout = timeout
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self._logger = logger or _LOGGER

    def close(self) -> None:
        """Close an internally created connection pool once."""
        if self._closed:
            return
        self._closed = True
        if self._owns_session:
            self._session.close()

    def public_request(
        self,
        method: str,
        path: str,
        params: Mapping[str, object] | None = None,
    ) -> Any:
        method = _method(method)
        _path(path)
        self._logger.debug("Binance public %s %s", method, path)
        return self._send(method, path, params=dict(params) if params else None)

    def private_request(
        self,
        method: str,
        path: str,
        params: Mapping[str, object] | None = None,
    ) -> Any:
        method = _method(method)
        _path(path)
        api_key, secret = self._required_credentials()
        signed_params = dict(params or {})
        signed_params["timestamp"] = self._clock_ms()
        query_string = urlencode(signed_params, doseq=True)
        signed_params["signature"] = sign_query(query_string, secret)
        self._logger.debug("Binance private %s %s", method, path)
        return self._send(
            method,
            path,
            params=signed_params,
            headers={"X-MBX-APIKEY": api_key},
            extra_secrets=(signed_params["signature"],),
        )

    def api_key_request(
        self,
        method: str,
        path: str,
        params: Mapping[str, object] | None = None,
    ) -> Any:
        """Call an API-key-only endpoint without adding a request signature."""
        method = _method(method)
        _path(path)
        api_key, _secret = self._required_credentials()
        self._logger.debug("Binance API-key %s %s", method, path)
        return self._send(
            method,
            path,
            params=dict(params) if params else None,
            headers={"X-MBX-APIKEY": api_key},
        )

    def _required_credentials(self) -> tuple[str, str]:
        missing = []
        if not self._credentials.binance_api_key.strip():
            missing.append("BINANCE_API_KEY")
        if not self._credentials.binance_api_secret.strip():
            missing.append("BINANCE_API_SECRET")
        if missing:
            raise ExchangeCredentialsError(
                f"Binance REST credentials incomplete: {', '.join(missing)}"
            )
        return (
            self._credentials.binance_api_key,
            self._credentials.binance_api_secret,
        )

    def _send(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, object] | None,
        headers: dict[str, str] | None = None,
        extra_secrets: tuple[str, ...] = (),
    ) -> Any:
        kwargs: dict[str, object] = {
            "params": params,
            "timeout": self._timeout,
        }
        if headers is not None:
            kwargs["headers"] = headers
        try:
            response = self._session.request(method, self.BASE_URL + path, **kwargs)
        except requests.Timeout:
            raise ExchangeTimeoutError(
                f"Binance REST request timed out after {self._timeout} seconds"
            ) from None
        except requests.RequestException:
            raise ExchangeResponseError("Binance REST transport failure") from None
        try:
            payload = response.json()
        except (TypeError, ValueError):
            if not 200 <= response.status_code < 300:
                raise ExchangeHttpError("Binance", response.status_code) from None
            raise ExchangeResponseError(
                "Binance REST response is not valid JSON"
            ) from None

        code, message = _api_error(payload)
        safe_message = redact_secrets(
            message,
            (*self._credentials.secret_values(), *extra_secrets),
        )
        if not 200 <= response.status_code < 300:
            raise ExchangeHttpError(
                "Binance", response.status_code, code, safe_message
            )
        if isinstance(code, int) and code < 0:
            raise ExchangeApiError("Binance", code, safe_message)
        return payload


def _api_error(payload: object) -> tuple[object, str]:
    if not isinstance(payload, Mapping):
        return None, ""
    return payload.get("code"), str(payload.get("msg", ""))


def _method(method: str) -> str:
    normalized = method.upper()
    if normalized not in {"GET", "POST", "PUT", "DELETE"}:
        raise ValueError(f"unsupported Binance REST method: {method}")
    return normalized


def _path(path: str) -> None:
    if not path.startswith("/") or "://" in path or "?" in path or "#" in path:
        raise ValueError("REST path must not contain a URL, query, or fragment")
