from decimal import Decimal
from copy import deepcopy
import unittest

from app.domain.enums import Exchange, MarketType, TradingStatus
from app.domain.exceptions import InstrumentDataError
from app.exchanges.binance.mappers.instrument_mapper import (
    parse_usdt_perpetual_products as parse_binance_futures_products,
    parse_spot_products as parse_binance_spot_products,
)
from app.exchanges.bitget.mappers.instrument_mapper import (
    parse_usdt_perpetual_products as parse_bitget_futures_products,
    parse_spot_products as parse_bitget_spot_products,
)


class InstrumentMapperTests(unittest.TestCase):
    def test_binance_spot_product_is_normalized_from_exchange_filters(self) -> None:
        payload = {
            "symbols": [
                {
                    "symbol": "BTCUSDT",
                    "status": "TRADING",
                    "baseAsset": "BTC",
                    "quoteAsset": "USDT",
                    "filters": [
                        {
                            "filterType": "PRICE_FILTER",
                            "tickSize": "0.01000000",
                        },
                        {
                            "filterType": "LOT_SIZE",
                            "minQty": "0.00001000",
                            "maxQty": "9000.00000000",
                            "stepSize": "0.00001000",
                        },
                        {
                            "filterType": "MIN_NOTIONAL",
                            "minNotional": "5.00000000",
                        },
                    ],
                }
            ]
        }

        (instrument,) = parse_binance_spot_products(payload)

        self.assertEqual(instrument.exchange, Exchange.BINANCE)
        self.assertEqual(instrument.market_type, MarketType.SPOT)
        self.assertEqual(instrument.raw_symbol, "BTCUSDT")
        self.assertEqual(instrument.base_asset, "BTC")
        self.assertEqual(instrument.quote_asset, "USDT")
        self.assertEqual(instrument.settlement_asset, "USDT")
        self.assertEqual(instrument.status, TradingStatus.TRADING)
        self.assertEqual(instrument.rules.tick_size, Decimal("0.01000000"))
        self.assertEqual(instrument.rules.quantity_step, Decimal("0.00001000"))
        self.assertEqual(instrument.rules.minimum_quantity, Decimal("0.00001000"))
        self.assertEqual(instrument.rules.maximum_quantity, Decimal("9000.00000000"))
        self.assertEqual(instrument.rules.minimum_notional, Decimal("5.00000000"))
        self.assertEqual(instrument.rules.contract_multiplier, Decimal("1"))
        for value in (
            instrument.rules.tick_size,
            instrument.rules.quantity_step,
            instrument.rules.minimum_quantity,
            instrument.rules.maximum_quantity,
            instrument.rules.minimum_notional,
            instrument.rules.contract_multiplier,
        ):
            self.assertIsInstance(value, Decimal)

    def test_binance_usdt_perpetual_product_uses_margin_asset_and_filters(self) -> None:
        payload = {
            "symbols": [
                {
                    "symbol": "BTCUSDT",
                    "contractType": "PERPETUAL",
                    "status": "TRADING",
                    "baseAsset": "BTC",
                    "quoteAsset": "USDT",
                    "marginAsset": "USDT",
                    "filters": [
                        {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
                        {
                            "filterType": "LOT_SIZE",
                            "minQty": "0.001",
                            "maxQty": "1000",
                            "stepSize": "0.001",
                        },
                        {"filterType": "MIN_NOTIONAL", "notional": "5"},
                    ],
                }
            ]
        }

        (instrument,) = parse_binance_futures_products(payload)

        self.assertEqual(instrument.market_type, MarketType.USDT_PERPETUAL)
        self.assertEqual(instrument.settlement_asset, "USDT")
        self.assertEqual(instrument.rules.tick_size, Decimal("0.10"))
        self.assertEqual(instrument.rules.quantity_step, Decimal("0.001"))
        self.assertEqual(instrument.rules.minimum_notional, Decimal("5"))
        self.assertEqual(instrument.rules.contract_multiplier, Decimal("1"))

    def test_bitget_spot_product_derives_steps_from_official_precisions(self) -> None:
        payload = {
            "code": "00000",
            "data": [
                {
                    "symbol": "BTC-USDT",
                    "category": "SPOT",
                    "baseCoin": "BTC",
                    "quoteCoin": "USDT",
                    "minOrderQty": "0.000001",
                    "maxOrderQty": "0",
                    "pricePrecision": "2",
                    "quantityPrecision": "6",
                    "minOrderAmount": "1",
                    "status": "online",
                }
            ],
        }

        (instrument,) = parse_bitget_spot_products(payload)

        self.assertEqual(instrument.exchange, Exchange.BITGET)
        self.assertEqual(instrument.market_type, MarketType.SPOT)
        self.assertEqual(instrument.raw_symbol, "BTC-USDT")
        self.assertEqual(instrument.rules.tick_size, Decimal("0.01"))
        self.assertEqual(instrument.rules.quantity_step, Decimal("0.000001"))
        self.assertEqual(instrument.rules.minimum_quantity, Decimal("0.000001"))
        self.assertIsNone(instrument.rules.maximum_quantity)
        self.assertEqual(instrument.rules.minimum_notional, Decimal("1"))

    def test_bitget_usdt_perpetual_uses_explicit_rule_multipliers(self) -> None:
        payload = {
            "code": "00000",
            "data": [
                {
                    "symbol": "BTCUSDT",
                    "category": "USDT-FUTURES",
                    "baseCoin": "BTC",
                    "quoteCoin": "USDT",
                    "minOrderQty": "0.0001",
                    "maxOrderQty": "1200",
                    "pricePrecision": "2",
                    "quantityPrecision": "4",
                    "priceMultiplier": "0.02",
                    "quantityMultiplier": "0.0001",
                    "minOrderAmount": "5",
                    "type": "perpetual",
                    "status": "online",
                }
            ],
        }

        (instrument,) = parse_bitget_futures_products(payload)

        self.assertEqual(instrument.market_type, MarketType.USDT_PERPETUAL)
        self.assertEqual(instrument.settlement_asset, "USDT")
        self.assertEqual(instrument.rules.tick_size, Decimal("0.02"))
        self.assertEqual(instrument.rules.quantity_step, Decimal("0.0001"))
        self.assertEqual(instrument.rules.minimum_quantity, Decimal("0.0001"))
        self.assertEqual(instrument.rules.maximum_quantity, Decimal("1200"))
        self.assertEqual(instrument.rules.minimum_notional, Decimal("5"))
        self.assertEqual(instrument.rules.contract_multiplier, Decimal("1"))

    def test_binance_rejects_missing_invalid_conflicting_and_unknown_fields(self) -> None:
        base_payload = {
            "symbols": [
                {
                    "symbol": "BTCUSDT",
                    "status": "TRADING",
                    "baseAsset": "BTC",
                    "quoteAsset": "USDT",
                    "filters": [
                        {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                        {
                            "filterType": "LOT_SIZE",
                            "minQty": "0.001",
                            "maxQty": "100",
                            "stepSize": "0.001",
                        },
                        {"filterType": "MIN_NOTIONAL", "minNotional": "5"},
                    ],
                }
            ]
        }
        cases = []
        missing_filter = deepcopy(base_payload)
        missing_filter["symbols"][0]["filters"].pop(0)
        cases.append((missing_filter, "missing PRICE_FILTER"))
        float_value = deepcopy(base_payload)
        float_value["symbols"][0]["filters"][0]["tickSize"] = 0.01
        cases.append((float_value, "tickSize must be a non-empty string"))
        unknown_status = deepcopy(base_payload)
        unknown_status["symbols"][0]["status"] = "UNKNOWN"
        cases.append((unknown_status, "status has unknown value"))
        conflicting_notional = deepcopy(base_payload)
        conflicting_notional["symbols"][0]["filters"].append(
            {"filterType": "NOTIONAL", "minNotional": "10"}
        )
        cases.append((conflicting_notional, "conflicting minimum notional"))

        for payload, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(InstrumentDataError, message):
                    parse_binance_spot_products(payload)

    def test_bitget_rejects_invalid_multiplier_and_unknown_status(self) -> None:
        base_product = {
            "symbol": "BTCUSDT",
            "category": "USDT-FUTURES",
            "baseCoin": "BTC",
            "quoteCoin": "USDT",
            "minOrderQty": "0.001",
            "maxOrderQty": "100",
            "pricePrecision": "2",
            "quantityPrecision": "3",
            "priceMultiplier": "0.01",
            "quantityMultiplier": "0.001",
            "minOrderAmount": "5",
            "type": "perpetual",
            "status": "online",
        }
        invalid_multiplier = deepcopy(base_product)
        invalid_multiplier["priceMultiplier"] = "0.005"
        unknown_status = deepcopy(base_product)
        unknown_status["status"] = "unknown"

        for product, message in (
            (invalid_multiplier, "priceMultiplier conflicts"),
            (unknown_status, "status has unknown value"),
        ):
            with self.subTest(message=message):
                with self.assertRaisesRegex(InstrumentDataError, message):
                    parse_bitget_futures_products(
                        {"code": "00000", "data": [product]}
                    )

    def test_known_non_trading_status_is_preserved_as_unavailable(self) -> None:
        payload = {
            "code": "00000",
            "data": [
                {
                    "symbol": "BTC-USDT",
                    "category": "SPOT",
                    "baseCoin": "BTC",
                    "quoteCoin": "USDT",
                    "minOrderQty": "0.000001",
                    "maxOrderQty": "0",
                    "pricePrecision": "2",
                    "quantityPrecision": "6",
                    "minOrderAmount": "1",
                    "status": "offline",
                }
            ],
        }

        (instrument,) = parse_bitget_spot_products(payload)

        self.assertEqual(instrument.status, TradingStatus.UNAVAILABLE)

    def test_binance_spot_known_non_trading_statuses_are_unavailable(self) -> None:
        for status in ("PRE_TRADING", "POST_TRADING", "AUCTION_MATCH"):
            with self.subTest(status=status):
                payload = {
                    "symbols": [
                        {
                            "symbol": "BTCUSDT",
                            "status": status,
                            "baseAsset": "BTC",
                            "quoteAsset": "USDT",
                            "filters": [
                                {
                                    "filterType": "PRICE_FILTER",
                                    "tickSize": "0.01",
                                },
                                {
                                    "filterType": "LOT_SIZE",
                                    "minQty": "0.001",
                                    "maxQty": "100",
                                    "stepSize": "0.001",
                                },
                                {
                                    "filterType": "MIN_NOTIONAL",
                                    "minNotional": "5",
                                },
                            ],
                        }
                    ]
                }

                (instrument,) = parse_binance_spot_products(payload)

                self.assertEqual(instrument.status, TradingStatus.UNAVAILABLE)

    def test_perpetual_parsers_skip_delivery_products(self) -> None:
        binance_payload = {
            "symbols": [
                {"symbol": "BTCUSDT_260925", "contractType": "CURRENT_QUARTER"},
                {
                    "symbol": "ETHUSDC",
                    "contractType": "PERPETUAL",
                    "quoteAsset": "USDC",
                    "marginAsset": "USDC",
                },
                {
                    "symbol": "BTCUSDT",
                    "contractType": "PERPETUAL",
                    "status": "TRADING",
                    "baseAsset": "BTC",
                    "quoteAsset": "USDT",
                    "marginAsset": "USDT",
                    "filters": [
                        {"filterType": "PRICE_FILTER", "tickSize": "0.1"},
                        {
                            "filterType": "LOT_SIZE",
                            "minQty": "0.001",
                            "maxQty": "100",
                            "stepSize": "0.001",
                        },
                        {"filterType": "MIN_NOTIONAL", "notional": "5"},
                    ],
                },
            ]
        }
        bitget_payload = {
            "code": "00000",
            "data": [
                {
                    "symbol": "BTCUSDT-DELIVERY",
                    "category": "USDT-FUTURES",
                    "type": "delivery",
                },
                {
                    "symbol": "BTCUSDT",
                    "category": "USDT-FUTURES",
                    "baseCoin": "BTC",
                    "quoteCoin": "USDT",
                    "minOrderQty": "0.001",
                    "maxOrderQty": "100",
                    "pricePrecision": "1",
                    "quantityPrecision": "3",
                    "priceMultiplier": "0.1",
                    "quantityMultiplier": "0.001",
                    "minOrderAmount": "5",
                    "type": "perpetual",
                    "status": "online",
                },
            ],
        }

        (binance,) = parse_binance_futures_products(binance_payload)
        (bitget,) = parse_bitget_futures_products(bitget_payload)

        self.assertEqual(binance.raw_symbol, "BTCUSDT")
        self.assertEqual(bitget.raw_symbol, "BTCUSDT")

        unknown_binance_type = {
            "symbols": [{"symbol": "BROKEN", "contractType": "UNKNOWN"}]
        }
        with self.assertRaisesRegex(InstrumentDataError, "contractType"):
            parse_binance_futures_products(unknown_binance_type)

        conflicting_bitget_quote = deepcopy(bitget_payload)
        conflicting_bitget_quote["data"] = [
            deepcopy(conflicting_bitget_quote["data"][1])
        ]
        conflicting_bitget_quote["data"][0]["quoteCoin"] = "USDC"
        with self.assertRaisesRegex(InstrumentDataError, "quoteCoin must be USDT"):
            parse_bitget_futures_products(conflicting_bitget_quote)

    def test_bitget_extreme_precision_has_a_field_specific_error(self) -> None:
        payload = {
            "code": "00000",
            "data": [
                {
                    "symbol": "BTC-USDT",
                    "category": "SPOT",
                    "baseCoin": "BTC",
                    "quoteCoin": "USDT",
                    "minOrderQty": "0.001",
                    "maxOrderQty": "100",
                    "pricePrecision": "999999999999999999999",
                    "quantityPrecision": "3",
                    "minOrderAmount": "5",
                    "status": "online",
                }
            ],
        }

        with self.assertRaisesRegex(
            InstrumentDataError, r"payload\.data\[0\]\.pricePrecision"
        ):
            parse_bitget_spot_products(payload)


if __name__ == "__main__":
    unittest.main()
