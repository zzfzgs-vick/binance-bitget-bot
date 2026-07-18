"""Domain errors with caller-facing reasons."""


class InstrumentDataError(ValueError):
    """Raw product data cannot form a valid instrument."""


class InstrumentMatchError(ValueError):
    """Two instruments are not compatible for the requested match."""


class TradingRuleError(ValueError):
    """An order value violates normalized trading rules."""


class MarketDataError(ValueError):
    """A market message or normalized event is invalid."""


class ArbitrageCalculationError(ValueError):
    """An arbitrage opportunity cannot be calculated from the inputs."""
