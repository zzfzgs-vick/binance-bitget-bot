"""Normalized account balances and incremental balance changes."""

from dataclasses import dataclass
from decimal import Decimal

from app.domain.enums import Exchange, MarketType
from app.domain.exceptions import AccountDataError


def _decimal(value: Decimal, field: str, *, signed: bool = False) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field} must be Decimal")
    if not value.is_finite() or (not signed and value < 0):
        raise AccountDataError(f"{field} must be a finite Decimal")


def _asset(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise AccountDataError("asset must be a non-empty string")


@dataclass(frozen=True, slots=True)
class AssetBalance:
    exchange: Exchange
    market_type: MarketType | None
    asset: str
    total: Decimal
    available: Decimal
    frozen: Decimal
    margin_balance: Decimal | None
    unrealized_pnl: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if not isinstance(self.exchange, Exchange):
            raise TypeError("exchange must be Exchange")
        if self.market_type is not None and not isinstance(
            self.market_type, MarketType
        ):
            raise TypeError("market_type must be MarketType or None")
        _asset(self.asset)
        _decimal(self.total, "total")
        _decimal(self.available, "available")
        _decimal(self.frozen, "frozen")
        if self.margin_balance is not None:
            _decimal(self.margin_balance, "margin_balance", signed=True)
        _decimal(self.unrealized_pnl, "unrealized_pnl", signed=True)


@dataclass(frozen=True, slots=True)
class BalanceUpdate:
    """Fields omitted by a private stream preserve their current value."""

    exchange: Exchange
    market_type: MarketType | None
    asset: str
    total: Decimal | None = None
    available: Decimal | None = None
    frozen: Decimal | None = None
    margin_balance: Decimal | None = None
    unrealized_pnl: Decimal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.exchange, Exchange):
            raise TypeError("exchange must be Exchange")
        if self.market_type is not None and not isinstance(
            self.market_type, MarketType
        ):
            raise TypeError("market_type must be MarketType or None")
        _asset(self.asset)
        for field in ("total", "available", "frozen"):
            value = getattr(self, field)
            if value is not None:
                _decimal(value, field)
        for field in ("margin_balance", "unrealized_pnl"):
            value = getattr(self, field)
            if value is not None:
                _decimal(value, field, signed=True)
