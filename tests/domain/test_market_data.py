from datetime import datetime, timezone
from decimal import Decimal
import unittest

from app.domain.enums import Exchange, MarketType, TradingStatus
from app.domain.instruments.instrument import Instrument, TradingRules
from app.domain.market.order_book import (
    OrderBook,
    OrderBookUpdate,
    UpdateResult,
)
from app.domain.market.order_book_level import OrderBookLevel


EVENT_TIME = datetime(2026, 7, 18, 11, 59, tzinfo=timezone.utc)
RECEIVED_TIME = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)


def _instrument() -> Instrument:
    return Instrument(
        exchange=Exchange.BINANCE,
        market_type=MarketType.SPOT,
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


def _level(price: str, quantity: str) -> OrderBookLevel:
    return OrderBookLevel(Decimal(price), Decimal(quantity))


class OrderBookTests(unittest.TestCase):
    def test_snapshot_and_increment_update_sort_delete_and_limit_levels(self) -> None:
        instrument = _instrument()
        book = OrderBook(instrument, depth_limit=2)
        snapshot = OrderBookUpdate(
            instrument=instrument,
            bids=(_level("99", "1"), _level("100", "2"), _level("98", "3")),
            asks=(_level("103", "1"), _level("101", "2"), _level("102", "3")),
            first_sequence=10,
            sequence=10,
            previous_sequence=None,
            is_snapshot=True,
            event_time=EVENT_TIME,
            received_time=RECEIVED_TIME,
        )
        update = OrderBookUpdate(
            instrument=instrument,
            bids=(_level("100", "0"), _level("99.5", "4")),
            asks=(_level("101", "0"), _level("100.5", "5")),
            first_sequence=10,
            sequence=11,
            previous_sequence=10,
            is_snapshot=False,
            event_time=EVENT_TIME,
            received_time=RECEIVED_TIME,
        )

        self.assertIs(book.apply(snapshot), UpdateResult.SNAPSHOT_APPLIED)
        self.assertIs(book.apply(update), UpdateResult.APPLIED)
        current = book.snapshot()

        self.assertEqual(
            current.bids,
            (_level("99.5", "4"), _level("99", "1")),
        )
        self.assertEqual(
            current.asks,
            (_level("100.5", "5"), _level("102", "3")),
        )
        self.assertTrue(current.is_valid)
        self.assertFalse(current.requires_snapshot)
        self.assertEqual(current.sequence, 11)

        remove_top = OrderBookUpdate(
            instrument=instrument,
            bids=(_level("99.5", "0"),),
            asks=(_level("100.5", "0"),),
            first_sequence=12,
            sequence=12,
            previous_sequence=11,
            is_snapshot=False,
            event_time=EVENT_TIME,
            received_time=RECEIVED_TIME,
        )
        self.assertIs(book.apply(remove_top), UpdateResult.APPLIED)
        promoted = book.snapshot()
        self.assertEqual(promoted.bids, (_level("99", "1"), _level("98", "3")))
        self.assertEqual(
            promoted.asks,
            (_level("102", "3"), _level("103", "1")),
        )

    def test_duplicate_out_of_order_gap_and_resnapshot_are_explicit(self) -> None:
        instrument = _instrument()
        book = OrderBook(instrument)

        def update(
            first: int,
            final: int,
            previous: int | None,
            *,
            snapshot: bool = False,
        ) -> OrderBookUpdate:
            return OrderBookUpdate(
                instrument=instrument,
                bids=(_level("100", str(final)),),
                asks=(_level("101", str(final)),),
                first_sequence=first,
                sequence=final,
                previous_sequence=previous,
                is_snapshot=snapshot,
                event_time=EVENT_TIME,
                received_time=RECEIVED_TIME,
            )

        self.assertIs(
            book.apply(update(100, 100, None, snapshot=True)),
            UpdateResult.SNAPSHOT_APPLIED,
        )
        self.assertIs(book.apply(update(100, 100, 99)), UpdateResult.DUPLICATE)
        self.assertIs(
            book.apply(update(98, 99, 97)), UpdateResult.OUT_OF_ORDER
        )
        self.assertIs(book.apply(update(100, 101, 100)), UpdateResult.APPLIED)
        self.assertIs(
            book.apply(update(103, 103, 102)), UpdateResult.GAP_DETECTED
        )
        invalid = book.snapshot()
        self.assertFalse(invalid.is_valid)
        self.assertTrue(invalid.requires_snapshot)
        self.assertIs(
            book.apply(update(102, 102, 101)), UpdateResult.RESYNC_REQUIRED
        )
        self.assertIs(
            book.apply(update(200, 200, None, snapshot=True)),
            UpdateResult.SNAPSHOT_APPLIED,
        )
        self.assertTrue(book.snapshot().is_valid)

    def test_snapshot_overlap_and_previous_sequence_rules_are_enforced(self) -> None:
        instrument = _instrument()

        def update(
            first: int,
            final: int,
            previous: int | None,
            snapshot: bool = False,
        ) -> OrderBookUpdate:
            return OrderBookUpdate(
                instrument=instrument,
                bids=(_level("100", "1"),),
                asks=(_level("101", "1"),),
                first_sequence=first,
                sequence=final,
                previous_sequence=previous,
                is_snapshot=snapshot,
                event_time=EVENT_TIME,
                received_time=RECEIVED_TIME,
            )

        book = OrderBook(instrument)
        self.assertIs(
            book.apply(update(99, 101, 98)), UpdateResult.RESYNC_REQUIRED
        )
        book.apply(update(100, 100, None, snapshot=True))
        self.assertIs(book.apply(update(99, 101, 98)), UpdateResult.APPLIED)
        self.assertIs(
            book.apply(update(102, 102, 0)), UpdateResult.GAP_DETECTED
        )

        bitget_style = OrderBook(instrument)
        bitget_style.apply(update(500, 500, None, snapshot=True))
        self.assertIs(
            bitget_style.apply(update(490, 501, 490)), UpdateResult.APPLIED
        )
        self.assertIs(
            bitget_style.apply(update(502, 502, 0)),
            UpdateResult.GAP_DETECTED,
        )

        invalid_first_range = OrderBook(instrument)
        invalid_first_range.apply(update(500, 500, None, snapshot=True))
        self.assertIs(
            invalid_first_range.apply(update(501, 501, 501)),
            UpdateResult.GAP_DETECTED,
        )

        spot_style = OrderBook(instrument)
        spot_style.apply(update(500, 500, None, snapshot=True))
        self.assertIs(
            spot_style.apply(update(501, 501, None)),
            UpdateResult.APPLIED,
        )

        reset_after_snapshot = OrderBook(instrument)
        reset_after_snapshot.apply(update(500, 500, None, snapshot=True))
        self.assertIs(
            reset_after_snapshot.apply(update(0, 1, 0)),
            UpdateResult.GAP_DETECTED,
        )


if __name__ == "__main__":
    unittest.main()
