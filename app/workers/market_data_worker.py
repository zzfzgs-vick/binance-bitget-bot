"""LIVE product, account, market-data, and opportunity orchestration."""

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import logging
import threading

from app.accounts.account_service import AccountStateStore
from app.domain.accounts.futures_position import PositionMode
from app.application.dto.opportunity_dto import ExecutableOpportunity
from app.domain.enums import Exchange, MarketType
from app.domain.arbitrage.arbitrage_position import PositionStatus
from app.domain.market.order_book import OrderBook, OrderBookUpdate, UpdateResult
from app.domain.orders.order import (
    FuturesPositionSide,
    OrderRequest,
    OrderSide,
    OrderType,
)
from app.execution.client_order_id_factory import ClientOrderIdFactory
from app.exchanges.binance.mappers import account_mapper as binance_accounts
from app.exchanges.binance.mappers import instrument_mapper as binance_instruments
from app.exchanges.binance.mappers import order_mapper as binance_orders
from app.exchanges.binance.mappers import quote_mapper as binance_quotes
from app.exchanges.bitget.mappers import account_mapper as bitget_accounts
from app.exchanges.bitget.mappers import instrument_mapper as bitget_instruments
from app.exchanges.bitget.mappers import order_mapper as bitget_orders
from app.exchanges.bitget.mappers import quote_mapper as bitget_quotes
from app.strategy.instrument_registry import InstrumentRegistry
from app.strategy.opportunity_engine import OpportunityRequest, calculate_opportunity


_LOGGER = logging.getLogger("binance_bitget_bot.live_data")
_MAX_BUFFERED_BOOK_UPDATES = 2_000


