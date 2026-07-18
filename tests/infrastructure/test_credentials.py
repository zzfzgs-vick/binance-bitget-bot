from dataclasses import FrozenInstanceError
import unittest


class ApiCredentialTests(unittest.TestCase):
    def test_credentials_load_from_environment_and_report_completeness(self) -> None:
        from app.infrastructure.security.credential_store import load_api_credentials

        credentials = load_api_credentials(
            {
                "BINANCE_API_KEY": "binance-key",
                "BINANCE_API_SECRET": "binance-secret",
                "BITGET_API_KEY": "bitget-key",
                "BITGET_API_SECRET": "bitget-secret",
            }
        )

        self.assertFalse(credentials.is_complete())
        self.assertEqual(credentials.missing_variables(), ("BITGET_API_PASSPHRASE",))

        with self.assertRaises(FrozenInstanceError):
            credentials.binance_api_key = "replacement"

    def test_credentials_repr_never_contains_secret_values(self) -> None:
        from app.infrastructure.security.credential_store import load_api_credentials

        values = {
            "BINANCE_API_KEY": "binance-key-visible-only-in-test",
            "BINANCE_API_SECRET": "binance-secret-visible-only-in-test",
            "BITGET_API_KEY": "bitget-key-visible-only-in-test",
            "BITGET_API_SECRET": "bitget-secret-visible-only-in-test",
            "BITGET_API_PASSPHRASE": "bitget-passphrase-visible-only-in-test",
        }

        credentials = load_api_credentials(values)
        rendered = repr(credentials)

        self.assertTrue(credentials.is_complete())
        for secret in values.values():
            self.assertNotIn(secret, rendered)
        self.assertEqual(rendered, "ApiCredentials(complete=True, missing_count=0)")

    def test_whitespace_only_credentials_are_incomplete(self) -> None:
        from app.infrastructure.security.credential_store import (
            CREDENTIAL_ENVIRONMENT_VARIABLES,
            load_api_credentials,
        )

        credentials = load_api_credentials(
            {name: "   " for name in CREDENTIAL_ENVIRONMENT_VARIABLES}
        )

        self.assertFalse(credentials.is_complete())
        self.assertEqual(
            credentials.missing_variables(),
            CREDENTIAL_ENVIRONMENT_VARIABLES,
        )
        self.assertEqual(credentials.secret_values(), ())


if __name__ == "__main__":
    unittest.main()
