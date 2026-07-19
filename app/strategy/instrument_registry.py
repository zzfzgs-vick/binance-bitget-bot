"""Small in-memory index of normalized LIVE instruments."""

from app.domain.enums import Exchange, MarketType, TradingStatus
from app.domain.instruments.instrument import Instrument


class InstrumentRegistry:
    def __init__(self) -> None:
        self._items: dict[tuple[Exchange, MarketType, str], Instrument] = {}

    def replace(self, instruments: tuple[Instrument, ...]) -> None:
        if not all(isinstance(item, Instrument) for item in instruments):
            raise TypeError("instruments must contain Instrument values")
        self._items = {
            (item.exchange, item.market_type, item.raw_symbol.upper()): item
            for item in instruments
            if item.status is TradingStatus.TRADING
        }

    @property
    def instruments(self) -> tuple[Instrument, ...]:
        return tuple(self._items.values())

    def for_exchange(self, exchange: Exchange) -> dict[str, Instrument]:
        return {
            instrument.raw_symbol: instrument
            for instrument in self._items.values()
            if instrument.exchange is exchange
        }

    def for_binance_orders(self) -> dict[tuple[MarketType, str], Instrument]:
        return {
            (instrument.market_type, instrument.raw_symbol): instrument
            for instrument in self._items.values()
            if instrument.exchange is Exchange.BINANCE
        }

    def search(self, value: str) -> tuple[Instrument, ...]:
        query = value.strip().upper().replace("/", "")
        if not query:
            return ()
        return tuple(
            item
            for item in self._items.values()
            if query in {
                item.raw_symbol.upper(),
                f"{item.base_asset}{item.quote_asset}".upper(),
            }
        )
