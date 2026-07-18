from datetime import datetime, timezone
from decimal import Decimal
import unittest

from app.domain.accounts.account_snapshot import AccountSnapshot, AccountUpdate
from app.domain.accounts.futures_position import (
    MarginMode,
    PositionMode,
    PositionSide,
)
from app.domain.enums import Exchange, MarketType, TradingStatus
from app.domain.exceptions import AccountDataError
from app.domain.instruments.instrument import Instrument, TradingRules
from app.exchanges.binance.mappers.account_mapper import (
    parse_futures_account,
    parse_private_message as parse_binance_private,
    parse_spot_account,
)
from app.exchanges.bitget.mappers.account_mapper import (
    private_subscriptions,
    parse_account,
    parse_positions,
    parse_private_message as parse_bitget_private,
)


RECEIVED = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)


def _instrument(exchange: Exchange) -> Instrument:
    return Instrument(
        exchange=exchange,
        market_type=MarketType.USDT_PERPETUAL,
        raw_symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        settlement_asset="USDT",
        rules=TradingRules(
            Decimal("0.1"),
            Decimal("0.001"),
            Decimal("0.001"),
            Decimal("100"),
            Decimal("5"),
            Decimal("1"),
        ),
        status=TradingStatus.TRADING,
        raw_status="TRADING",
    )


class BinanceAccountMapperTests(unittest.TestCase):
    def test_spot_rest_balance_strings_become_decimal(self) -> None:
        snapshot = parse_spot_account(
            {
                "updateTime": 1720000000000,
                "balances": [
                    {"asset": "USDT", "free": "10.10000000", "locked": "2.20000000"}
                ],
            },
            RECEIVED,
            known_assets={"USDT"},
        )
        (balance,) = snapshot.balances
        self.assertEqual(balance.total, Decimal("12.30000000"))
        self.assertEqual(balance.available, Decimal("10.10000000"))
        self.assertEqual(balance.frozen, Decimal("2.20000000"))
        self.assertIsInstance(balance.total, Decimal)
        with self.assertRaisesRegex(AccountDataError, "string"):
            parse_spot_account(
                {
                    "updateTime": 1720000000000,
                    "balances": [
                        {"asset": "USDT", "free": 10.1, "locked": "0"}
                    ],
                },
                RECEIVED,
                known_assets={"USDT"},
            )

    def test_futures_rest_balances_positions_modes_and_empty(self) -> None:
        instrument = _instrument(Exchange.BINANCE)
        snapshot = parse_futures_account(
            {
                "assets": [
                    {
                        "asset": "USDT",
                        "walletBalance": "120.5",
                        "availableBalance": "100.25",
                        "marginBalance": "121.75",
                        "updateTime": 1720000000000,
                    }
                ]
            },
            [
                {
                    "symbol": "BTCUSDT",
                    "positionSide": "BOTH",
                    "positionAmt": "-0.010",
                    "entryPrice": "62000.5",
                    "unRealizedProfit": "1.250",
                    "marginType": "cross",
                    "updateTime": 1720000000001,
                },
                {
                    "symbol": "BTCUSDT",
                    "positionSide": "BOTH",
                    "positionAmt": "0",
                    "entryPrice": "0",
                    "unRealizedProfit": "0",
                    "marginType": "cross",
                    "updateTime": 1720000000001,
                },
            ],
            {"BTCUSDT": instrument},
            RECEIVED,
            known_assets={"USDT"},
        )
        self.assertEqual(snapshot.balances[0].margin_balance, Decimal("121.75"))
        self.assertEqual(snapshot.positions[0].side, PositionSide.SHORT)
        self.assertEqual(snapshot.positions[0].mode, PositionMode.ONE_WAY)
        self.assertEqual(snapshot.positions[0].margin_mode, MarginMode.CROSS)
        self.assertEqual(snapshot.positions[0].quantity, Decimal("0.010"))
        self.assertEqual(snapshot.positions[1].side, PositionSide.FLAT)

    def test_spot_and_futures_private_updates_are_normalized(self) -> None:
        spot = parse_binance_private(
            {
                "subscriptionId": 0,
                "event": {
                    "e": "outboundAccountPosition",
                    "E": 1720000000002,
                    "u": 1720000000001,
                    "B": [{"a": "USDT", "f": "3.1", "l": "0.2"}],
                },
            },
            {},
            RECEIVED,
            known_assets={"USDT"},
        )
        self.assertEqual(spot.balances[0].total, Decimal("3.3"))

        instrument = _instrument(Exchange.BINANCE)
        futures = parse_binance_private(
            {
                "e": "ACCOUNT_UPDATE",
                "E": 1720000000004,
                "T": 1720000000003,
                "a": {
                    "m": "ORDER",
                    "B": [{"a": "USDT", "wb": "101.5", "cw": "100.0", "bc": "1.5"}],
                    "P": [
                        {
                            "s": "BTCUSDT",
                            "pa": "0.2",
                            "ep": "62000",
                            "up": "2.5",
                            "mt": "isolated",
                            "iw": "20",
                            "ps": "LONG",
                        }
                    ],
                },
            },
            {"BTCUSDT": instrument},
            RECEIVED,
            known_assets={"USDT"},
        )
        self.assertEqual(futures.balances[0].total, Decimal("101.5"))
        self.assertIsNone(futures.balances[0].available)
        self.assertEqual(futures.positions[0].mode, PositionMode.HEDGE)
        self.assertEqual(futures.positions[0].margin_mode, MarginMode.ISOLATED)

    def test_unknown_asset_symbol_and_enum_are_rejected(self) -> None:
        with self.assertRaisesRegex(AccountDataError, "unknown asset"):
            parse_spot_account(
                {"updateTime": 1, "balances": [{"asset": "XYZ", "free": "1", "locked": "0"}]},
                RECEIVED,
                known_assets={"USDT"},
            )
        with self.assertRaisesRegex(AccountDataError, "unknown symbol"):
            parse_futures_account(
                {"assets": []},
                [{"symbol": "UNKNOWN", "positionSide": "BOTH", "positionAmt": "1", "entryPrice": "1", "unRealizedProfit": "0", "marginType": "cross", "updateTime": 1}],
                {},
                RECEIVED,
            )
        instrument = _instrument(Exchange.BINANCE)
        with self.assertRaisesRegex(AccountDataError, "unknown position direction"):
            parse_futures_account(
                {"assets": []},
                [
                    {
                        "symbol": "BTCUSDT",
                        "positionSide": "SIDEWAYS",
                        "positionAmt": "1",
                        "entryPrice": "1",
                        "unRealizedProfit": "0",
                        "marginType": "cross",
                        "updateTime": 1,
                    }
                ],
                {"BTCUSDT": instrument},
                RECEIVED,
            )


