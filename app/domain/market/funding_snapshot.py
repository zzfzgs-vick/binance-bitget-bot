"""Normalized perpetual funding-rate event."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.domain.exceptions import MarketDataError
from app.domain.instruments.instrument import Instrument


@dataclass(frozen=True, slots=True)
class FundingRateSnapshot:
    instrument: Instrument
    rate: Decimal
    next_funding_time: datetime
    event_time: datetime
    received_time: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.rate, Decimal):
            raise TypeError("rate must be Decimal")
        if not self.rate.is_finite():
            raise MarketDataError("rate must be a finite Decimal")
