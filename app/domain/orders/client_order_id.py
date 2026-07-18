"""Cross-exchange client order identifier."""

from dataclasses import dataclass
import re

from app.domain.exceptions import OrderDataError


_SAFE_ID = re.compile(r"^[.0-9A-Za-z_:/-]+$")


@dataclass(frozen=True, slots=True)
class ClientOrderId:
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise TypeError("client order id must be str")
        if not 1 <= len(self.value) <= 32:
            raise OrderDataError("client order id must contain 1 to 32 characters")
        if _SAFE_ID.fullmatch(self.value) is None:
            raise OrderDataError("client order id contains an unsupported character")

    def __str__(self) -> str:
        return self.value
