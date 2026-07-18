from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from app.accounts.account_service import AccountStateStore, SyncResult
from app.domain.accounts.account_snapshot import AccountSnapshot, AccountUpdate
from app.domain.accounts.balance import AssetBalance, BalanceUpdate
from app.domain.accounts.futures_position import (
    FuturesPosition,
    MarginMode,
    PositionMode,
    PositionSide,
)
from app.domain.enums import Exchange, MarketType, TradingStatus
from app.domain.exceptions import AccountDataError
from app.domain.instruments.instrument import Instrument, TradingRules


NOW = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)


def _instrument() -> Instrument:
    return Instrument(
        exchange=Exchange.BINANCE,
        market_type=MarketType.USDT_PERPETUAL,
        raw_symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        settlement_asset="USDT",
        rules=TradingRules(
            tick_size=Decimal("0.1"),
            quantity_step=Decimal("0.001"),
            minimum_quantity=Decimal("0.001"),
            maximum_quantity=Decimal("100"),
            minimum_notional=Decimal("5"),
            contract_multiplier=Decimal("1"),
        ),
        status=TradingStatus.TRADING,
        raw_status="TRADING",
    )


class AccountDomainTests(unittest.TestCase):
    def test_models_require_decimal_values_and_enforce_empty_positions(self) -> None:
        balance = AssetBalance(
            exchange=Exchange.BINANCE,
            market_type=MarketType.SPOT,
            asset="USDT",
            total=Decimal("12.30000000"),
            available=Decimal("10.10000000"),
            frozen=Decimal("2.20000000"),
            margin_balance=None,
        )
        self.assertIsInstance(balance.total, Decimal)
        with self.assertRaises(TypeError):
            AssetBalance(
                exchange=Exchange.BINANCE,
                market_type=MarketType.SPOT,
                asset="USDT",
                total=1.0,  # type: ignore[arg-type]
                available=Decimal("1"),
                frozen=Decimal("0"),
                margin_balance=None,
            )

        empty = FuturesPosition(
            instrument=_instrument(),
            quantity=Decimal("0"),
            side=PositionSide.FLAT,
            mode=PositionMode.ONE_WAY,
            average_open_price=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            margin_mode=MarginMode.CROSS,
        )
        self.assertTrue(empty.is_empty)
        with self.assertRaisesRegex(AccountDataError, "FLAT"):
            FuturesPosition(
                instrument=_instrument(),
                quantity=Decimal("1"),
                side=PositionSide.FLAT,
                mode=PositionMode.ONE_WAY,
                average_open_price=Decimal("100"),
                unrealized_pnl=Decimal("0"),
                margin_mode=MarginMode.CROSS,
            )

    def test_rest_snapshot_then_websocket_delta_merges_by_scope(self) -> None:
        store = AccountStateStore(Exchange.BINANCE)
        spot = AssetBalance(
            Exchange.BINANCE,
            MarketType.SPOT,
            "USDT",
            Decimal("100"),
            Decimal("90"),
            Decimal("10"),
            None,
        )
        snapshot = AccountSnapshot(
            Exchange.BINANCE,
            MarketType.SPOT,
            (spot,),
            (),
            NOW,
            NOW,
            100,
        )
        self.assertIs(store.apply_snapshot(snapshot), SyncResult.APPLIED)

        update = AccountUpdate(
            Exchange.BINANCE,
            MarketType.SPOT,
            (
                BalanceUpdate(
                    Exchange.BINANCE,
                    MarketType.SPOT,
                    "USDT",
                    total=Decimal("120"),
                    available=Decimal("115"),
                    frozen=Decimal("5"),
                ),
            ),
            (),
            NOW + timedelta(milliseconds=1),
            NOW + timedelta(milliseconds=1),
            101,
        )
        self.assertIs(store.apply_update(update), SyncResult.APPLIED)
        self.assertEqual(store.state.balances[0].total, Decimal("120"))
        self.assertIs(store.apply_update(update), SyncResult.DUPLICATE)

        older = AccountUpdate(
            Exchange.BINANCE,
            MarketType.SPOT,
            (),
            (),
            NOW,
            NOW,
            99,
        )
        self.assertIs(store.apply_update(older), SyncResult.OUT_OF_ORDER)

    def test_update_before_snapshot_and_expired_update_are_explicit(self) -> None:
        update = AccountUpdate(
            Exchange.BINANCE,
            MarketType.SPOT,
            (),
            (),
            NOW,
            NOW,
            1,
        )
        store = AccountStateStore(Exchange.BINANCE)
        self.assertIs(store.apply_update(update), SyncResult.SNAPSHOT_REQUIRED)

        store = AccountStateStore(
            Exchange.BINANCE,
            max_update_age=timedelta(seconds=5),
            clock=lambda: NOW + timedelta(seconds=10),
        )
        snapshot = AccountSnapshot(
            Exchange.BINANCE,
            MarketType.SPOT,
            (),
            (),
            NOW,
            NOW,
            1,
        )
        self.assertIs(store.apply_snapshot(snapshot), SyncResult.STALE)

    def test_zero_position_update_removes_one_way_position(self) -> None:
        instrument = _instrument()
        position = FuturesPosition(
            instrument,
            Decimal("1.5"),
            PositionSide.LONG,
            PositionMode.ONE_WAY,
            Decimal("60000"),
            Decimal("1.25"),
            MarginMode.CROSS,
        )
        store = AccountStateStore(Exchange.BINANCE)
        store.apply_snapshot(
            AccountSnapshot(
                Exchange.BINANCE,
                MarketType.USDT_PERPETUAL,
                (),
                (position,),
                NOW,
                NOW,
                1,
            )
        )
        flat = FuturesPosition(
            instrument,
            Decimal("0"),
            PositionSide.FLAT,
            PositionMode.ONE_WAY,
            Decimal("0"),
            Decimal("0"),
            MarginMode.CROSS,
        )
        store.apply_update(
            AccountUpdate(
                Exchange.BINANCE,
                MarketType.USDT_PERPETUAL,
                (),
                (flat,),
                NOW + timedelta(milliseconds=1),
                NOW + timedelta(milliseconds=1),
                2,
            )
        )
        self.assertEqual(store.state.positions, ())

    def test_balance_and_position_snapshots_have_independent_cursors(self) -> None:
        instrument = _instrument()
        store = AccountStateStore(Exchange.BINANCE)
        balance_snapshot = AccountSnapshot(
            Exchange.BINANCE,
            MarketType.USDT_PERPETUAL,
            (),
            (),
            NOW + timedelta(milliseconds=2),
            NOW + timedelta(milliseconds=2),
            102,
            replace_positions=False,
        )
        position_snapshot = AccountSnapshot(
            Exchange.BINANCE,
            MarketType.USDT_PERPETUAL,
            (),
            (
                FuturesPosition(
                    instrument,
                    Decimal("1"),
                    PositionSide.LONG,
                    PositionMode.ONE_WAY,
                    Decimal("60000"),
                    Decimal("0"),
                    MarginMode.CROSS,
                ),
            ),
            NOW + timedelta(milliseconds=1),
            NOW + timedelta(milliseconds=2),
            101,
            replace_balances=False,
        )
        self.assertIs(store.apply_snapshot(balance_snapshot), SyncResult.APPLIED)
        self.assertIs(store.apply_snapshot(position_snapshot), SyncResult.APPLIED)
        self.assertEqual(len(store.state.positions), 1)

    def test_empty_hedge_leg_removes_only_its_direction(self) -> None:
        instrument = _instrument()
        store = AccountStateStore(Exchange.BINANCE)
        long_position = FuturesPosition(
            instrument,
            Decimal("1"),
            PositionSide.LONG,
            PositionMode.HEDGE,
            Decimal("60000"),
            Decimal("0"),
            MarginMode.CROSS,
        )
        short_position = FuturesPosition(
            instrument,
            Decimal("2"),
            PositionSide.SHORT,
            PositionMode.HEDGE,
            Decimal("61000"),
            Decimal("0"),
            MarginMode.CROSS,
        )
        store.apply_snapshot(
            AccountSnapshot(
                Exchange.BINANCE,
                MarketType.USDT_PERPETUAL,
                (),
                (long_position, short_position),
                NOW,
                NOW,
                1,
            )
        )
        empty_long = FuturesPosition(
            instrument,
            Decimal("0"),
            PositionSide.LONG,
            PositionMode.HEDGE,
            Decimal("0"),
            Decimal("0"),
            MarginMode.CROSS,
        )
        store.apply_update(
            AccountUpdate(
                Exchange.BINANCE,
                MarketType.USDT_PERPETUAL,
                (),
                (empty_long,),
                NOW + timedelta(milliseconds=1),
                NOW + timedelta(milliseconds=1),
                2,
            )
        )
        self.assertEqual(
            tuple(position.side for position in store.state.positions),
            (PositionSide.SHORT,),
        )


if __name__ == "__main__":
    unittest.main()
