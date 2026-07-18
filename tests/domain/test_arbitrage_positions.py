from datetime import datetime, timezone
from decimal import Decimal
import unittest

from app.domain.enums import Exchange, MarketType, TradingStatus
from app.domain.exceptions import PositionDataError
from app.domain.instruments.instrument import Instrument, TradingRules
from app.domain.orders.client_order_id import ClientOrderId
from app.domain.orders.order import Order, OrderRequest, OrderSide, OrderStatus, OrderType, TimeInForce
from app.domain.orders.order_group import DualLegExecutionResult, DualLegStatus
from app.domain.orders.order_leg import LegRole, successful_leg
from app.domain.arbitrage.arbitrage_position import ArbitragePosition, PositionStatus


NOW = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)


def _instrument(exchange: Exchange, market: MarketType) -> Instrument:
    return Instrument(
        exchange=exchange,
        market_type=market,
        raw_symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        settlement_asset="USDT",
        rules=TradingRules(
            tick_size=Decimal("0.1"),
            quantity_step=Decimal("0.001"),
            minimum_quantity=Decimal("0.001"),
            maximum_quantity=Decimal("100"),
            minimum_notional=Decimal("5"),
            contract_multiplier=Decimal("1"),
        ),
        status=TradingStatus.TRADING,
        raw_status="TRADING",
    )


def _request(exchange: Exchange, market: MarketType, side: OrderSide, client_id: str) -> OrderRequest:
    return OrderRequest(
        instrument=_instrument(exchange, market),
        side=side,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.010"),
        reference_price=Decimal("60000"),
        client_order_id=ClientOrderId(client_id),
    )


def _filled(request: OrderRequest, quantity: str, price: str, fee: str, order_id: str) -> Order:
    return Order(
        instrument=request.instrument,
        client_order_id=request.client_order_id,
        exchange_order_id=order_id,
        side=request.side,
        order_type=request.order_type,
        time_in_force=TimeInForce.GTC,
        original_quantity=request.quantity,
        price=None,
        status=OrderStatus.FILLED,
        cumulative_filled_quantity=Decimal(quantity),
        average_price=Decimal(price),
        cumulative_fee=Decimal(fee),
        fee_asset="USDT",
        fills=(),
        updated_time=NOW,
    )


def _result(first_quantity: str = "0.009", second_quantity: str = "0.009") -> DualLegExecutionResult:
    first_request = _request(Exchange.BINANCE, MarketType.SPOT, OrderSide.BUY, "open-first")
    second_request = _request(Exchange.BITGET, MarketType.USDT_PERPETUAL, OrderSide.SELL, "open-second")
    first_order = _filled(first_request, first_quantity, "60000", "0.54", "1")
    second_order = _filled(second_request, second_quantity, "60100", "0.5409", "2")
    return DualLegExecutionResult(
        DualLegStatus.COMPLETED,
        successful_leg(LegRole.FIRST, first_request, first_order),
        successful_leg(LegRole.SECOND, second_request, second_order),
    )


class ArbitragePositionTests(unittest.TestCase):
    def test_completed_execution_creates_position_from_actual_fills(self) -> None:
        position = ArbitragePosition.from_execution("position-1", _result(), NOW)

        self.assertEqual(position.status, PositionStatus.OPEN)
        self.assertEqual(position.first_leg.open_quantity, Decimal("0.009"))
        self.assertEqual(position.second_leg.open_quantity, Decimal("0.009"))
        self.assertEqual(position.first_leg.open_average_price, Decimal("60000"))
        self.assertEqual(position.second_leg.open_average_price, Decimal("60100"))
        self.assertEqual(position.first_leg.open_fee, Decimal("0.54"))
        self.assertEqual(position.second_leg.open_fee, Decimal("0.5409"))
        self.assertEqual(position.realized_pnl, Decimal("-1.0809"))
        self.assertEqual(position.unrealized_pnl, Decimal("0"))

    def test_incomplete_or_quantity_mismatched_execution_is_rejected(self) -> None:
        with self.assertRaisesRegex(PositionDataError, "completed"):
            ArbitragePosition.from_execution(
                "bad-status",
                DualLegExecutionResult(
                    DualLegStatus.FIRST_INCOMPLETE,
                    _result().first,
                    None,
                ),
                NOW,
            )
        with self.assertRaisesRegex(PositionDataError, "quantity"):
            ArbitragePosition.from_execution(
                "bad-quantity", _result(second_quantity="0.008"), NOW
            )

    def test_mark_to_market_uses_remaining_actual_quantities(self) -> None:
        position = ArbitragePosition.from_execution("marked", _result(), NOW)

        marked = position.mark_to_market(
            first_price=Decimal("60200"),
            second_price=Decimal("59900"),
        )

        self.assertEqual(marked.unrealized_pnl, Decimal("3.6"))
        self.assertEqual(position.unrealized_pnl, Decimal("0"))
        with self.assertRaises(TypeError):
            position.mark_to_market(first_price=60200.0, second_price=Decimal("59900"))


if __name__ == "__main__":
    unittest.main()
