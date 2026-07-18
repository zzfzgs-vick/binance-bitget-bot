from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import inspect
import unittest

from app.domain.enums import Exchange, MarketType, TradingStatus
from app.domain.exceptions import ArbitrageCalculationError
from app.domain.arbitrage.arbitrage_opportunity import ArbitrageOpportunity
from app.domain.arbitrage.arbitrage_route import LegSide
from app.domain.instruments.instrument import Instrument, TradingRules
from app.domain.market.order_book import OrderBookSnapshot
from app.domain.market.order_book_level import OrderBookLevel
import app.strategy.opportunity_engine as opportunity_engine
from app.strategy.opportunity_engine import (
    OpportunityRequest,
    calculate_opportunity,
)


NOW = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)


def _instrument(
    exchange: Exchange,
    market_type: MarketType = MarketType.SPOT,
    *,
    quantity_step: str = "0.001",
    minimum_quantity: str = "0.001",
    maximum_quantity: str = "100000",
    minimum_notional: str = "1",
    contract_multiplier: str = "1",
) -> Instrument:
    return Instrument(
        exchange=exchange,
        market_type=market_type,
        raw_symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        settlement_asset="USDT",
        rules=TradingRules(
            tick_size=Decimal("0.01"),
            quantity_step=Decimal(quantity_step),
            minimum_quantity=Decimal(minimum_quantity),
            maximum_quantity=Decimal(maximum_quantity),
            minimum_notional=Decimal(minimum_notional),
            contract_multiplier=Decimal(contract_multiplier),
        ),
        status=TradingStatus.TRADING,
        raw_status="TRADING",
    )


def _book(
    instrument: Instrument,
    *,
    bids: tuple[tuple[str, str], ...],
    asks: tuple[tuple[str, str], ...],
    valid: bool = True,
    received_time: datetime = NOW,
) -> OrderBookSnapshot:
    def levels(
        values: tuple[tuple[str, str], ...],
    ) -> tuple[OrderBookLevel, ...]:
        return tuple(
            OrderBookLevel(Decimal(price), Decimal(quantity))
            for price, quantity in values
        )
    return OrderBookSnapshot(
        instrument=instrument,
        bids=levels(bids),
        asks=levels(asks),
        sequence=1,
        is_valid=valid,
        requires_snapshot=not valid,
        event_time=received_time,
        received_time=received_time,
    )


