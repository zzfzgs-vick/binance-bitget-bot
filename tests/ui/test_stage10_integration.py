from datetime import timedelta
from dataclasses import replace
from decimal import Decimal
import os
import time
import threading
import sys
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.application.dto.opportunity_dto import ExecutableOpportunity
from app.domain.accounts.account_snapshot import AccountState
from app.domain.accounts.balance import AssetBalance
from app.domain.arbitrage.arbitrage_position import ArbitragePosition
from app.domain.enums import Exchange, MarketType
from app.domain.orders.client_order_id import ClientOrderId
from app.domain.orders.order import OrderRequest, OrderSide, OrderType
from app.strategy.opportunity_engine import OpportunityRequest, calculate_opportunity
from app.ui.presenters.main_window_presenter import MainWindowPresenter
from app.ui.views.main_window import MainWindowView
from app.workers.execution_worker import ExecutionWorker
from app.workers.worker_signals import LiveEventBridge
from app.domain.arbitrage.arbitrage_position import PositionStatus
from app.domain.orders.order import OrderSide
from app.domain.orders.order import OrderStatus
from app.exchanges.base.exchange_errors import (
    ExchangeApiError,
    ExchangeResponseError,
    ExchangeTimeoutError,
)
from tests.domain.test_arbitrage_positions import NOW, _result
from tests.strategy.test_opportunity_engine import _book, _instrument


def _plan() -> ExecutableOpportunity:
    buy = _instrument(Exchange.BINANCE, MarketType.SPOT)
    sell = _instrument(Exchange.BITGET, MarketType.USDT_PERPETUAL)
    opportunity = calculate_opportunity(
        _book(
            buy,
            bids=(("59990", "1"),),
            asks=(("60000", "1"),),
            received_time=NOW,
        ),
        _book(
            sell,
            bids=(("60100", "1"),),
            asks=(("60110", "1"),),
            received_time=NOW,
        ),
        OpportunityRequest(
            base_quantity=Decimal("0.009"),
            quote_amount=None,
            buy_fee_rate=Decimal("0.001"),
            sell_fee_rate=Decimal("0.001"),
            now=NOW,
            max_age=timedelta(seconds=2),
        ),
    )
    first = OrderRequest(
        buy,
        OrderSide.BUY,
        OrderType.MARKET,
        opportunity.buy_leg.order_quantity,
        ClientOrderId("gui-open-first"),
        reference_price=opportunity.buy_leg.average_price,
    )
    second = OrderRequest(
        sell,
        OrderSide.SELL,
        OrderType.MARKET,
        opportunity.sell_leg.order_quantity,
        ClientOrderId("gui-open-second"),
        reference_price=opportunity.sell_leg.average_price,
    )
    return ExecutableOpportunity("gui-position", opportunity, first, second)


