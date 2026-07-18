"""Immutable normalized REST snapshots and private-stream updates."""

from dataclasses import dataclass
from datetime import datetime

from app.domain.accounts.balance import AssetBalance, BalanceUpdate
from app.domain.accounts.futures_position import FuturesPosition
from app.domain.enums import Exchange, MarketType
from app.domain.exceptions import AccountDataError


def _metadata(
    event_time: datetime,
    received_time: datetime,
    sequence: int,
) -> None:
    if event_time.tzinfo is None or received_time.tzinfo is None:
        raise AccountDataError("account event times must be timezone-aware")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        raise AccountDataError("sequence must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    exchange: Exchange
    scope: MarketType | None
    balances: tuple[AssetBalance, ...]
    positions: tuple[FuturesPosition, ...]
    event_time: datetime
    received_time: datetime
    sequence: int
    replace_balances: bool = True
    replace_positions: bool = True

    def __post_init__(self) -> None:
        _metadata(self.event_time, self.received_time, self.sequence)
        if any(balance.exchange is not self.exchange for balance in self.balances):
            raise AccountDataError("snapshot balance exchange mismatch")
        if any(
            position.instrument.exchange is not self.exchange
            for position in self.positions
        ):
            raise AccountDataError("snapshot position exchange mismatch")
        if self.scope is not None and any(
            balance.market_type is not self.scope for balance in self.balances
        ):
            raise AccountDataError("snapshot balance scope mismatch")
        if self.scope is not None and any(
            position.instrument.market_type is not self.scope
            for position in self.positions
        ):
            raise AccountDataError("snapshot position scope mismatch")


@dataclass(frozen=True, slots=True)
class AccountUpdate:
    exchange: Exchange
    scope: MarketType | None
    balances: tuple[BalanceUpdate, ...]
    positions: tuple[FuturesPosition, ...]
    event_time: datetime
    received_time: datetime
    sequence: int

    def __post_init__(self) -> None:
        _metadata(self.event_time, self.received_time, self.sequence)
        if any(balance.exchange is not self.exchange for balance in self.balances):
            raise AccountDataError("update balance exchange mismatch")
        if any(
            position.instrument.exchange is not self.exchange
            for position in self.positions
        ):
            raise AccountDataError("update position exchange mismatch")
        if self.scope is not None and any(
            balance.market_type is not self.scope for balance in self.balances
        ):
            raise AccountDataError("update balance scope mismatch")
        if self.scope is not None and any(
            position.instrument.market_type is not self.scope
            for position in self.positions
        ):
            raise AccountDataError("update position scope mismatch")


@dataclass(frozen=True, slots=True)
class AccountState:
    exchange: Exchange
    balances: tuple[AssetBalance, ...]
    positions: tuple[FuturesPosition, ...]
