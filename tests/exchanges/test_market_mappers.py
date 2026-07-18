from datetime import datetime, timezone
from decimal import Decimal
import unittest

from app.domain.enums import Exchange, MarketType, TradingStatus
from app.domain.exceptions import MarketDataError
from app.domain.instruments.instrument import Instrument, TradingRules
from app.domain.market.market_quote import BestBidAsk
from app.domain.market.funding_snapshot import FundingRateSnapshot
from app.domain.market.order_book import OrderBookUpdate
from app.exchanges.binance.mappers.quote_mapper import (
    market_subscriptions as binance_market_subscriptions,
    parse_message as parse_binance_message,
)
from app.exchanges.bitget.mappers.quote_mapper import (
    market_subscriptions as bitget_market_subscriptions,
    parse_message as parse_bitget_message,
)


RECEIVED_TIME = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)


def _instrument(exchange: Exchange, market_type: MarketType) -> Instrument:
    return Instrument(
        exchange=exchange,
        market_type=market_type,
        raw_symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        settlement_asset="USDT",
        rules=TradingRules(
            tick_size=Decimal("0.01"),
            quantity_step=Decimal("0.001"),
            minimum_quantity=Decimal("0.001"),
            maximum_quantity=Decimal("100"),
            minimum_notional=Decimal("5"),
            contract_multiplier=Decimal("1"),
        ),
        status=TradingStatus.TRADING,
        raw_status="TRADING",
    )


class BinanceMarketMapperTests(unittest.TestCase):
    def test_spot_book_ticker_is_normalized_without_float_conversion(self) -> None:
        instrument = _instrument(Exchange.BINANCE, MarketType.SPOT)
        message = {
            "u": 400900217,
            "s": "BTCUSDT",
            "b": "25.35190000",
            "B": "31.21000000",
            "a": "25.36520000",
            "A": "40.66000000",
        }

        (event,) = parse_binance_message(message, instrument, RECEIVED_TIME)

        self.assertIsInstance(event, BestBidAsk)
        self.assertEqual(event.bid.price, Decimal("25.35190000"))
        self.assertEqual(event.bid.quantity, Decimal("31.21000000"))
        self.assertEqual(event.ask.price, Decimal("25.36520000"))
        self.assertEqual(event.sequence, 400900217)
        self.assertEqual(event.event_time, RECEIVED_TIME)
        self.assertEqual(event.received_time, RECEIVED_TIME)
        self.assertIsInstance(event.bid.price, Decimal)

    def test_spot_ticker_without_book_update_id_is_normalized(self) -> None:
        instrument = _instrument(Exchange.BINANCE, MarketType.SPOT)
        message = {
            "e": "24hrTicker",
            "E": 1720000000123,
            "s": "BTCUSDT",
            "c": "62000.15",
            "b": "62000.10",
            "B": "1.001",
            "a": "62000.20",
            "A": "2.002",
        }

        (event,) = parse_binance_message(message, instrument, RECEIVED_TIME)

        self.assertIsInstance(event, BestBidAsk)
        self.assertIsNone(event.sequence)
        self.assertEqual(event.bid.price, Decimal("62000.10"))

    def test_futures_quote_and_funding_messages_are_normalized(self) -> None:
        instrument = _instrument(
            Exchange.BINANCE, MarketType.USDT_PERPETUAL
        )
        quote_message = {
            "e": "bookTicker",
            "E": 1720000000123,
            "T": 1720000000120,
            "u": 99,
            "s": "BTCUSDT",
            "b": "62000.10",
            "B": "1.250",
            "a": "62000.20",
            "A": "2.500",
        }
        funding_message = {
            "e": "markPriceUpdate",
            "E": 1720000001123,
            "s": "BTCUSDT",
            "p": "62000.15",
            "i": "61999.80",
            "P": "62001.00",
            "r": "-0.00001250",
            "T": 1720028800000,
        }

        (quote,) = parse_binance_message(
            quote_message, instrument, RECEIVED_TIME
        )
        (funding,) = parse_binance_message(
            funding_message, instrument, RECEIVED_TIME
        )

        self.assertIsInstance(quote, BestBidAsk)
        self.assertEqual(
            quote.event_time,
            datetime.fromtimestamp(1720000000.123, tz=timezone.utc),
        )
        self.assertIsInstance(funding, FundingRateSnapshot)
        self.assertEqual(funding.rate, Decimal("-0.00001250"))
        self.assertEqual(
            funding.next_funding_time,
            datetime.fromtimestamp(1720028800, tz=timezone.utc),
        )
        self.assertEqual(funding.received_time, RECEIVED_TIME)

    def test_spot_snapshot_and_futures_depth_update_are_normalized(self) -> None:
        spot = _instrument(Exchange.BINANCE, MarketType.SPOT)
        futures = _instrument(
            Exchange.BINANCE, MarketType.USDT_PERPETUAL
        )
        snapshot_message = {
            "lastUpdateId": 100,
            "bids": [["62000.10", "1.001"]],
            "asks": [["62000.20", "2.002"]],
        }
        update_message = {
            "e": "depthUpdate",
            "E": 1720000000123,
            "T": 1720000000120,
            "s": "BTCUSDT",
            "U": 101,
            "u": 102,
            "pu": 100,
            "b": [["62000.10", "0"], ["62000.00", "3.003"]],
            "a": [["62000.20", "4.004"]],
        }

        (snapshot,) = parse_binance_message(
            snapshot_message, spot, RECEIVED_TIME
        )
        (update,) = parse_binance_message(
            update_message, futures, RECEIVED_TIME
        )

        self.assertIsInstance(snapshot, OrderBookUpdate)
        self.assertTrue(snapshot.is_snapshot)
        self.assertEqual(snapshot.sequence, 100)
        self.assertEqual(snapshot.bids[0].price, Decimal("62000.10"))
        self.assertIsInstance(update, OrderBookUpdate)
        self.assertFalse(update.is_snapshot)
        self.assertEqual(update.first_sequence, 101)
        self.assertEqual(update.sequence, 102)
        self.assertEqual(update.previous_sequence, 100)
        self.assertEqual(update.bids[0].quantity, Decimal("0"))


