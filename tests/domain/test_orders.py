from datetime import datetime, timezone
from decimal import Decimal
import unittest

from app.domain.enums import Exchange, MarketType, TradingStatus
from app.domain.exceptions import OrderDataError, TradingRuleError
from app.domain.instruments.instrument import Instrument, TradingRules
from app.domain.orders.client_order_id import ClientOrderId
from app.domain.orders.fill import Fill
from app.domain.orders.order import (
    FuturesPositionSide,
    Order,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from app.execution.preflight_validator import prepare_order


NOW = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)


def _instrument(
    exchange: Exchange = Exchange.BINANCE,
    market_type: MarketType = MarketType.SPOT,
) -> Instrument:
    return Instrument(
        exchange=exchange,
        market_type=market_type,
        raw_symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        settlement_asset="USDT",
        rules=TradingRules(
            tick_size=Decimal("0.10"),
            quantity_step=Decimal("0.001"),
            minimum_quantity=Decimal("0.010"),
            maximum_quantity=Decimal("100"),
            minimum_notional=Decimal("5"),
            contract_multiplier=Decimal("1"),
        ),
        status=TradingStatus.TRADING,
        raw_status="TRADING",
    )


class OrderDomainTests(unittest.TestCase):
    def test_client_order_id_uses_common_exchange_safe_contract(self) -> None:
        value = ClientOrderId("arb-20260719-first")
        self.assertEqual(str(value), "arb-20260719-first")
        self.assertEqual(str(ClientOrderId("route/BTC:USDT")), "route/BTC:USDT")
        with self.assertRaisesRegex(OrderDataError, "1 to 32"):
            ClientOrderId("x" * 33)
        with self.assertRaisesRegex(OrderDataError, "unsupported character"):
            ClientOrderId("bad?id")

    def test_preflight_centrally_quantizes_price_and_quantity_down(self) -> None:
        request = OrderRequest(
            instrument=_instrument(),
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.0199"),
            price=Decimal("62500.199"),
            client_order_id=ClientOrderId("stage9-limit"),
        )

        normalized = prepare_order(request)

        self.assertEqual(normalized.price, Decimal("62500.10"))
        self.assertEqual(normalized.quantity, Decimal("0.019"))
        self.assertIsInstance(normalized.price, Decimal)
        self.assertIsInstance(normalized.quantity, Decimal)

    def test_market_preflight_requires_reference_price_for_minimum_rules(self) -> None:
        request = OrderRequest(
            instrument=_instrument(),
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.0119"),
            client_order_id=ClientOrderId("stage9-market"),
        )
        with self.assertRaisesRegex(TradingRuleError, "reference_price"):
            prepare_order(request)

        normalized = prepare_order(
            OrderRequest(
                instrument=request.instrument,
                side=request.side,
                order_type=request.order_type,
                quantity=request.quantity,
                client_order_id=request.client_order_id,
                reference_price=Decimal("62499.99"),
            )
        )
        self.assertEqual(normalized.quantity, Decimal("0.011"))
        self.assertIsNone(normalized.price)

    def test_futures_position_side_is_only_valid_for_perpetual_orders(self) -> None:
        with self.assertRaisesRegex(OrderDataError, "position_side"):
            OrderRequest(
                instrument=_instrument(),
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("1"),
                price=Decimal("10"),
                client_order_id=ClientOrderId("spot-position-side"),
                position_side=FuturesPositionSide.LONG,
            )

    def test_order_and_fill_enforce_decimal_and_cumulative_invariants(self) -> None:
        instrument = _instrument()
        fill = Fill(
            fill_id="trade-1",
            price=Decimal("62500.10"),
            quantity=Decimal("0.010"),
            fee=Decimal("0.625001"),
            fee_asset="USDT",
            executed_time=NOW,
        )
        order = Order(
            instrument=instrument,
            client_order_id=ClientOrderId("stage9-filled"),
            exchange_order_id="123",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            time_in_force=TimeInForce.GTC,
            original_quantity=Decimal("0.010"),
            price=Decimal("62500.10"),
            status=OrderStatus.FILLED,
            cumulative_filled_quantity=Decimal("0.010"),
            average_price=Decimal("62500.10"),
            cumulative_fee=Decimal("0.625001"),
            fee_asset="USDT",
            fills=(fill,),
            updated_time=NOW,
        )
        self.assertEqual(order.filled_base_quantity, Decimal("0.010"))
        self.assertTrue(order.is_terminal)

        with self.assertRaises(TypeError):
            Fill("trade-2", "62500.10", Decimal("0.01"), Decimal("0"), "USDT", NOW)
        with self.assertRaisesRegex(OrderDataError, "exceeds original_quantity"):
            Order(
                instrument=instrument,
                client_order_id=ClientOrderId("stage9-invalid"),
                exchange_order_id="124",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                time_in_force=TimeInForce.GTC,
                original_quantity=Decimal("0.010"),
                price=Decimal("62500.10"),
                status=OrderStatus.PARTIALLY_FILLED,
                cumulative_filled_quantity=Decimal("0.011"),
                average_price=Decimal("62500.10"),
                cumulative_fee=Decimal("0"),
                fee_asset=None,
                fills=(),
                updated_time=NOW,
            )


if __name__ == "__main__":
    unittest.main()
