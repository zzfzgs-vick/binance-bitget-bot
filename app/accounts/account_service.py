"""Deterministic REST snapshot and private-stream state synchronization."""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from enum import Enum

from app.domain.accounts.account_snapshot import (
    AccountSnapshot,
    AccountState,
    AccountUpdate,
)
from app.domain.accounts.balance import AssetBalance, BalanceUpdate
from app.domain.accounts.futures_position import FuturesPosition, PositionSide
from app.domain.enums import Exchange, MarketType
from app.domain.exceptions import AccountDataError


class SyncResult(str, Enum):
    APPLIED = "applied"
    DUPLICATE = "duplicate"
    OUT_OF_ORDER = "out_of_order"
    STALE = "stale"
    SNAPSHOT_REQUIRED = "snapshot_required"


class AccountStateStore:
    """Own synchronization policy; adapters only produce normalized events."""

    def __init__(
        self,
        exchange: Exchange,
        *,
        max_update_age: timedelta | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if max_update_age is not None and max_update_age <= timedelta(0):
            raise ValueError("max_update_age must be positive")
        self._exchange = exchange
        self._max_update_age = max_update_age
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._balances: dict[tuple[MarketType | None, str], AssetBalance] = {}
        self._positions: dict[tuple[str, PositionSide], FuturesPosition] = {}
        self._balance_cursors: dict[MarketType | None, int] = {}
        self._position_cursors: dict[MarketType | None, int] = {}

    @property
    def state(self) -> AccountState:
        balances = tuple(
            sorted(
                self._balances.values(),
                key=lambda value: (
                    value.market_type.value if value.market_type else "",
                    value.asset,
                ),
            )
        )
        positions = tuple(
            sorted(
                self._positions.values(),
                key=lambda value: (value.instrument.raw_symbol, value.side.value),
            )
        )
        return AccountState(self._exchange, balances, positions)

    def apply_snapshot(self, snapshot: AccountSnapshot) -> SyncResult:
        components = (
            snapshot.replace_balances,
            snapshot.replace_positions,
        )
        decision = self._decision(
            snapshot.exchange,
            snapshot.scope,
            snapshot.sequence,
            snapshot.event_time,
            False,
            components,
        )
        if decision is not SyncResult.APPLIED:
            return decision
        if snapshot.replace_balances:
            self._remove_balances(snapshot.scope)
        if snapshot.replace_positions:
            self._remove_positions(snapshot.scope)
        for balance in snapshot.balances:
            self._balances[(balance.market_type, balance.asset)] = balance
        for position in snapshot.positions:
            self._apply_position(position)
        self._advance_cursors(snapshot.scope, snapshot.sequence, components)
        return SyncResult.APPLIED

    def apply(self, event: AccountSnapshot | AccountUpdate) -> SyncResult:
        if isinstance(event, AccountSnapshot):
            return self.apply_snapshot(event)
        if isinstance(event, AccountUpdate):
            return self.apply_update(event)
        raise TypeError("event must be AccountSnapshot or AccountUpdate")

    def apply_update(self, update: AccountUpdate) -> SyncResult:
        components = (bool(update.balances), bool(update.positions))
        if not any(components):
            components = (True, True)
        decision = self._decision(
            update.exchange,
            update.scope,
            update.sequence,
            update.event_time,
            True,
            components,
        )
        if decision is not SyncResult.APPLIED:
            return decision
        for change in update.balances:
            self._apply_balance(change)
        for position in update.positions:
            self._apply_position(position)
        self._advance_cursors(update.scope, update.sequence, components)
        return SyncResult.APPLIED

    def _decision(
        self,
        exchange: Exchange,
        scope: MarketType | None,
        sequence: int,
        event_time: datetime,
        require_snapshot: bool,
        components: tuple[bool, bool],
    ) -> SyncResult:
        if exchange is not self._exchange:
            raise AccountDataError("account event exchange does not match store")
        if (
            self._max_update_age is not None
            and self._clock() - event_time > self._max_update_age
        ):
            return SyncResult.STALE
        cursors = tuple(
            cursor
            for enabled, cursor in zip(
                components,
                (
                    self._balance_cursors.get(scope),
                    self._position_cursors.get(scope),
                ),
                strict=True,
            )
            if enabled
        )
        if require_snapshot and any(cursor is None for cursor in cursors):
            return SyncResult.SNAPSHOT_REQUIRED
        known = tuple(cursor for cursor in cursors if cursor is not None)
        if known and all(sequence == cursor for cursor in known):
            return SyncResult.DUPLICATE
        if any(sequence < cursor for cursor in known):
            return SyncResult.OUT_OF_ORDER
        return SyncResult.APPLIED

    def _advance_cursors(
        self,
        scope: MarketType | None,
        sequence: int,
        components: tuple[bool, bool],
    ) -> None:
        if components[0]:
            self._balance_cursors[scope] = sequence
        if components[1]:
            self._position_cursors[scope] = sequence

    def _remove_balances(self, scope: MarketType | None) -> None:
        if scope is None:
            self._balances.clear()
            return
        for key in tuple(self._balances):
            if key[0] is scope:
                del self._balances[key]

    def _remove_positions(self, scope: MarketType | None) -> None:
        if scope is None:
            self._positions.clear()
            return
        for key, position in tuple(self._positions.items()):
            if position.instrument.market_type is scope:
                del self._positions[key]

    def _apply_balance(self, change: BalanceUpdate) -> None:
        key = (change.market_type, change.asset)
        current = self._balances.get(key)
        if current is None and any(
            value is None for value in (change.total, change.available, change.frozen)
        ):
            raise AccountDataError(
                f"partial balance update for unknown asset {change.asset!r}"
            )
        self._balances[key] = AssetBalance(
            exchange=change.exchange,
            market_type=change.market_type,
            asset=change.asset,
            total=change.total if change.total is not None else current.total,
            available=(
                change.available if change.available is not None else current.available
            ),
            frozen=change.frozen if change.frozen is not None else current.frozen,
            margin_balance=(
                change.margin_balance
                if change.margin_balance is not None
                else current.margin_balance
            ),
            unrealized_pnl=(
                change.unrealized_pnl
                if change.unrealized_pnl is not None
                else current.unrealized_pnl
            ),
        )

    def _apply_position(self, position: FuturesPosition) -> None:
        symbol = position.instrument.raw_symbol
        if position.side is PositionSide.FLAT:
            for key in tuple(self._positions):
                if key[0] == symbol:
                    del self._positions[key]
            return
        key = (symbol, position.side)
        if position.is_empty:
            self._positions.pop(key, None)
        else:
            self._positions[key] = position
