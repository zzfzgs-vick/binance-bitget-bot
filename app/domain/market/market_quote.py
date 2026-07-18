"""Normalized best bid and ask."""

from dataclasses import dataclass
from datetime import datetime

from app.domain.instruments.instrument import Instrument
from app.domain.market.order_book_level import OrderBookLevel


@dataclass(frozen=True, slots=True)
class BestBidAsk:
    instrument: Instrument
    bid: OrderBookLevel
    ask: OrderBookLevel
    sequence: int | None
    event_time: datetime
    received_time: datetime
