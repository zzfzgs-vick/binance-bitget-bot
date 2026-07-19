from __future__ import annotations

import io
import logging
import unittest
from unittest.mock import Mock, patch

import requests

from app.exchanges.base.exchange_errors import (
    ExchangeApiError,
    ExchangeCredentialsError,
    ExchangeHttpError,
    ExchangeResponseError,
    ExchangeTimeoutError,
)
from app.exchanges.binance.constants import (
    BINANCE_FUTURES_BASE_URL,
    BINANCE_SPOT_BASE_URL,
)
from app.exchanges.binance.rest.futures_market_client import (
    BinanceFuturesMarketClient,
)
from app.exchanges.binance.rest.spot_market_client import BinanceSpotMarketClient
from app.exchanges.binance.rest.futures_trading_client import BinanceFuturesTradingClient
from app.exchanges.binance.signer import sign_query
from app.infrastructure.security.credential_store import ApiCredentials


class _Response:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> object:
        return self._payload


class _InvalidJsonResponse(_Response):
    def json(self) -> object:
        raise ValueError("invalid JSON")


class BinanceRestTests(unittest.TestCase):
    def test_futures_listen_key_create_keepalive_and_close_are_api_key_only(self) -> None:
        self.session.request.side_effect = [
            _Response({"listenKey": "live-listen-key"}),
            _Response({}),
            _Response({}),
        ]
        client = BinanceFuturesTradingClient(
            credentials=self.credentials, session=self.session
        )

        self.assertEqual(client.create_listen_key(), "live-listen-key")
        client.keepalive_listen_key()
        client.close_listen_key()

        self.assertEqual(
            [call.args[0] for call in self.session.request.call_args_list],
            ["POST", "PUT", "DELETE"],
        )
        for call in self.session.request.call_args_list:
            self.assertEqual(call.args[1], "https://fapi.binance.com/fapi/v1/listenKey")
            self.assertEqual(call.kwargs["headers"], {"X-MBX-APIKEY": "test-key"})
            self.assertIsNone(call.kwargs["params"])

    def setUp(self) -> None:
        self.credentials = ApiCredentials(
            binance_api_key="test-key",
            binance_api_secret="test-secret",
        )
        self.session = Mock(spec=requests.Session)

    def test_hmac_signature_matches_known_vector(self) -> None:
        signature = sign_query(
            "symbol=BTCUSDT&timestamp=1700000000123",
            "test-secret",
        )
        self.assertEqual(
            signature,
            "9010bb3849c477605c75ba1dda73f7de5e413e66f4a027e01ec8b6ac0019b3fc",
        )

    def test_public_spot_time_request_uses_production_url_and_timeout(self) -> None:
        self.session.request.return_value = _Response({"serverTime": 1700000000123})
        client = BinanceSpotMarketClient(session=self.session, timeout=7.5)

        result = client.get_server_time()

        self.assertEqual(result, {"serverTime": 1700000000123})
        self.session.request.assert_called_once_with(
            "GET",
            "https://api.binance.com/api/v3/time",
            params=None,
            timeout=7.5,
        )

    def test_product_requests_keep_numeric_fields_as_raw_strings(self) -> None:
        payload = {"symbols": [{"symbol": "BTCUSDT", "tickSize": "0.01000000"}]}
        self.session.request.return_value = _Response(payload)
        client = BinanceFuturesMarketClient(session=self.session)

        result = client.get_raw_product_info()

        self.assertIs(result, payload)
        self.assertEqual(result["symbols"][0]["tickSize"], "0.01000000")
        self.session.request.assert_called_once_with(
            "GET",
            "https://fapi.binance.com/fapi/v1/exchangeInfo",
            params=None,
            timeout=10.0,
        )

    def test_private_request_adds_timestamp_signature_and_api_key(self) -> None:
        self.session.request.return_value = _Response({"ok": True})
        client = BinanceSpotMarketClient(
            credentials=self.credentials,
            session=self.session,
            clock_ms=lambda: 1700000000123,
        )

        client.private_request("GET", "/api/v3/private-resource", {"symbol": "BTCUSDT"})

        call = self.session.request.call_args
        params = call.kwargs["params"]
        self.assertEqual(params["symbol"], "BTCUSDT")
        self.assertEqual(params["timestamp"], 1700000000123)
        self.assertEqual(
            params["signature"],
            "9010bb3849c477605c75ba1dda73f7de5e413e66f4a027e01ec8b6ac0019b3fc",
        )
        self.assertEqual(call.kwargs["headers"], {"X-MBX-APIKEY": "test-key"})

    def test_private_request_requires_exchange_credentials(self) -> None:
        client = BinanceSpotMarketClient(
            credentials=ApiCredentials(binance_api_key="only-key"),
            session=self.session,
        )
        with self.assertRaisesRegex(
            ExchangeCredentialsError,
            "BINANCE_API_SECRET",
        ):
            client.private_request("GET", "/api/v3/private-resource")
        self.session.request.assert_not_called()

    def test_timeout_is_converted_to_exchange_error(self) -> None:
        self.session.request.side_effect = requests.Timeout("network details")
        client = BinanceSpotMarketClient(session=self.session, timeout=2.0)
        with self.assertRaisesRegex(ExchangeTimeoutError, "2.0 seconds"):
            client.get_server_time()

    def test_transport_error_does_not_chain_sensitive_request_details(self) -> None:
        self.session.request.side_effect = requests.ConnectionError(
            "request failed with signature=sensitive-signature"
        )
        client = BinanceSpotMarketClient(
            credentials=self.credentials,
            session=self.session,
        )
        with self.assertRaises(ExchangeResponseError) as context:
            client.private_request("GET", "/api/v3/private-resource")
        self.assertIsNone(context.exception.__cause__)
        self.assertNotIn("sensitive-signature", str(context.exception))

    def test_http_and_api_errors_are_parsed(self) -> None:
        client = BinanceSpotMarketClient(session=self.session)
        self.session.request.return_value = _Response(
            {"code": -1003, "msg": "Too many requests"}, 429
        )
        with self.assertRaises(ExchangeHttpError) as http_context:
            client.get_server_time()
        self.assertEqual(http_context.exception.status_code, 429)
        self.assertEqual(http_context.exception.api_code, -1003)

        self.session.request.return_value = _Response(
            {"code": -1121, "msg": "Invalid symbol"}
        )
        with self.assertRaises(ExchangeApiError) as api_context:
            client.get_raw_product_info()
        self.assertEqual(api_context.exception.api_code, -1121)

        self.session.request.return_value = _InvalidJsonResponse(None, 502)
        with self.assertRaises(ExchangeHttpError) as invalid_json_context:
            client.get_server_time()
        self.assertEqual(invalid_json_context.exception.status_code, 502)

    def test_private_request_logging_does_not_expose_auth_material(self) -> None:
        stream = io.StringIO()
        logger = logging.getLogger("tests.binance.rest.redaction")
        logger.handlers.clear()
        logger.propagate = False
        logger.setLevel(logging.DEBUG)
        logger.addHandler(logging.StreamHandler(stream))
        self.session.request.return_value = _Response({"ok": True})
        client = BinanceSpotMarketClient(
            credentials=self.credentials,
            session=self.session,
            clock_ms=lambda: 1700000000123,
            logger=logger,
        )

        client.private_request("GET", "/api/v3/private-resource")

        rendered = stream.getvalue()
        self.assertIn("Binance private GET /api/v3/private-resource", rendered)
        self.assertNotIn("test-key", rendered)
        self.assertNotIn("test-secret", rendered)
        self.assertNotIn("X-MBX-APIKEY", rendered)
        self.assertNotIn("signature", rendered.lower())

    def test_base_urls_are_fixed_production_hosts(self) -> None:
        self.assertEqual(BINANCE_SPOT_BASE_URL, "https://api.binance.com")
        self.assertEqual(BINANCE_FUTURES_BASE_URL, "https://fapi.binance.com")
        combined = f"{BINANCE_SPOT_BASE_URL} {BINANCE_FUTURES_BASE_URL}".lower()
        for forbidden in ("testnet", "demo", "sandbox", "paper"):
            self.assertNotIn(forbidden, combined)

    def test_query_must_be_passed_separately_from_path(self) -> None:
        client = BinanceSpotMarketClient(session=self.session)
        with self.assertRaisesRegex(ValueError, "query"):
            client.public_request("GET", "/api/v3/time?secret=value")
        self.session.request.assert_not_called()

    def test_close_is_idempotent_and_respects_session_ownership(self) -> None:
        owned_session = Mock(spec=requests.Session)
        with patch(
            "app.exchanges.binance.rest.base_client.requests.Session",
            return_value=owned_session,
        ):
            owned_client = BinanceSpotMarketClient()
        owned_client.close()
        owned_client.close()
        owned_session.close.assert_called_once_with()

        injected_session = Mock(spec=requests.Session)
        injected_client = BinanceSpotMarketClient(session=injected_session)
        injected_client.close()
        injected_session.close.assert_not_called()


if __name__ == "__main__":
    unittest.main()