class LiveDataWorker:
    """Own all non-Qt LIVE sources; every blocking REST call runs in its pool."""

    def __init__(
        self,
        *,
        bridge,
        market_clients: dict,
        account_clients: dict,
        trading_clients: dict,
        public_websockets: dict,
        private_streams: dict | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._bridge = bridge
        self._market_clients = market_clients
        self._account_clients = account_clients
        self._trading_clients = trading_clients
        self._public_websockets = public_websockets
        self._private_streams = private_streams or {}
        self._logger = logger or _LOGGER
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="live-data-rest")
        self._registry = InstrumentRegistry()
        self._account_stores = {
            Exchange.BINANCE: AccountStateStore(Exchange.BINANCE),
            Exchange.BITGET: AccountStateStore(Exchange.BITGET),
        }
        self._position_modes: dict[Exchange, PositionMode] = {}
        self._books: dict[object, OrderBook] = {}
        self._snapshots_pending: set[object] = set()
        self._snapshot_buffers: dict[
            object, dict[int, OrderBookUpdate]
        ] = {}
        self._fees: dict[object, Decimal] = {}
        self._selected: tuple[object, ...] = ()
        self._positions: tuple[object, ...] = ()
        self._quote_amount: Decimal | None = None
        self._ids = ClientOrderIdFactory("live")
        self._lock = threading.RLock()
        self._started = False
        self._shutdown = False

    @property
    def instruments(self) -> tuple[object, ...]:
        return self._registry.instruments

    def is_execution_ready(self, instruments: tuple[object, ...]) -> bool:
        with self._lock:
            if not self._started or self._shutdown or not self._private_streams:
                return False
            streams = []
            for instrument in instruments:
                stream = self._private_streams.get(
                    _instrument_key(instrument)
                ) or self._private_streams.get((instrument.exchange, None))
                if stream is None:
                    return False
                streams.append(stream)
        return all(bool(getattr(stream, "is_connected", False)) for stream in streams)

    def start(self) -> Future | None:
        with self._lock:
            if self._shutdown:
                raise RuntimeError("live data worker is shut down")
            if self._started:
                return None
            self._started = True
        started = []
        try:
            for websocket in self._public_websockets.values():
                websocket.start()
                started.append(websocket)
        except Exception:
            for websocket in reversed(started):
                try:
                    websocket.stop()
                except Exception:
                    pass
            with self._lock:
                self._started = False
            raise
        return self._submit(self._initialize)

    def refresh_products(self) -> Future:
        return self._submit(self._load_products)

    def refresh_accounts(self) -> Future:
        return self._submit(self._load_accounts)

    def select_symbol(self, symbol: str, quote_amount_text: str) -> Future:
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol must not be empty")
        try:
            amount = Decimal(quote_amount_text.strip())
        except (InvalidOperation, AttributeError):
            raise ValueError("investment amount must be a decimal string") from None
        if not amount.is_finite() or amount <= 0:
            raise ValueError("investment amount must be positive")
        return self._submit(self._select_symbol, symbol, amount)

    def track_positions(self, positions: tuple[object, ...]) -> None:
        with self._lock:
            if self._shutdown:
                return
            previous = self._active_instruments()
            self._positions = tuple(positions)
            current = self._active_instruments()
            self._retain_active_books(current)
        self._sync_subscriptions(previous, current)

    def handle_market_message(self, key, message: object) -> None:
        received = datetime.now(timezone.utc)
        try:
            symbol = _message_symbol(key, message)
            with self._lock:
                selected = tuple(
                    item
                    for item in self._active_instruments()
                    if _instrument_key(item) == key
                    and (symbol is None or item.raw_symbol == symbol)
                )
            for instrument in selected:
                parser = (
                    binance_quotes.parse_message
                    if instrument.exchange is Exchange.BINANCE
                    else bitget_quotes.parse_message
                )
                events = parser(message, instrument, received)
                for event in events:
                    if isinstance(event, OrderBookUpdate):
                        request_snapshot = False
                        with self._lock:
                            book = self._book(instrument)
                            state = book.snapshot()
                            if event.is_snapshot:
                                result, request_snapshot = (
                                    self._apply_snapshot_and_replay(event)
                                )
                                self._snapshots_pending.discard(instrument)
                            elif (
                                not event.is_snapshot
                                and (
                                    state.requires_snapshot
                                    or instrument in self._snapshots_pending
                                )
                            ):
                                self._buffer_update(event)
                                result = UpdateResult.RESYNC_REQUIRED
                                request_snapshot = True
                            else:
                                result = book.apply(event)
                                if result in {
                                    UpdateResult.GAP_DETECTED,
                                    UpdateResult.RESYNC_REQUIRED,
                                }:
                                    self._buffer_update(event)
                                    request_snapshot = True
                        if request_snapshot:
                            self._request_snapshot(instrument)
            self._publish_opportunities()
            self._publish_position_prices()
        except Exception as exc:
            self._safe_failure("market message", exc)

    def handle_private_message(self, exchange: Exchange, message: object) -> None:
        received = datetime.now(timezone.utc)
        try:
            with self._lock:
                instruments = self._registry.for_exchange(exchange)
            if exchange is Exchange.BINANCE:
                account_event = binance_accounts.parse_private_message(
                    message, instruments, received
                )
                with self._lock:
                    order_instruments = self._registry.for_binance_orders()
                order_event = binance_orders.parse_private_message(
                    message, order_instruments, received
                )
            else:
                topic = (
                    message.get("arg", {}).get("topic")
                    if isinstance(message, dict)
                    else None
                )
                account_event = (
                    bitget_accounts.parse_private_message(message, instruments, received)
                    if topic in (None, "account", "position")
                    else None
                )
                order_event = (
                    bitget_orders.parse_private_message(
                        message,
                        {(item.market_type, item.raw_symbol): item for item in instruments.values()},
                        received,
                    )
                    if topic in (None, "order", "fill")
                    else None
                )
            if account_event is not None:
                with self._lock:
                    self._remember_position_mode(account_event)
                    self._account_stores[exchange].apply(account_event)
                self._publish_accounts()
            if order_event is not None:
                events = order_event if isinstance(order_event, tuple) else (order_event,)
                for event in events:
                    self._bridge.publish_private_order_event(event)
        except Exception as exc:
            self._safe_failure("private message", exc)

    def shutdown(self) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
        first_error: Exception | None = None
        stop_futures = [
            self._pool.submit(stream.stop)
            for stream in reversed(tuple(self._private_streams.values()))
        ]
        for websocket in reversed(tuple(self._public_websockets.values())):
            try:
                websocket.stop()
            except Exception as exc:
                first_error = first_error or exc
        self._pool.shutdown(wait=True, cancel_futures=False)
        for future in stop_futures:
            try:
                future.result()
            except Exception as exc:
                first_error = first_error or exc
        if first_error is not None:
            raise first_error

    def _initialize(self) -> None:
        self._load_products()
        if self._account_clients:
            self._load_accounts()
        if not self._shutdown:
            started = []
            try:
                for stream in self._private_streams.values():
                    stream.start()
                    started.append(stream)
            except Exception:
                for stream in reversed(started):
                    try:
                        stream.stop()
                    except Exception:
                        pass
                raise

    def _load_products(self) -> None:
        instruments = []
        parsers = {
            (Exchange.BINANCE, MarketType.SPOT): binance_instruments.parse_spot_products,
            (Exchange.BINANCE, MarketType.USDT_PERPETUAL): binance_instruments.parse_usdt_perpetual_products,
            (Exchange.BITGET, MarketType.SPOT): bitget_instruments.parse_spot_products,
            (Exchange.BITGET, MarketType.USDT_PERPETUAL): bitget_instruments.parse_usdt_perpetual_products,
        }
        for key, client in self._market_clients.items():
            instruments.extend(parsers[key](client.get_raw_product_info()))
        with self._lock:
            self._registry.replace(tuple(instruments))
        self._bridge.publish_status(f"已加载 {len(instruments)} 个正式实盘产品")

    def _load_accounts(self) -> None:
        now = datetime.now(timezone.utc)
        binance_spot = self._account_clients.get((Exchange.BINANCE, MarketType.SPOT))
        binance_future = self._account_clients.get((Exchange.BINANCE, MarketType.USDT_PERPETUAL))
        bitget = self._account_clients.get((Exchange.BITGET, None))
        if binance_spot is not None:
            event = binance_accounts.parse_spot_account(
                binance_spot.get_account(), now
            )
            with self._lock:
                self._remember_position_mode(event)
                self._account_stores[Exchange.BINANCE].apply(event)
        if binance_future is not None:
            with self._lock:
                instruments = self._registry.for_exchange(Exchange.BINANCE)
            event = binance_accounts.parse_futures_account(
                binance_future.get_account(),
                binance_future.get_positions(),
                instruments,
                now,
            )
            with self._lock:
                self._remember_position_mode(event)
                self._account_stores[Exchange.BINANCE].apply(event)
        if bitget is not None:
            position_mode = bitget_accounts.parse_account_settings(
                bitget.get_settings()
            )
            account_event = bitget_accounts.parse_account(bitget.get_account(), now)
            with self._lock:
                instruments = self._registry.for_exchange(Exchange.BITGET)
            position_event = bitget_accounts.parse_positions(
                bitget.get_positions(),
                instruments,
                now,
            )
            with self._lock:
                self._position_modes[Exchange.BITGET] = position_mode
                self._remember_position_mode(account_event)
                self._account_stores[Exchange.BITGET].apply(account_event)
                self._remember_position_mode(position_event)
                self._account_stores[Exchange.BITGET].apply(position_event)
        self._publish_accounts()

    def _select_symbol(self, symbol: str, amount: Decimal) -> None:
        selected = self._registry.search(symbol)
        if len({item.exchange for item in selected}) < 2:
            raise ValueError("symbol has no compatible Binance/Bitget LIVE pair")
        with self._lock:
            previous = self._active_instruments()
            self._selected = selected
            self._quote_amount = amount
            current = self._active_instruments()
            self._retain_active_books(current)
            self._fees.clear()
        self._sync_subscriptions(previous, current)
        for instrument in selected:
            client = self._trading_clients[_instrument_key(instrument)]
            self._fees[instrument] = client.get_taker_fee_rate(instrument.raw_symbol)
        self._bridge.publish_status(f"已订阅 {symbol.upper()} 正式实盘行情")

    def _load_snapshot(self, instrument) -> None:
        resync = False
        completed = False
        try:
            if instrument.exchange is not Exchange.BINANCE:
                return
            payload = self._market_clients[_instrument_key(instrument)].get_order_book(
                instrument.raw_symbol
            )
            for event in binance_quotes.parse_message(
                payload, instrument, datetime.now(timezone.utc)
            ):
                if isinstance(event, OrderBookUpdate):
                    with self._lock:
                        if instrument not in self._active_instruments():
                            return
                        book = self._book(instrument)
                        current = book.snapshot()
                        if (
                            current.is_valid
                            and not current.requires_snapshot
                            and current.sequence is not None
                            and event.sequence <= current.sequence
                        ):
                            continue
                        _result, resync = self._apply_snapshot_and_replay(event)
                        self._snapshots_pending.discard(instrument)
                        completed = True
        finally:
            if not completed:
                with self._lock:
                    self._snapshots_pending.discard(instrument)
        if resync:
            self._request_snapshot(instrument)

    def _request_snapshot(self, instrument) -> None:
        with self._lock:
            if self._shutdown or instrument in self._snapshots_pending:
                return
            self._snapshots_pending.add(instrument)
        if instrument.exchange is Exchange.BITGET:
            try:
                websocket = self._public_websockets[_instrument_key(instrument)]
                subscriptions = _market_subscriptions(instrument)
                websocket.unsubscribe(*subscriptions)
                websocket.subscribe(*subscriptions)
            except Exception:
                with self._lock:
                    self._snapshots_pending.discard(instrument)
                raise
            return
        try:
            self._submit(self._load_snapshot, instrument)
        except Exception:
            with self._lock:
                self._snapshots_pending.discard(instrument)
            raise

    def _publish_opportunities(self) -> None:
        with self._lock:
            selected = self._selected
            amount = self._quote_amount
            if amount is None or any(item not in self._fees for item in selected):
                return
            plans = []
            now = datetime.now(timezone.utc)
            for buy in selected:
                for sell in selected:
                    if buy.exchange is sell.exchange:
                        continue
                    try:
                        opportunity = calculate_opportunity(
                            self._book(buy).snapshot(),
                            self._book(sell).snapshot(),
                            OpportunityRequest(
                                base_quantity=None,
                                quote_amount=amount,
                                buy_fee_rate=self._fees[buy],
                                sell_fee_rate=self._fees[sell],
                                now=now,
                                max_age=timedelta(seconds=5),
                            ),
                        )
                        first_position_side = self._position_side(
                            buy, OrderSide.BUY
                        )
                        second_position_side = self._position_side(
                            sell, OrderSide.SELL
                        )
                    except ValueError:
                        continue
                    first_id = self._ids.create("a")
                    second_id = self._ids.create("b")
                    first = OrderRequest(
                        buy, OrderSide.BUY, OrderType.MARKET,
                        opportunity.buy_leg.order_quantity, first_id,
                        reference_price=opportunity.buy_leg.average_price,
                        position_side=first_position_side,
                    )
                    second = OrderRequest(
                        sell, OrderSide.SELL, OrderType.MARKET,
                        opportunity.sell_leg.order_quantity, second_id,
                        reference_price=opportunity.sell_leg.average_price,
                        position_side=second_position_side,
                    )
                    plans.append(
                        ExecutableOpportunity(
                            str(first_id),
                            opportunity,
                            first,
                            second,
                            expires_at=now + timedelta(seconds=5),
                        )
                    )
        self._bridge.publish_opportunities(tuple(plans))

    def _publish_accounts(self) -> None:
        with self._lock:
            states = tuple(store.state for store in self._account_stores.values())
        self._bridge.publish_account_states(states)

    def _remember_position_mode(self, event) -> None:
        modes = {position.mode for position in event.positions}
        if len(modes) > 1:
            raise ValueError("account event contains conflicting position modes")
        if modes:
            self._position_modes[event.exchange] = next(iter(modes))

    def _position_side(self, instrument, side: OrderSide):
        if instrument.market_type is not MarketType.USDT_PERPETUAL:
            return None
        mode = self._position_modes.get(instrument.exchange)
        if mode is None:
            raise ValueError("futures position mode is not synchronized")
        if mode is PositionMode.ONE_WAY:
            return FuturesPositionSide.BOTH
        return (
            FuturesPositionSide.LONG
            if side is OrderSide.BUY
            else FuturesPositionSide.SHORT
        )

    def _publish_position_prices(self) -> None:
        with self._lock:
            positions = self._positions
            for position in positions:
                prices = []
                for leg in (position.first_leg, position.second_leg):
                    snapshot = self._book(leg.instrument).snapshot()
                    if (
                        not snapshot.is_valid
                        or not snapshot.bids
                        or not snapshot.asks
                        or snapshot.received_time is None
                        or datetime.now(timezone.utc) - snapshot.received_time
                        > timedelta(seconds=5)
                    ):
                        break
                    prices.append(
                        snapshot.bids[0].price
                        if leg.opening_side is OrderSide.BUY
                        else snapshot.asks[0].price
                    )
                if len(prices) == 2:
                    self._bridge.publish_position_prices(
                        position.position_id, prices[0], prices[1]
                    )

    def _active_instruments(self) -> tuple[object, ...]:
        values = list(self._selected)
        for position in self._positions:
            if position.status is PositionStatus.CLOSED:
                continue
            values.extend((position.first_leg.instrument, position.second_leg.instrument))
        return tuple(dict.fromkeys(values))

    def _retain_active_books(self, instruments: tuple[object, ...]) -> None:
        self._books = {
            instrument: self._books.get(
                instrument, OrderBook(instrument, depth_limit=100)
            )
            for instrument in instruments
        }
        active = set(instruments)
        self._snapshot_buffers = {
            instrument: updates
            for instrument, updates in self._snapshot_buffers.items()
            if instrument in active
        }

    def _sync_subscriptions(
        self,
        previous: tuple[object, ...],
        current: tuple[object, ...],
    ) -> None:
        for instrument in set(previous) - set(current):
            self._public_websockets[_instrument_key(instrument)].unsubscribe(
                *_market_subscriptions(instrument)
            )
        for instrument in set(current) - set(previous):
            if instrument.exchange is Exchange.BITGET:
                with self._lock:
                    self._snapshots_pending.add(instrument)
            self._public_websockets[_instrument_key(instrument)].subscribe(
                *_market_subscriptions(instrument)
            )
            if instrument.exchange is Exchange.BINANCE:
                self._request_snapshot(instrument)

    def _buffer_update(self, update: OrderBookUpdate) -> None:
        buffered = self._snapshot_buffers.setdefault(update.instrument, {})
        buffered[update.sequence] = update
        while len(buffered) > _MAX_BUFFERED_BOOK_UPDATES:
            buffered.pop(min(buffered))

    def _apply_snapshot_and_replay(
        self, snapshot: OrderBookUpdate
    ) -> tuple[UpdateResult, bool]:
        book = self._book(snapshot.instrument)
        result = book.apply(snapshot)
        buffered = tuple(
            self._snapshot_buffers.pop(snapshot.instrument, {}).values()
        )
        ordered = tuple(sorted(buffered, key=lambda update: update.sequence))
        for index, update in enumerate(ordered):
            if update.sequence <= snapshot.sequence:
                continue
            replay = book.apply(update)
            if replay in {
                UpdateResult.GAP_DETECTED,
                UpdateResult.RESYNC_REQUIRED,
            }:
                self._snapshot_buffers[snapshot.instrument] = {
                    item.sequence: item for item in ordered[index:]
                }
                return result, True
        return result, False

    def _book(self, instrument) -> OrderBook:
        with self._lock:
            return self._books.setdefault(instrument, OrderBook(instrument, depth_limit=100))

    def _submit(self, function, *args) -> Future:
        with self._lock:
            if self._shutdown:
                raise RuntimeError("live data worker is shut down")
            future = self._pool.submit(function, *args)
        future.add_done_callback(self._report_future)
        return future

    def _report_future(self, future: Future) -> None:
        if future.cancelled() or self._shutdown:
            return
        try:
            future.result()
        except Exception as exc:
            self._safe_failure("LIVE refresh", exc)

    def _safe_failure(self, operation: str, error: Exception) -> None:
        self._logger.warning("%s failed error=%s", operation, type(error).__name__)
        if not self._shutdown:
            self._bridge.publish_status(f"{operation} 失败：{type(error).__name__}")


def _instrument_key(instrument) -> tuple[Exchange, MarketType]:
    return instrument.exchange, instrument.market_type


def _market_subscriptions(instrument) -> tuple[object, ...]:
    if instrument.exchange is Exchange.BINANCE:
        return binance_quotes.market_subscriptions(instrument)
    return bitget_quotes.market_subscriptions(instrument)


def _message_symbol(
    key: tuple[Exchange, MarketType], message: object
) -> str | None:
    if not isinstance(message, dict):
        return None
    if key[0] is Exchange.BINANCE:
        payload = message.get("data", message)
        symbol = payload.get("s") if isinstance(payload, dict) else None
    else:
        argument = message.get("arg")
        symbol = argument.get("symbol") if isinstance(argument, dict) else None
    return symbol if isinstance(symbol, str) and symbol else None
