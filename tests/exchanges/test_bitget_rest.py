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
from app.exchanges.bitget.constants import BITGET_BASE_URL
from app.exchanges.bitget.rest.futures_market_client import BitgetFuturesMarketClient
from app.exchanges.bitget.rest.spot_market_client import BitgetSpotMarketClient
from app.exchanges.bitget.signer import build_prehash, sign_prehash
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


class BitgetRestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.credentials = ApiCredentials(
            bitget_api_key="test-key",
            bitget_api_secret="test-secret",
            bitget_api_passphrase="test-passphrase",
        )
        self.session = Mock(spec=requests.Session)

    def test_prehash_and_hmac_signature_match_known_vector(self) -> None:
        prehash = build_prehash(
            "1700000000123",
            "get",
            "/api/v3/account/assets",
            "coin=USDT",
        )
        self.assertEqual(
            prehash,
            "1700000000123GET/api/v3/account/assets?coin=USDT",
        )
        self.assertEqual(
            sign_prehash(prehash, "test-secret"),
            "esBVuZVNDlWB4vNj0lNznBHigbn9kaOzS+glV+ytARU=",
        )

    def test_public_time_request_uses_production_url_and_timeout(self) -> None:
        payload = {
            "code": "00000",
            "msg": "success",
            "data": {"serverTime": "1700000000123"},
        }
        self.session.request.return_value = _Response(payload)
        client = BitgetSpotMarketClient(session=self.session, timeout=6.0)

        result = client.get_server_time()

        self.assertIs(result, payload)
        self.assertEqual(result["data"]["serverTime"], "1700000000123")
        self.session.request.assert_called_once_with(
            "GET",
            "https://api.bitget.com/api/v2/public/time",
            params=None,
            timeout=6.0,
        )

    def test_spot_and_futures_product_requests_use_required_categories(self) -> None:
        self.session.request.return_value = _Response(
            {"code": "00000", "msg": "success", "data": []}
        )
        spot = BitgetSpotMarketClient(session=self.session)
        futures = BitgetFuturesMarketClient(session=self.session)

        spot.get_raw_product_info()
        futures.get_raw_product_info()

        first, second = self.session.request.call_args_list
        self.assertEqual(first.kwargs["params"], {"category": "SPOT"})
        self.assertEqual(second.kwargs["params"], {"category": "USDT-FUTURES"})
        self.assertEqual(first.args[1], "https://api.bitget.com/api/v3/market/instruments")
        self.assertEqual(second.args[1], "https://api.bitget.com/api/v3/market/instruments")

    def test_private_get_request_builds_sorted_query_and_auth_headers(self) -> None:
        self.session.request.return_value = _Response(
            {"code": "00000", "msg": "success", "data": {}}
        )
        client = BitgetSpotMarketClient(
            credentials=self.credentials,
            session=self.session,
            clock_ms=lambda: 1700000000123,
        )

        client.private_request(
            "GET",
            "/api/v3/account/assets",
            params={"coin": "USDT"},
        )

        call = self.session.request.call_args
        self.assertEqual(call.kwargs["params"], {"coin": "USDT"})
        self.assertEqual(
            call.kwargs["headers"],
            {
                "ACCESS-KEY": "test-key",
                "ACCESS-SIGN": "esBVuZVNDlWB4vNj0lNznBHigbn9kaOzS+glV+ytARU=",
                "ACCESS-TIMESTAMP": "1700000000123",
                "ACCESS-PASSPHRASE": "test-passphrase",
                "Content-Type": "application/json",
            },
        )

    def test_private_post_signs_and_sends_the_same_compact_json_body(self) -> None:
        self.session.request.return_value = _Response(
            {"code": "00000", "msg": "success", "data": {}}
        )
        client = BitgetSpotMarketClient(
            credentials=self.credentials,
            session=self.session,
            clock_ms=lambda: 1700000000123,
        )

        client.private_request(
            "POST",
            "/api/v3/private-resource",
            body={"symbol": "BTCUSDT", "size": "1.25"},
        )

        call = self.session.request.call_args
        self.assertEqual(call.kwargs["data"], '{"symbol":"BTCUSDT","size":"1.25"}')
        self.assertEqual(call.kwargs["headers"]["Content-Type"], "application/json")

    def test_private_request_requires_all_bitget_credentials(self) -> None:
        client = BitgetSpotMarketClient(
            credentials=ApiCredentials(
                bitget_api_key="key",
                bitget_api_secret="secret",
            ),
            session=self.session,
        )
        with self.assertRaisesRegex(
            ExchangeCredentialsError,
            "BITGET_API_PASSPHRASE",
        ):
            client.private_request("GET", "/api/v3/private-resource")
        self.session.request.assert_not_called()

    def test_timeout_http_and_api_errors_are_converted(self) -> None:
        client = BitgetSpotMarketClient(session=self.session, timeout=3.0)
        self.session.request.side_effect = requests.Timeout("network details")
        with self.assertRaisesRegex(ExchangeTimeoutError, "3.0 seconds"):
            client.get_server_time()

        self.session.request.side_effect = None
        self.session.request.return_value = _Response(
            {"code": "40009", "msg": "sign signature error"}, 401
        )
        with self.assertRaises(ExchangeHttpError) as http_context:
            client.get_server_time()
        self.assertEqual(http_context.exception.status_code, 401)
        self.assertEqual(http_context.exception.api_code, "40009")

        self.session.request.return_value = _Response(
            {"code": "40015", "msg": "system is abnormal"}
        )
        with self.assertRaises(ExchangeApiError) as api_context:
            client.get_server_time()
        self.assertEqual(api_context.exception.api_code, "40015")

        self.session.request.return_value = _InvalidJsonResponse(None, 503)
        with self.assertRaises(ExchangeHttpError) as invalid_json_context:
            client.get_server_time()
        self.assertEqual(invalid_json_context.exception.status_code, 503)

    def test_transport_error_does_not_chain_sensitive_request_details(self) -> None:
        self.session.request.side_effect = requests.ConnectionError(
            "request failed with ACCESS-SIGN=sensitive-signature"
        )
        client = BitgetSpotMarketClient(
            credentials=self.credentials,
            session=self.session,
        )
        with self.assertRaises(ExchangeResponseError) as context:
            client.private_request("GET", "/api/v3/private-resource")
        self.assertIsNone(context.exception.__cause__)
        self.assertNotIn("sensitive-signature", str(context.exception))

    def test_private_request_logging_does_not_expose_auth_material(self) -> None:
        stream = io.StringIO()
        logger = logging.getLogger("tests.bitget.rest.redaction")
        logger.handlers.clear()
        logger.propagate = False
        logger.setLevel(logging.DEBUG)
        logger.addHandler(logging.StreamHandler(stream))
        self.session.request.return_value = _Response(
            {"code": "00000", "msg": "success", "data": {}}
        )
        client = BitgetSpotMarketClient(
            credentials=self.credentials,
            session=self.session,
            clock_ms=lambda: 1700000000123,
            logger=logger,
        )

        client.private_request("GET", "/api/v3/private-resource")

        rendered = stream.getvalue()
        self.assertIn("Bitget private GET /api/v3/private-resource", rendered)
        for secret in ("test-key", "test-secret", "test-passphrase", "ACCESS-SIGN"):
            self.assertNotIn(secret, rendered)

    def test_base_url_is_fixed_production_host(self) -> None:
        self.assertEqual(BITGET_BASE_URL, "https://api.bitget.com")
        for forbidden in ("testnet", "demo", "sandbox", "paper"):
            self.assertNotIn(forbidden, BITGET_BASE_URL.lower())

    def test_query_must_be_passed_separately_from_path(self) -> None:
        client = BitgetSpotMarketClient(session=self.session)
        with self.assertRaisesRegex(ValueError, "query"):
            client.public_request("GET", "/api/v2/public/time?secret=value")
        self.session.request.assert_not_called()

    def test_missing_api_result_code_is_rejected(self) -> None:
        self.session.request.return_value = _Response({"data": {}})
        client = BitgetSpotMarketClient(session=self.session)
        with self.assertRaisesRegex(ExchangeResponseError, "result code"):
            client.get_server_time()

    def test_close_is_idempotent_and_respects_session_ownership(self) -> None:
        owned_session = Mock(spec=requests.Session)
        with patch(
            "app.exchanges.bitget.rest.base_client.requests.Session",
            return_value=owned_session,
        ):
            owned_client = BitgetSpotMarketClient()
        owned_client.close()
        owned_client.close()
        owned_session.close.assert_called_once_with()

        injected_session = Mock(spec=requests.Session)
        injected_client = BitgetSpotMarketClient(session=injected_session)
        injected_client.close()
        injected_session.close.assert_not_called()


if __name__ == "__main__":
    unittest.main()
