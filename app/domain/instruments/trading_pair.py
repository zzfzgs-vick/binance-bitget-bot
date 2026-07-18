"""Cross-exchange instrument compatibility."""

from dataclasses import dataclass

from app.domain.enums import MarketType, TradingStatus
from app.domain.exceptions import InstrumentMatchError
from app.domain.instruments.instrument import Instrument


_SUPPORTED_MARKETS = {MarketType.SPOT, MarketType.USDT_PERPETUAL}


@dataclass(frozen=True, slots=True)
class InstrumentMatch:
    left: Instrument
    right: Instrument


def match_instruments(left: Instrument, right: Instrument) -> InstrumentMatch:
    if left.exchange == right.exchange:
        raise InstrumentMatchError("instruments must belong to different exchanges")
    if (
        left.status is not TradingStatus.TRADING
        or right.status is not TradingStatus.TRADING
    ):
        raise InstrumentMatchError("both instruments must be trading")
    if (
        left.market_type not in _SUPPORTED_MARKETS
        or right.market_type not in _SUPPORTED_MARKETS
    ):
        raise InstrumentMatchError("market type is not compatible")
    for field in ("base_asset", "quote_asset", "settlement_asset"):
        if getattr(left, field) != getattr(right, field):
            raise InstrumentMatchError(f"{field} does not match")
    return InstrumentMatch(left=left, right=right)