class BitgetMarketMapperTests(unittest.TestCase):
    def test_spot_and_futures_tickers_emit_quotes_and_funding(self) -> None:
        spot = _instrument(Exchange.BITGET, MarketType.SPOT)
        futures = _instrument(
            Exchange.BITGET, MarketType.USDT_PERPETUAL
        )
        spot_message = {
            "arg": {
                "instType": "spot",
                "topic": "ticker",
                "symbol": "BTCUSDT",
            },
            "action": "snapshot",
            "data": [
                {
                    "bid1Price": "61999.10",
                    "bid1Size": "1.001",
                    "ask1Price": "61999.20",
                    "ask1Size": "2.002",
                    "lastPrice": "61999.15",
                }
            ],
            "ts": 1720000000123,
        }
        futures_message = {
            "arg": {
                "instType": "usdt-futures",
                "topic": "ticker",
                "symbol": "BTCUSDT",
            },
            "action": "snapshot",
            "data": [
                {
                    "bid1Price": "62000.10",
                    "bid1Size": "1.003",
                    "ask1Price": "62000.20",
                    "ask1Size": "2.004",
                    "lastPrice": "62000.15",
                    "fundingRate": "0.00007500",
                    "nextFundingTime": "1720028800000",
                }
            ],
            "ts": 1720000001123,
        }

        (spot_quote,) = parse_bitget_message(
            spot_message, spot, RECEIVED_TIME
        )
        futures_events = parse_bitget_message(
            futures_message, futures, RECEIVED_TIME
        )

        self.assertIsInstance(spot_quote, BestBidAsk)
        self.assertEqual(spot_quote.bid.price, Decimal("61999.10"))
        self.assertEqual(len(futures_events), 2)
        futures_quote, funding = futures_events
        self.assertIsInstance(futures_quote, BestBidAsk)
        self.assertIsInstance(funding, FundingRateSnapshot)
        self.assertEqual(funding.rate, Decimal("0.00007500"))
        self.assertEqual(
            funding.next_funding_time,
            datetime.fromtimestamp(1720028800, tz=timezone.utc),
        )

    def test_spot_and_futures_books_snapshot_and_update_are_normalized(self) -> None:
        spot = _instrument(Exchange.BITGET, MarketType.SPOT)
        futures = _instrument(
            Exchange.BITGET, MarketType.USDT_PERPETUAL
        )
        snapshot_message = {
            "arg": {
                "instType": "spot",
                "topic": "books",
                "symbol": "BTCUSDT",
            },
            "action": "snapshot",
            "data": [
                {
                    "a": [["62000.20", "2.002"]],
                    "b": [["62000.10", "1.001"]],
                    "pseq": 0,
                    "seq": 500,
                    "ts": "1720000000120",
                }
            ],
            "ts": 1720000000123,
        }
        update_message = {
            "arg": {
                "instType": "usdt-futures",
                "topic": "books",
                "symbol": "BTCUSDT",
            },
            "action": "update",
            "data": [
                {
                    "a": [["62000.20", "0"]],
                    "b": [["62000.00", "3.003"]],
                    "pseq": 500,
                    "seq": 501,
                    "ts": "1720000001120",
                }
            ],
            "ts": 1720000001123,
        }

        (snapshot,) = parse_bitget_message(
            snapshot_message, spot, RECEIVED_TIME
        )
        (update,) = parse_bitget_message(
            update_message, futures, RECEIVED_TIME
        )

        self.assertIsInstance(snapshot, OrderBookUpdate)
        self.assertTrue(snapshot.is_snapshot)
        self.assertEqual(snapshot.sequence, 500)
        self.assertEqual(snapshot.event_time.microsecond, 120000)
        self.assertIsInstance(update, OrderBookUpdate)
        self.assertFalse(update.is_snapshot)
        self.assertEqual(update.first_sequence, 500)
        self.assertEqual(update.previous_sequence, 500)
        self.assertEqual(update.sequence, 501)
        self.assertEqual(update.asks[0].quantity, Decimal("0"))


