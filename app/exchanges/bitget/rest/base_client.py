"""Synchronous Bitget REST request and authentication foundation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
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
from app.exchanges.bitget.constants import BITGET_BASE_URL
from app.exchanges.bitget.signer import build_prehash, sign_prehash
from app.infrastructure.security.credential_store import ApiCredentials
from app.infrastructure.security.secret_redactor import redact_secrets


_LOGGER = logging.getLogger("binance_bitget_bot.exchanges.bitget.rest")


class BitgetRestClient:
    """Minimal synchronous client; callers must run it outside the GUI thread."""

    def __init__(
        self,
        *,
        credentials: ApiCredentials | None = None,
        session: requests.Session | None = None,
        timeout: float = 10.0,
        clock_ms: Callable[[], int] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
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
        self._logger.debug("Bitget public %s %s", method, path)
        return self._send(method, path, params=dict(params) if params else None)

    def private_request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, object] | None = None,
        body: Mapping[str, object] | None = None,
    ) -> Any:
        method = _method(method)
        _path(path)
        api_key, secret, passphrase = self._required_credentials()
        ordered_params = dict(sorted((params or {}).items()))
        query_string = urlencode(ordered_params, doseq=True)
        body_text = (
            json.dumps(body, separators=(",", ":"), ensure_ascii=False)
            if body is not None
            else ""
        )
        timestamp = str(self._clock_ms())
        signature = sign_prehash(
            build_prehash(timestamp, method, path, query_string, body_text), secret
        )
        headers = {
            "ACCESS-KEY": api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": passphrase,
            "Content-Type": "application/json",
        }
        self._logger.debug("Bitget private %s %s", method, path)
        return self._send(
            method,
            path,
            params=ordered_params or None,
            headers=headers,
            body_text=body_text or None,
            extra_secrets=(signature,),
        )

    def _required_credentials(self) -> tuple[str, str, str]:
        credential_fields = (
            ("BITGET_API_KEY", self._credentials.bitget_api_key),
            ("BITGET_API_SECRET", self._credentials.bitget_api_secret),
            ("BITGET_API_PASSPHRASE", self._credentials.bitget_api_passphrase),
        )
        missing = [name for name, value in credential_fields if not value.strip()]
        if missing:
            raise ExchangeCredentialsError(
                f"Bitget REST credentials incomplete: {', '.join(missing)}"
            )
        return (
            self._credentials.bitget_api_key,
            self._credentials.bitget_api_secret,
            self._credentials.bitget_api_passphrase,
        )

    def _send(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, object] | None,
        headers: dict[str, str] | None = None,
        body_text: str | None = None,
        extra_secrets: tuple[str, ...] = (),
    ) -> Any:
        kwargs: dict[str, object] = {
            "params": params,
            "timeout": self._timeout,
        }
        if headers is not None:
            kwargs["headers"] = headers
        if body_text is not None:
            kwargs["data"] = body_text
        try:
            response = self._session.request(method, BITGET_BASE_URL + path, **kwargs)
        except requests.Timeout:
            raise ExchangeTimeoutError(
                f"Bitget REST request timed out after {self._timeout} seconds"
            ) from None
        except requests.RequestException:
            raise ExchangeResponseError("Bitget REST transport failure") from None
        try:
            payload = response.json()
        except (TypeError, ValueError):
            if not 200 <= response.status_code < 300:
                raise ExchangeHttpError("Bitget", response.status_code) from None
            raise ExchangeResponseError(
                "Bitget REST response is not valid JSON"
            ) from None

        code, message = _api_result(payload)
        safe_message = redact_secrets(
            message,
            (*self._credentials.secret_values(), *extra_secrets),
        )
        if not 200 <= response.status_code < 300:
            raise ExchangeHttpError(
                "Bitget", response.status_code, code, safe_message
            )
        if code is None:
            raise ExchangeResponseError(
                "Bitget REST response is missing its API result code"
            )
        if code is not None and str(code) != "00000":
            raise ExchangeApiError("Bitget", code, safe_message)
        return payload


def _api_result(payload: object) -> tuple[object, str]:
    if not isinstance(payload, Mapping):
        return None, ""
    return payload.get("code"), str(payload.get("msg", ""))


def _method(method: str) -> str:
    normalized = method.upper()
    if normalized not in {"GET", "POST"}:
        raise ValueError(f"unsupported Bitget REST method: {method}")
    return normalized


def _path(path: str) -> None:
    if not path.startswith("/") or "://" in path or "?" in path or "#" in path:
        raise ValueError("REST path must not contain a URL, query, or fragment")