class Stage10PresenterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_presenters_render_normalized_live_state_in_existing_widgets(self) -> None:
        view = MainWindowView()
        presenter = MainWindowPresenter(view)
        presenter.bind()
        plan = _plan()
        position = ArbitragePosition.from_execution("gui-position", _result(), NOW)
        account = AccountState(
            Exchange.BINANCE,
            (
                AssetBalance(
                    Exchange.BINANCE,
                    MarketType.SPOT,
                    "USDT",
                    Decimal("100"),
                    Decimal("90"),
                    Decimal("10"),
                    None,
                ),
            ),
            (),
        )

        presenter.set_opportunities((plan,))
        presenter.set_account_states((account,))
        presenter.set_positions((position,))
        view.widgets.opportunity_table.selectRow(0)
        self.app.processEvents()

        self.assertEqual(view.widgets.opportunity_table.model().rowCount(), 1)
        self.assertEqual(view.widgets.position_table.model().rowCount(), 1)
        self.assertEqual(view.widgets.selected_symbol_label.text(), "BTC/USDT")
        self.assertIn("USDT", view.widgets.binance_spot_balance_value_label.text())
        self.assertIn("0.009", view.widgets.position_spot_leg_label.text())

        requested: list[str] = []
        view.close_position_requested.connect(requested.append)
        action = view.widgets.position_table.model().index(0, 12)
        view.widgets.position_table.doubleClicked.emit(action)
        self.assertEqual(requested, ["gui-position"])
        view.dispose()
        self.app.processEvents()

    def test_gui_requires_explicit_open_and_close_actions(self) -> None:
        view = MainWindowView()
        plan = _plan()
        first_client = Mock()
        second_client = Mock()

        def first_order(request):
            price = "60000" if request.side is OrderSide.BUY else "60200"
            fee = "0.54" if request.side is OrderSide.BUY else "0.5418"
            return _filled(request, "0.009", price, fee, f"first-{request.side.value}")

        def second_order(request):
            price = "60100" if request.side is OrderSide.SELL else "59900"
            fee = "0.5409" if request.side is OrderSide.SELL else "0.5391"
            return _filled(request, "0.009", price, fee, f"second-{request.side.value}")

        from tests.domain.test_arbitrage_positions import _filled

        first_client.create_order.side_effect = first_order
        second_client.create_order.side_effect = second_order
        clients = {
            (plan.first_request.instrument.exchange, plan.first_request.instrument.market_type): first_client,
            (plan.second_request.instrument.exchange, plan.second_request.instrument.market_type): second_client,
        }
        worker = ExecutionWorker(trading_clients=clients)
        presenter = MainWindowPresenter(
            view,
            execution_worker=worker,
        )
        presenter.bind()
        presenter.set_opportunities((plan,))
        view.widgets.opportunity_table.selectRow(0)
        self.app.processEvents()

        self.assertTrue(view.widgets.live_order_button.isEnabled())
        self.assertFalse(view.widgets.confirm_dual_leg_button.isEnabled())
        view.widgets.live_order_button.click()
        self.assertTrue(view.widgets.confirm_dual_leg_button.isEnabled())
        view.widgets.confirm_dual_leg_button.click()
        self._wait_until(lambda: view.widgets.position_table.model().rowCount() == 1)

        presenter.mark_position(
            plan.position_id,
            first_price=Decimal("60200"),
            second_price=Decimal("59900"),
        )
        action = view.widgets.position_table.model().index(0, 12)
        view.widgets.position_table.doubleClicked.emit(action)
        self._wait_until(
            lambda: view.widgets.position_table.model().data(
                view.widgets.position_table.model().index(0, 11)
            )
            == PositionStatus.CLOSED.value
        )

        self.assertEqual(first_client.create_order.call_count, 2)
        self.assertEqual(second_client.create_order.call_count, 2)
        presenter.shutdown()
        presenter.shutdown()
        view.dispose()
        self.app.processEvents()

    def test_readiness_loss_requires_explicit_confirmation_before_deferred_submit(self) -> None:
        from tests.domain.test_arbitrage_positions import _filled

        view = MainWindowView()
        plan = _plan()
        ready = threading.Event()
        ready.set()
        first_client = Mock()
        second_client = Mock()

        def first_order(request):
            ready.clear()
            return _filled(request, "0.009", "60000", "0", "deferred-first")

        first_client.create_order.side_effect = first_order
        second_client.create_order.side_effect = lambda request: _filled(
            request, "0.009", "60100", "0", "deferred-second"
        )
        worker = ExecutionWorker(
            trading_clients={
                (plan.first_request.instrument.exchange, plan.first_request.instrument.market_type): first_client,
                (plan.second_request.instrument.exchange, plan.second_request.instrument.market_type): second_client,
            }
        )
        worker.set_readiness_check(lambda _instruments: ready.is_set())
        presenter = MainWindowPresenter(view, execution_worker=worker)
        presenter.bind()
        presenter.set_opportunities((plan,))
        view.widgets.opportunity_table.selectRow(0)
        self.app.processEvents()

        view.widgets.live_order_button.click()
        view.widgets.confirm_dual_leg_button.click()
        self._wait_until(
            lambda: view.widgets.live_order_button.text()
            == "继续未发送的 LIVE 订单"
        )
        second_client.create_order.assert_not_called()

        ready.set()
        view.widgets.live_order_button.click()
        self.assertTrue(view.widgets.confirm_dual_leg_button.isEnabled())
        second_client.create_order.assert_not_called()
        view.widgets.confirm_dual_leg_button.click()
        self._wait_until(
            lambda: view.widgets.position_table.model().rowCount() == 1
        )

        first_client.create_order.assert_called_once()
        second_client.create_order.assert_called_once()
        presenter.shutdown()
        view.dispose()
        self.app.processEvents()

    def test_shutdown_drops_worker_callbacks_before_qt_objects_are_destroyed(self) -> None:
        from tests.domain.test_arbitrage_positions import _filled

        view = MainWindowView()
        plan = _plan()
        release = threading.Event()
        first_client = Mock()
        second_client = Mock()

        def delayed(request):
            release.wait(timeout=1)
            return _filled(request, "0.009", "60000", "0", "shutdown-first")

        first_client.create_order.side_effect = delayed
        second_client.create_order.side_effect = lambda request: _filled(
            request, "0.009", "60100", "0", "shutdown-second"
        )
        worker = ExecutionWorker(
            trading_clients={
                (plan.first_request.instrument.exchange, plan.first_request.instrument.market_type): first_client,
                (plan.second_request.instrument.exchange, plan.second_request.instrument.market_type): second_client,
            }
        )
        presenter = MainWindowPresenter(view, execution_worker=worker)
        presenter.bind()
        caught = []
        previous_hook = sys.excepthook
        sys.excepthook = lambda *details: caught.append(details)
        try:
            worker.submit_open(plan)
            release.set()
            presenter.shutdown()
            view.dispose()
            self.app.processEvents()
        finally:
            sys.excepthook = previous_hook
        self.assertEqual(caught, [])

    def test_queued_status_after_dispose_is_a_tested_no_op(self) -> None:
        view = MainWindowView()
        bridge = LiveEventBridge()
        bridge.status_updated.connect(view.set_status)
        caught = []
        previous_hook = sys.excepthook
        sys.excepthook = lambda *details: caught.append(details)
        try:
            publisher = threading.Thread(
                target=bridge.publish_status, args=("queued status",)
            )
            publisher.start()
            publisher.join(timeout=1)
            view.dispose()
            self.app.processEvents()
        finally:
            sys.excepthook = previous_hook
            bridge.deleteLater()
        self.assertEqual(caught, [])

    def test_background_live_state_enters_gui_only_through_qt_signal_bridge(self) -> None:
        view = MainWindowView()
        presenter = MainWindowPresenter(view)
        presenter.bind()
        bridge = LiveEventBridge()
        bridge.account_states_updated.connect(presenter.set_account_states)
        account = AccountState(
            Exchange.BITGET,
            (
                AssetBalance(
                    Exchange.BITGET,
                    None,
                    "USDT",
                    Decimal("55"),
                    Decimal("50"),
                    Decimal("5"),
                    Decimal("55"),
                ),
            ),
            (),
        )

        publisher = threading.Thread(
            target=bridge.publish_account_states,
            args=((account,),),
        )
        publisher.start()
        publisher.join(timeout=1)
        self._wait_until(
            lambda: "USDT" in view.widgets.bitget_spot_balance_value_label.text()
        )

        self.assertFalse(publisher.is_alive())
        bridge.deleteLater()
        view.dispose()
        self.app.processEvents()

    def test_gui_retries_remaining_leg_after_mark_to_market_update(self) -> None:
        from tests.domain.test_arbitrage_positions import _filled

        view = MainWindowView()
        plan = _plan()
        first_client = Mock()
        second_client = Mock()
        first_client.create_order.side_effect = lambda request: _filled(
            request,
            "0.009",
            "60000" if request.side is OrderSide.BUY else "60200",
            "0",
            f"first-{request.side.value}",
        )
        close_attempts = 0

        def second_order(request):
            nonlocal close_attempts
            if request.side is OrderSide.BUY:
                close_attempts += 1
                if close_attempts == 1:
                    raise ExchangeApiError("Bitget", "25202", "insufficient balance")
                return _filled(request, "0.009", "59900", "0", "second-close")
            return _filled(request, "0.009", "60100", "0", "second-open")

        second_client.create_order.side_effect = second_order
        clients = {
            (plan.first_request.instrument.exchange, plan.first_request.instrument.market_type): first_client,
            (plan.second_request.instrument.exchange, plan.second_request.instrument.market_type): second_client,
        }
        worker = ExecutionWorker(trading_clients=clients)
        presenter = MainWindowPresenter(view, execution_worker=worker)
        presenter.bind()
        presenter.set_opportunities((plan,))
        view.widgets.opportunity_table.selectRow(0)
        self.app.processEvents()
        view.widgets.live_order_button.click()
        view.widgets.confirm_dual_leg_button.click()
        self._wait_until(lambda: view.widgets.position_table.model().rowCount() == 1)
        presenter.mark_position(
            plan.position_id,
            first_price=Decimal("60200"),
            second_price=Decimal("59900"),
        )
        action = view.widgets.position_table.model().index(0, 12)
        view.widgets.position_table.doubleClicked.emit(action)
        self._wait_until(
            lambda: view.widgets.position_table.model().data(
                view.widgets.position_table.model().index(0, 11)
            )
            == PositionStatus.CLOSE_FAILED.value
        )

        view.widgets.position_table.doubleClicked.emit(action)
        self._wait_until(
            lambda: view.widgets.position_table.model().data(
                view.widgets.position_table.model().index(0, 11)
            )
            == PositionStatus.CLOSED.value
        )

        self.assertEqual(first_client.create_order.call_count, 2)
        self.assertEqual(second_client.create_order.call_count, 3)
        presenter.shutdown()
        view.dispose()
        self.app.processEvents()

    def test_private_order_signal_finishes_rest_partial_open(self) -> None:
        from tests.domain.test_arbitrage_positions import _filled

        view = MainWindowView()
        plan = _plan()
        first_client = Mock()
        second_client = Mock()
        partial = replace(
            _filled(plan.first_request, "0.004", "60000", "0.24", "open-1"),
            status=OrderStatus.PARTIALLY_FILLED,
        )
        first_client.create_order.return_value = partial
        second_client.create_order.side_effect = lambda request: _filled(
            request, "0.009", "60100", "0.5409", "open-2"
        )
        clients = {
            (plan.first_request.instrument.exchange, plan.first_request.instrument.market_type): first_client,
            (plan.second_request.instrument.exchange, plan.second_request.instrument.market_type): second_client,
        }
        worker = ExecutionWorker(trading_clients=clients)
        presenter = MainWindowPresenter(view, execution_worker=worker)
        presenter.bind()
        bridge = LiveEventBridge()
        bridge.private_order_event.connect(worker.reconcile_private_order)
        presenter.set_opportunities((plan,))
        view.widgets.opportunity_table.selectRow(0)
        self.app.processEvents()
        view.widgets.live_order_button.click()
        view.widgets.confirm_dual_leg_button.click()
        self._wait_until(lambda: first_client.create_order.call_count == 1)
        self.assertEqual(view.widgets.position_table.model().rowCount(), 0)

        completed = replace(
            partial,
            status=OrderStatus.FILLED,
            cumulative_filled_quantity=Decimal("0.009"),
            cumulative_fee=Decimal("0.54"),
            updated_time=NOW + timedelta(milliseconds=1),
        )
        bridge.publish_private_order_event(completed)
        self._wait_until(lambda: view.widgets.position_table.model().rowCount() == 1)

        self.assertEqual(second_client.create_order.call_count, 1)
        presenter.shutdown()
        bridge.deleteLater()
        view.dispose()
        self.app.processEvents()

    def test_unknown_open_exposes_query_only_resume_action(self) -> None:
        from tests.domain.test_arbitrage_positions import _filled

        view = MainWindowView()
        plan = _plan()
        first_client = Mock()
        second_client = Mock()
        first_client.create_order.side_effect = ExchangeTimeoutError("timeout")
        first_client.query_order.side_effect = [
            ExchangeResponseError("still unknown"),
            _filled(plan.first_request, "0.009", "60000", "0.54", "open-1"),
        ]
        second_client.create_order.side_effect = lambda request: _filled(
            request, "0.009", "60100", "0.5409", "open-2"
        )
        clients = {
            (plan.first_request.instrument.exchange, plan.first_request.instrument.market_type): first_client,
            (plan.second_request.instrument.exchange, plan.second_request.instrument.market_type): second_client,
        }
        worker = ExecutionWorker(trading_clients=clients)
        presenter = MainWindowPresenter(view, execution_worker=worker)
        presenter.bind()
        presenter.set_opportunities((plan,))
        view.widgets.opportunity_table.selectRow(0)
        self.app.processEvents()
        view.widgets.live_order_button.click()
        view.widgets.confirm_dual_leg_button.click()
        self._wait_until(
            lambda: view.widgets.live_order_button.text() == "查询原订单状态"
        )

        presenter.set_opportunities((plan, replace(plan, position_id="other-plan")))
        view.widgets.opportunity_table.selectRow(1)
        self.app.processEvents()
        self.assertEqual(view.widgets.live_order_button.text(), "查询原订单状态")

        view.widgets.live_order_button.click()
        self._wait_until(lambda: view.widgets.position_table.model().rowCount() == 1)

        first_client.create_order.assert_called_once()
        self.assertEqual(first_client.query_order.call_count, 2)
        second_client.create_order.assert_called_once()
        presenter.shutdown()
        view.dispose()
        self.app.processEvents()

    def _wait_until(self, predicate) -> None:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(0.01)
        self.fail("timed out waiting for GUI update")


if __name__ == "__main__":
    unittest.main()
