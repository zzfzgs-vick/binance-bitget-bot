import unittest
from unittest.mock import Mock

import requests

from app.exchanges.base.exchange_errors import ExchangeCredentialsError
from app.exchanges.binance.rest.account_client import (
    BinanceFuturesAccountClient,
    BinanceSpotAccountClient,
)
from app.exchanges.bitget.rest.account_client import BitgetAccountClient
from app.infrastructure.security.credential_store import ApiCredentials


class _Response:
    status_code = 200

    def __init__(self, payload: object) -> None:
        self._payload = payload

    def json(self) -> object:
        return self._payload


class AccountRestClientTests(unittest.TestCase):
    def test_binance_account_endpoints_use_signed_production_requests(self) -> None:
        session = Mock(spec=requests.Session)
        session.request.return_value = _Response({"balances": []})
        credentials = ApiCredentials(binance_api_key="key", binance_api_secret="secret")
        spot = BinanceSpotAccountClient(credentials=credentials, session=session, clock_ms=lambda: 1)
        spot.get_account()
        self.assertEqual(session.request.call_args.args[:2], ("GET", "https://api.binance.com/api/v3/account"))

        session.request.return_value = _Response({"positions": []})
        futures = BinanceFuturesAccountClient(credentials=credentials, session=session, clock_ms=lambda: 1)
        futures.get_account()
        self.assertEqual(session.request.call_args.args[1], "https://fapi.binance.com/fapi/v3/account")
        futures.get_positions()
        self.assertEqual(session.request.call_args.args[1], "https://fapi.binance.com/fapi/v3/positionRisk")

    def test_bitget_uta_account_and_position_endpoints_are_signed(self) -> None:
        session = Mock(spec=requests.Session)
        session.request.return_value = _Response({"code": "00000", "msg": "success", "data": {}})
        credentials = ApiCredentials(
            bitget_api_key="key",
            bitget_api_secret="secret",
            bitget_api_passphrase="passphrase",
        )
        client = BitgetAccountClient(credentials=credentials, session=session, clock_ms=lambda: 1)
        client.get_settings()
        self.assertEqual(session.request.call_args.args[1], "https://api.bitget.com/api/v3/account/settings")
        client.get_account()
        self.assertEqual(session.request.call_args.args[1], "https://api.bitget.com/api/v3/account/assets")
        client.get_positions()
        self.assertEqual(session.request.call_args.args[1], "https://api.bitget.com/api/v3/position/current-position")
        self.assertEqual(session.request.call_args.kwargs["params"], {"category": "USDT-FUTURES"})

    def test_missing_credentials_fail_before_network_and_do_not_expose_values(self) -> None:
        session = Mock(spec=requests.Session)
        client = BinanceSpotAccountClient(
            credentials=ApiCredentials(binance_api_secret="super-secret-value"),
            session=session,
        )
        with self.assertRaisesRegex(ExchangeCredentialsError, "BINANCE_API_KEY") as context:
            client.get_account()
        self.assertNotIn("super-secret-value", str(context.exception))
        session.request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