class BitgetAccountMapperTests(unittest.TestCase):
    def test_uta_rest_account_and_positions_are_normalized(self) -> None:
        instrument = _instrument(Exchange.BITGET)
        account = parse_account(
            {
                "requestTime": 1720000000000,
                "data": {
                    "assets": [
                        {"coin": "USDT", "balance": "50.5", "available": "45.2", "locked": "5.3", "equity": "51.25"}
                    ]
                },
            },
            RECEIVED,
            known_assets={"USDT"},
        )
        self.assertIsNone(account.scope)
        self.assertEqual(account.balances[0].margin_balance, Decimal("51.25"))

        positions = parse_positions(
            {
                "requestTime": 1720000000001,
                "data": {
                    "list": [
                        {
                            "symbol": "BTCUSDT",
                            "holdMode": "hedge_mode",
                            "posSide": "long",
                            "marginMode": "crossed",
                            "total": "0.020",
                            "avgPrice": "61000.5",
                            "unrealisedPnl": "4.25",
                        }
                    ]
                },
            },
            {"BTCUSDT": instrument},
            RECEIVED,
        )
        self.assertEqual(positions.positions[0].side, PositionSide.LONG)
        self.assertEqual(positions.positions[0].quantity, Decimal("0.020"))

    def test_uta_private_account_and_position_updates_and_subscriptions(self) -> None:
        self.assertEqual(
            private_subscriptions(),
            (
                {"instType": "UTA", "topic": "account"},
                {"instType": "UTA", "topic": "position"},
            ),
        )
        account = parse_bitget_private(
            {
                "arg": {"instType": "UTA", "topic": "account"},
                "action": "update",
                "ts": 1720000000002,
                "data": [
                    {
                        "coin": [
                            {"coin": "USDT", "balance": "9", "available": "8", "locked": "1", "equity": "9.5"}
                        ]
                    }
                ],
            },
            {},
            RECEIVED,
            known_assets={"USDT"},
        )
        self.assertEqual(account.balances[0].margin_balance, Decimal("9.5"))
        self.assertIsInstance(account, AccountUpdate)

        instrument = _instrument(Exchange.BITGET)
        position = parse_bitget_private(
            {
                "arg": {"instType": "UTA", "topic": "position"},
                "action": "update",
                "ts": 1720000000003,
                "data": [
                    {
                        "symbol": "BTCUSDT",
                        "holdMode": "one_way_mode",
                        "posSide": "short",
                        "marginMode": "isolated",
                        "size": "0",
                        "avgPrice": "0",
                        "unrealisedPnl": "0",
                    }
                ],
            },
            {"BTCUSDT": instrument},
            RECEIVED,
        )
        self.assertEqual(position.positions[0].side, PositionSide.FLAT)
        self.assertEqual(position.positions[0].margin_mode, MarginMode.ISOLATED)

    def test_uta_private_snapshot_is_component_replacing(self) -> None:
        account = parse_bitget_private(
            {
                "arg": {"instType": "UTA", "topic": "account"},
                "action": "snapshot",
                "ts": 1720000000002,
                "data": [],
            },
            {},
            RECEIVED,
        )
        self.assertIsInstance(account, AccountSnapshot)
        self.assertTrue(account.replace_balances)
        self.assertFalse(account.replace_positions)

        positions = parse_bitget_private(
            {
                "arg": {"instType": "UTA", "topic": "position"},
                "action": "snapshot",
                "ts": 1720000000003,
                "data": [],
            },
            {},
            RECEIVED,
        )
        self.assertIsInstance(positions, AccountSnapshot)
        self.assertFalse(positions.replace_balances)
        self.assertTrue(positions.replace_positions)

    def test_unknown_margin_mode_is_rejected(self) -> None:
        instrument = _instrument(Exchange.BITGET)
        with self.assertRaisesRegex(AccountDataError, "unknown margin mode"):
            parse_positions(
                {
                    "requestTime": 1720000000001,
                    "data": {
                        "list": [
                            {
                                "symbol": "BTCUSDT",
                                "holdMode": "one_way_mode",
                                "posSide": "long",
                                "marginMode": "mystery",
                                "total": "1",
                                "avgPrice": "1",
                                "unrealisedPnl": "0",
                            }
                        ]
                    },
                },
                {"BTCUSDT": instrument},
                RECEIVED,
            )


if __name__ == "__main__":
    unittest.main()
