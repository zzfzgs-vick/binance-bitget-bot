"""In-memory API credentials loaded only from environment variables."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os


CREDENTIAL_ENVIRONMENT_VARIABLES = (
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "BITGET_API_KEY",
    "BITGET_API_SECRET",
    "BITGET_API_PASSPHRASE",
)


@dataclass(frozen=True, slots=True, repr=False)
class ApiCredentials:
    binance_api_key: str = ""
    binance_api_secret: str = ""
    bitget_api_key: str = ""
    bitget_api_secret: str = ""
    bitget_api_passphrase: str = ""

    def missing_variables(self) -> tuple[str, ...]:
        values = self._by_environment_variable()
        return tuple(name for name, value in values.items() if not value.strip())

    def is_complete(self) -> bool:
        return not self.missing_variables()

    def secret_values(self) -> tuple[str, ...]:
        return tuple(
            value
            for value in self._by_environment_variable().values()
            if value.strip()
        )

    def _by_environment_variable(self) -> dict[str, str]:
        return dict(zip(CREDENTIAL_ENVIRONMENT_VARIABLES, self._values(), strict=True))

    def _values(self) -> tuple[str, ...]:
        return (
            self.binance_api_key,
            self.binance_api_secret,
            self.bitget_api_key,
            self.bitget_api_secret,
            self.bitget_api_passphrase,
        )

    def __repr__(self) -> str:
        return (
            "ApiCredentials("
            f"complete={self.is_complete()}, "
            f"missing_count={len(self.missing_variables())})"
        )


def load_api_credentials(
    environ: Mapping[str, str] | None = None,
) -> ApiCredentials:
    """Read credentials from the process environment without persisting them."""
    values = os.environ if environ is None else environ
    return ApiCredentials(*(values.get(name, "") for name in CREDENTIAL_ENVIRONMENT_VARIABLES))