class MarketSubscriptionTests(unittest.TestCase):
    def test_supported_channels_match_each_market(self) -> None:
        binance_spot = _instrument(Exchange.BINANCE, MarketType.SPOT)
        binance_futures = _instrument(
            Exchange.BINANCE, MarketType.USDT_PERPETUAL
        )
        bitget_spot = _instrument(Exchange.BITGET, MarketType.SPOT)
        bitget_futures = _instrument(
            Exchange.BITGET, MarketType.USDT_PERPETUAL
        )

        self.assertEqual(
            binance_market_subscriptions(binance_spot),
            ("btcusdt@bookTicker", "btcusdt@depth@100ms"),
        )
        self.assertEqual(
            binance_market_subscriptions(binance_futures),
            (
                "btcusdt@bookTicker",
                "btcusdt@depth@100ms",
                "btcusdt@markPrice@1s",
            ),
        )
        self.assertEqual(
            bitget_market_subscriptions(bitget_spot),
            (
                {"instType": "spot", "topic": "ticker", "symbol": "BTCUSDT"},
                {"instType": "spot", "topic": "books", "symbol": "BTCUSDT"},
            ),
        )
        self.assertEqual(
            bitget_market_subscriptions(bitget_futures)[0]["instType"],
            "usdt-futures",
        )

    def test_control_unknown_and_invalid_messages_are_explicit(self) -> None:
        binance = _instrument(Exchange.BINANCE, MarketType.SPOT)
        bitget = _instrument(Exchange.BITGET, MarketType.SPOT)

        self.assertEqual(
            parse_binance_message(
                {"result": None, "id": "1"}, binance, RECEIVED_TIME
            ),
            (),
        )
        self.assertEqual(
            parse_bitget_message(
                {
                    "event": "subscribe",
                    "arg": {
                        "instType": "spot",
                        "topic": "ticker",
                        "symbol": "BTCUSDT",
                    },
                },
                bitget,
                RECEIVED_TIME,
            ),
            (),
        )
        invalid_messages = (
            (
                parse_binance_message,
                {
                    "e": "unknown",
                    "s": "BTCUSDT",
                    "u": 1,
                    "b": "1",
                    "B": "1",
                    "a": "2",
                    "A": "1",
                },
                binance,
            ),
            (
                parse_binance_message,
                {
                    "u": 1,
                    "s": "BTCUSDT",
                    "b": 1.0,
                    "B": "1",
                    "a": "2",
                    "A": "1",
                },
                binance,
            ),
            (
                parse_bitget_message,
                {
                    "arg": {
                        "instType": "spot",
                        "topic": "unknown",
                        "symbol": "BTCUSDT",
                    },
                    "action": "snapshot",
                    "data": [{}],
                    "ts": 1,
                },
                bitget,
            ),
            (
                parse_binance_message,
                {
                    "e": "24hrTicker",
                    "E": 10**100,
                    "s": "BTCUSDT",
                    "b": "1",
                    "B": "1",
                    "a": "2",
                    "A": "1",
                },
                binance,
            ),
            (
                parse_bitget_message,
                {
                    "arg": {
                        "instType": "spot",
                        "topic": "ticker",
                        "symbol": "BTCUSDT",
                    },
                    "action": "snapshot",
                    "data": [
                        {
                            "bid1Price": "1",
                            "bid1Size": "1",
                            "ask1Price": "2",
                            "ask1Size": "1",
                        }
                    ],
                    "ts": "9" * 5000,
                },
                bitget,
            ),
        )
        for parser, message, instrument in invalid_messages:
            with self.subTest(message=message):
                with self.assertRaises(MarketDataError):
                    parser(message, instrument, RECEIVED_TIME)


if __name__ == "__main__":
    unittest.main()
