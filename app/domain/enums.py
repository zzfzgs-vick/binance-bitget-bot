"""Shared domain enumerations."""

from enum import Enum


class Exchange(str, Enum):
    BINANCE = "binance"
    BITGET = "bitget"


class MarketType(str, Enum):
    SPOT = "spot"
    USDT_PERPETUAL = "usdt_perpetual"


class TradingStatus(str, Enum):
    TRADING = "trading"
    UNAVAILABLE = "unavailable"