class OpportunityEngineTests(unittest.TestCase):
    def test_strategy_delegates_quantity_rounding_to_domain_rules(self) -> None:
        source = inspect.getsource(opportunity_engine)

        self.assertNotIn("ROUND_DOWN", source)
        self.assertNotIn("from math import lcm", source)
        self.assertNotIn(".quantity_step", source)

    def test_direct_opportunity_construction_rejects_incompatible_legs(self) -> None:
        binance = _instrument(Exchange.BINANCE)
        bitget = _instrument(Exchange.BITGET)
        result = calculate_opportunity(
            _book(
                binance,
                bids=(("99", "10"),),
                asks=(("100", "10"),),
            ),
            _book(
                bitget,
                bids=(("101", "10"),),
                asks=(("102", "10"),),
            ),
            OpportunityRequest(
                base_quantity=Decimal("1"),
                quote_amount=None,
                buy_fee_rate=Decimal("0"),
                sell_fee_rate=Decimal("0"),
                now=NOW,
                max_age=timedelta(seconds=2),
            ),
        )

        def construct(
            *,
            buy_leg=result.buy_leg,
            sell_leg=result.sell_leg,
            quantity=result.quantity,
        ) -> ArbitrageOpportunity:
            return ArbitrageOpportunity(
                buy_leg=buy_leg,
                sell_leg=sell_leg,
                quantity=quantity,
                profitability=result.profitability,
            )

        cases = (
            (
                "different exchanges",
                {"sell_leg": replace(result.sell_leg, instrument=binance)},
            ),
            (
                "base_asset does not match",
                {
                    "sell_leg": replace(
                        result.sell_leg,
                        instrument=replace(bitget, base_asset="ETH"),
                    )
                },
            ),
            (
                "quote_asset does not match",
                {
                    "sell_leg": replace(
                        result.sell_leg,
                        instrument=replace(bitget, quote_asset="USDC"),
                    )
                },
            ),
            (
                "settlement_asset does not match",
                {
                    "sell_leg": replace(
                        result.sell_leg,
                        instrument=replace(bitget, settlement_asset="USDC"),
                    )
                },
            ),
            (
                "market type is not compatible",
                {
                    "sell_leg": replace(
                        result.sell_leg,
                        instrument=replace(
                            bitget,
                            market_type="delivery",  # type: ignore[arg-type]
                        ),
                    )
                },
            ),
            (
                "buy_leg must have BUY side",
                {"buy_leg": replace(result.buy_leg, side=LegSide.SELL)},
            ),
            (
                "both legs must use the opportunity quantity",
                {
                    "buy_leg": replace(
                        result.buy_leg,
                        order_quantity=Decimal("2"),
                        base_quantity=Decimal("2"),
                        notional=Decimal("200"),
                    )
                },
            ),
        )
        for message, changes in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ArbitrageCalculationError, message):
                    construct(**changes)

    def test_multi_level_fill_fees_profit_and_roi(self) -> None:
        binance = _instrument(Exchange.BINANCE)
        bitget = _instrument(Exchange.BITGET)
        buy_book = _book(
            binance,
            bids=(("99", "10"),),
            asks=(("100", "1"), ("102", "2")),
        )
        sell_book = _book(
            bitget,
            bids=(("105", "1"), ("104", "2")),
            asks=(("106", "10"),),
        )

        result = calculate_opportunity(
            buy_book,
            sell_book,
            OpportunityRequest(
                base_quantity=Decimal("2"),
                quote_amount=None,
                buy_fee_rate=Decimal("0.001"),
                sell_fee_rate=Decimal("0.002"),
                now=NOW,
                max_age=timedelta(seconds=2),
            ),
        )

        self.assertEqual(result.direction, "binance_buy_bitget_sell")
        self.assertEqual(result.quantity, Decimal("2"))
        self.assertEqual(result.buy_leg.average_price, Decimal("101"))
        self.assertEqual(result.sell_leg.average_price, Decimal("104.5"))
        self.assertEqual(result.buy_leg.slippage, Decimal("2"))
        self.assertEqual(result.sell_leg.slippage, Decimal("1"))
        self.assertEqual(result.gross_profit, Decimal("7"))
        self.assertEqual(result.total_fee, Decimal("0.620"))
        self.assertEqual(result.net_profit, Decimal("6.380"))
        self.assertEqual(result.roi, Decimal("6.380") / Decimal("202"))

    def test_quote_amount_spot_perpetual_and_contract_multiplier(self) -> None:
        spot = _instrument(Exchange.BINANCE)
        perpetual = _instrument(
            Exchange.BITGET,
            MarketType.USDT_PERPETUAL,
            quantity_step="1",
            minimum_quantity="1",
            contract_multiplier="0.01",
        )
        buy_book = _book(
            spot,
            bids=(("99", "10"),),
            asks=(("100", "1"), ("105", "2")),
        )
        sell_book = _book(
            perpetual,
            bids=(("110", "100"), ("109", "200")),
            asks=(("111", "1000"),),
        )

        result = calculate_opportunity(
            buy_book,
            sell_book,
            OpportunityRequest(
                base_quantity=None,
                quote_amount=Decimal("205"),
                buy_fee_rate=Decimal("0"),
                sell_fee_rate=Decimal("0"),
                now=NOW,
                max_age=timedelta(seconds=2),
            ),
        )

        self.assertEqual(result.quantity, Decimal("2"))
        self.assertEqual(result.buy_leg.order_quantity, Decimal("2"))
        self.assertEqual(result.sell_leg.order_quantity, Decimal("2E+2"))
        self.assertEqual(result.buy_leg.notional, Decimal("205"))
        self.assertEqual(result.sell_leg.notional, Decimal("219"))

    def test_reverse_perpetual_route_returns_negative_profit(self) -> None:
        bitget = _instrument(
            Exchange.BITGET,
            MarketType.USDT_PERPETUAL,
            quantity_step="1",
            minimum_quantity="1",
            contract_multiplier="0.01",
        )
        binance = _instrument(
            Exchange.BINANCE,
            MarketType.USDT_PERPETUAL,
            quantity_step="1",
            minimum_quantity="1",
            contract_multiplier="0.01",
        )
        buy_book = _book(
            bitget,
            bids=(("100", "1000"),),
            asks=(("102", "1000"),),
        )
        sell_book = _book(
            binance,
            bids=(("101", "1000"),),
            asks=(("103", "1000"),),
        )

        result = calculate_opportunity(
            buy_book,
            sell_book,
            OpportunityRequest(
                base_quantity=Decimal("1.239"),
                quote_amount=None,
                buy_fee_rate=Decimal("0"),
                sell_fee_rate=Decimal("0"),
                now=NOW,
                max_age=timedelta(seconds=2),
            ),
        )

        self.assertEqual(result.direction, "bitget_buy_binance_sell")
        self.assertEqual(result.quantity, Decimal("1.23"))
        self.assertEqual(result.buy_leg.order_quantity, Decimal("123"))
        self.assertEqual(result.sell_leg.order_quantity, Decimal("123"))
        self.assertEqual(result.gross_profit, Decimal("-1.23"))
        self.assertEqual(result.net_profit, Decimal("-1.23"))
        self.assertLess(result.roi, Decimal(0))

    def test_quantity_uses_common_step_for_both_legs(self) -> None:
        binance = _instrument(
            Exchange.BINANCE,
            quantity_step="0.03",
            minimum_quantity="0.03",
        )
        bitget = _instrument(
            Exchange.BITGET,
            quantity_step="0.02",
            minimum_quantity="0.02",
        )
        buy_book = _book(
            binance,
            bids=(("99", "1"),),
            asks=(("100", "1"),),
        )
        sell_book = _book(
            bitget,
            bids=(("101", "1"),),
            asks=(("102", "1"),),
        )

        result = calculate_opportunity(
            buy_book,
            sell_book,
            OpportunityRequest(
                base_quantity=Decimal("0.10"),
                quote_amount=None,
                buy_fee_rate=Decimal("0"),
                sell_fee_rate=Decimal("0"),
                now=NOW,
                max_age=timedelta(seconds=2),
            ),
        )

        self.assertEqual(result.quantity, Decimal("0.06"))
        self.assertEqual(result.buy_leg.order_quantity, Decimal("0.06"))
        self.assertEqual(result.sell_leg.order_quantity, Decimal("0.06"))

    def test_invalid_stale_or_insufficient_books_are_rejected(self) -> None:
        binance = _instrument(Exchange.BINANCE)
        bitget = _instrument(Exchange.BITGET)
        valid_buy = _book(
            binance,
            bids=(("99", "1"),),
            asks=(("100", "1"),),
        )
        valid_sell = _book(
            bitget,
            bids=(("101", "1"),),
            asks=(("102", "1"),),
        )
        request = OpportunityRequest(
            base_quantity=Decimal("2"),
            quote_amount=None,
            buy_fee_rate=Decimal("0"),
            sell_fee_rate=Decimal("0"),
            now=NOW,
            max_age=timedelta(seconds=2),
        )

        with self.assertRaisesRegex(
            ArbitrageCalculationError, "insufficient buy depth"
        ):
            calculate_opportunity(valid_buy, valid_sell, request)

        deep_buy = _book(
            binance,
            bids=(("99", "10"),),
            asks=(("100", "10"),),
        )
        with self.assertRaisesRegex(
            ArbitrageCalculationError, "insufficient sell depth"
        ):
            calculate_opportunity(deep_buy, valid_sell, request)

        invalid_buy = _book(
            binance,
            bids=(("99", "10"),),
            asks=(("100", "10"),),
            valid=False,
        )
        with self.assertRaisesRegex(ArbitrageCalculationError, "invalid"):
            calculate_opportunity(invalid_buy, valid_sell, request)

        stale_sell = _book(
            bitget,
            bids=(("101", "10"),),
            asks=(("102", "10"),),
            received_time=NOW - timedelta(seconds=3),
        )
        with self.assertRaisesRegex(ArbitrageCalculationError, "stale"):
            calculate_opportunity(
                _book(
                    binance,
                    bids=(("99", "10"),),
                    asks=(("100", "10"),),
                ),
                stale_sell,
                request,
            )

    def test_minimum_quantity_and_notional_are_enforced(self) -> None:
        bitget = _instrument(Exchange.BITGET)
        request = OpportunityRequest(
            base_quantity=Decimal("1"),
            quote_amount=None,
            buy_fee_rate=Decimal("0"),
            sell_fee_rate=Decimal("0"),
            now=NOW,
            max_age=timedelta(seconds=2),
        )

        minimum_quantity = _instrument(
            Exchange.BINANCE,
            minimum_quantity="2",
        )
        with self.assertRaisesRegex(
            ArbitrageCalculationError, "below minimum_quantity"
        ):
            calculate_opportunity(
                _book(
                    minimum_quantity,
                    bids=(("99", "10"),),
                    asks=(("100", "10"),),
                ),
                _book(
                    bitget,
                    bids=(("101", "10"),),
                    asks=(("102", "10"),),
                ),
                request,
            )

        minimum_notional = _instrument(
            Exchange.BINANCE,
            minimum_notional="200",
        )
        with self.assertRaisesRegex(
            ArbitrageCalculationError, "below minimum_notional"
        ):
            calculate_opportunity(
                _book(
                    minimum_notional,
                    bids=(("99", "10"),),
                    asks=(("100", "10"),),
                ),
                _book(
                    bitget,
                    bids=(("101", "10"),),
                    asks=(("102", "10"),),
                ),
                request,
            )

        maximum_quantity = _instrument(
            Exchange.BINANCE,
            maximum_quantity="0.5",
        )
        with self.assertRaisesRegex(
            ArbitrageCalculationError, "exceeds maximum_quantity"
        ):
            calculate_opportunity(
                _book(
                    maximum_quantity,
                    bids=(("99", "10"),),
                    asks=(("100", "10"),),
                ),
                _book(
                    bitget,
                    bids=(("101", "10"),),
                    asks=(("102", "10"),),
                ),
                request,
            )

    def test_missing_fees_and_incompatible_instruments_are_rejected(self) -> None:
        binance = _instrument(Exchange.BINANCE)
        bitget = _instrument(Exchange.BITGET)
        buy_book = _book(
            binance,
            bids=(("99", "10"),),
            asks=(("100", "10"),),
        )
        sell_book = _book(
            bitget,
            bids=(("101", "10"),),
            asks=(("102", "10"),),
        )

        with self.assertRaisesRegex(
            ArbitrageCalculationError, "buy_fee_rate is required"
        ):
            calculate_opportunity(
                buy_book,
                sell_book,
                OpportunityRequest(
                    base_quantity=Decimal("1"),
                    quote_amount=None,
                    buy_fee_rate=None,
                    sell_fee_rate=Decimal("0"),
                    now=NOW,
                    max_age=timedelta(seconds=2),
                ),
            )

        incompatible = Instrument(
            exchange=Exchange.BITGET,
            market_type=MarketType.SPOT,
            raw_symbol="BTCUSDC",
            base_asset="BTC",
            quote_asset="USDC",
            settlement_asset="USDC",
            rules=bitget.rules,
            status=TradingStatus.TRADING,
            raw_status="TRADING",
        )
        with self.assertRaisesRegex(
            ArbitrageCalculationError, "incompatible trading rules"
        ):
            calculate_opportunity(
                buy_book,
                _book(
                    incompatible,
                    bids=(("101", "10"),),
                    asks=(("102", "10"),),
                ),
                OpportunityRequest(
                    base_quantity=Decimal("1"),
                    quote_amount=None,
                    buy_fee_rate=Decimal("0"),
                    sell_fee_rate=Decimal("0"),
                    now=NOW,
                    max_age=timedelta(seconds=2),
                ),
            )

    def test_zero_profit_result_and_all_financial_values_are_decimal(self) -> None:
        binance = _instrument(Exchange.BINANCE)
        bitget = _instrument(Exchange.BITGET)
        result = calculate_opportunity(
            _book(
                binance,
                bids=(("99", "10"),),
                asks=(("100.00000001", "10"),),
            ),
            _book(
                bitget,
                bids=(("100.00000001", "10"),),
                asks=(("101", "10"),),
            ),
            OpportunityRequest(
                base_quantity=Decimal("0.123"),
                quote_amount=None,
                buy_fee_rate=Decimal("0"),
                sell_fee_rate=Decimal("0"),
                now=NOW,
                max_age=timedelta(seconds=2),
            ),
        )

        self.assertEqual(result.gross_profit, Decimal(0))
        self.assertEqual(result.net_profit, Decimal(0))
        self.assertEqual(result.roi, Decimal(0))
        values = (
            result.quantity,
            result.buy_leg.order_quantity,
            result.buy_leg.average_price,
            result.buy_leg.notional,
            result.buy_leg.fee,
            result.buy_leg.slippage,
            result.sell_leg.order_quantity,
            result.sell_leg.average_price,
            result.sell_leg.notional,
            result.sell_leg.fee,
            result.sell_leg.slippage,
            result.gross_profit,
            result.total_fee,
            result.slippage_cost,
            result.net_profit,
            result.roi,
        )
        self.assertTrue(all(isinstance(value, Decimal) for value in values))


if __name__ == "__main__":
    unittest.main()
