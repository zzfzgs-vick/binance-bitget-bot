from decimal import Decimal
import unittest

from app.domain.enums import Exchange, MarketType, TradingStatus
from app.domain.exceptions import (
    InstrumentDataError,
    InstrumentMatchError,
    TradingRuleError,
)
from app.domain.instruments.instrument import Instrument, TradingRules
from app.domain.instruments.trading_pair import match_instruments


def _instrument(
    exchange: Exchange,
    market_type: MarketType,
    symbol: str,
    *,
    base: str = "BTC",
    quote: str = "USDT",
    settlement: str = "USDT",
    status: TradingStatus = TradingStatus.TRADING,
) -> Instrument:
    return Instrument(
        exchange=exchange,
        market_type=market_type,
        raw_symbol=symbol,
        base_asset=base,
        quote_asset=quote,
        settlement_asset=settlement,
        rules=TradingRules(
            tick_size=Decimal("0.01"),
            quantity_step=Decimal("0.001"),
            minimum_quantity=Decimal("0.001"),
            maximum_quantity=Decimal("100"),
            minimum_notional=Decimal("5"),
            contract_multiplier=Decimal("1"),
        ),
        status=status,
        raw_status=status.value,
    )


class InstrumentRulesTests(unittest.TestCase):
    def test_normalize_order_uses_decimal_steps_and_rounds_quantity_down(self) -> None:
        rules = TradingRules(
            tick_size=Decimal("0.05"),
            quantity_step=Decimal("0.02"),
            minimum_quantity=Decimal("0.02"),
            maximum_quantity=Decimal("100"),
            minimum_notional=Decimal("5"),
            contract_multiplier=Decimal("1"),
        )
        instrument = Instrument(
            exchange=Exchange.BINANCE,
            market_type=MarketType.SPOT,
            raw_symbol="BTCUSDT",
            base_asset="BTC",
            quote_asset="USDT",
            settlement_asset="USDT",
            rules=rules,
            status=TradingStatus.TRADING,
            raw_status="TRADING",
        )

        price, quantity = instrument.rules.normalize_order(
            Decimal("100.078"), Decimal("0.079")
        )

        self.assertEqual(price, Decimal("100.05"))
        self.assertEqual(quantity, Decimal("0.06"))
        self.assertIsInstance(price, Decimal)
        self.assertIsInstance(quantity, Decimal)

    def test_minimum_maximum_and_notional_are_enforced_after_quantization(self) -> None:
        rules = TradingRules(
            tick_size=Decimal("1"),
            quantity_step=Decimal("0.1"),
            minimum_quantity=Decimal("1"),
            maximum_quantity=Decimal("10"),
            minimum_notional=Decimal("25"),
            contract_multiplier=Decimal("2"),
        )
        invalid_orders = (
            (Decimal("20"), Decimal("0.99"), "minimum_quantity"),
            (Decimal("20"), Decimal("10.11"), "maximum_quantity"),
            (Decimal("10"), Decimal("1"), "minimum_notional"),
        )
        for price, quantity, expected_field in invalid_orders:
            with self.subTest(field=expected_field):
                with self.assertRaisesRegex(TradingRuleError, expected_field):
                    rules.normalize_order(price, quantity)

    def test_order_values_must_be_decimal(self) -> None:
        rules = _instrument(
            Exchange.BINANCE, MarketType.SPOT, "BTCUSDT"
        ).rules

        with self.assertRaisesRegex(TypeError, "price must be Decimal"):
            rules.normalize_order(100.0, Decimal("1"))  # type: ignore[arg-type]
        with self.assertRaisesRegex(TypeError, "quantity must be Decimal"):
            rules.normalize_order(Decimal("100"), "1")  # type: ignore[arg-type]
        for price, quantity in (
            (Decimal("0"), Decimal("1")),
            (Decimal("1"), Decimal("-1")),
        ):
            with self.subTest(price=price, quantity=quantity):
                with self.assertRaises(TradingRuleError):
                    rules.normalize_order(price, quantity)

    def test_invalid_rule_values_are_rejected(self) -> None:
        invalid = (Decimal("0"), Decimal("NaN"), Decimal("Infinity"))
        for tick_size in invalid:
            with self.subTest(tick_size=tick_size):
                with self.assertRaises(InstrumentDataError):
                    TradingRules(
                        tick_size=tick_size,
                        quantity_step=Decimal("1"),
                        minimum_quantity=Decimal("1"),
                        maximum_quantity=None,
                        minimum_notional=Decimal("1"),
                        contract_multiplier=Decimal("1"),
                    )

        with self.assertRaisesRegex(InstrumentDataError, "maximum_quantity"):
            TradingRules(
                tick_size=Decimal("1"),
                quantity_step=Decimal("1"),
                minimum_quantity=Decimal("2"),
                maximum_quantity=Decimal("1"),
                minimum_notional=Decimal("1"),
                contract_multiplier=Decimal("1"),
            )


class InstrumentMatchingTests(unittest.TestCase):
    def test_matching_uses_asset_semantics_not_raw_symbol(self) -> None:
        binance = _instrument(
            Exchange.BINANCE, MarketType.SPOT, "BTCUSDT"
        )
        bitget = _instrument(
            Exchange.BITGET, MarketType.SPOT, "BTC-USDT"
        )

        match = match_instruments(binance, bitget)

        self.assertIs(match.left, binance)
        self.assertIs(match.right, bitget)

    def test_supported_market_combinations_include_spot_and_perpetual(self) -> None:
        combinations = (
            (MarketType.SPOT, MarketType.SPOT),
            (MarketType.USDT_PERPETUAL, MarketType.USDT_PERPETUAL),
            (MarketType.SPOT, MarketType.USDT_PERPETUAL),
            (MarketType.USDT_PERPETUAL, MarketType.SPOT),
        )
        for left_market, right_market in combinations:
            with self.subTest(left=left_market, right=right_market):
                match_instruments(
                    _instrument(Exchange.BINANCE, left_market, "left"),
                    _instrument(Exchange.BITGET, right_market, "right"),
                )

    def test_incompatible_or_unavailable_instruments_are_rejected(self) -> None:
        valid = _instrument(Exchange.BINANCE, MarketType.SPOT, "BTCUSDT")
        incompatible = (
            _instrument(Exchange.BINANCE, MarketType.SPOT, "same-exchange"),
            _instrument(
                Exchange.BITGET, MarketType.SPOT, "ETHUSDT", base="ETH"
            ),
            _instrument(
                Exchange.BITGET, MarketType.SPOT, "BTCUSDC", quote="USDC"
            ),
            _instrument(
                Exchange.BITGET,
                MarketType.SPOT,
                "BTCUSDT",
                settlement="USDC",
            ),
            _instrument(
                Exchange.BITGET,
                MarketType.SPOT,
                "BTCUSDT",
                status=TradingStatus.UNAVAILABLE,
            ),
        )
        for candidate in incompatible:
            with self.subTest(symbol=candidate.raw_symbol):
                with self.assertRaises(InstrumentMatchError):
                    match_instruments(valid, candidate)


if __name__ == "__main__":
    unittest.main()
