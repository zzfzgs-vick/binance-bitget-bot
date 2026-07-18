"""Reconcile REST order snapshots with private-stream order and fill updates."""

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from enum import Enum

from app.domain.exceptions import OrderDataError
from app.domain.orders.fill import Fill, OrderFill
from app.domain.orders.order import Order, OrderRequest, OrderStatus, OrderType


class ReconcileResult(str, Enum):
    APPLIED = "applied"
    DUPLICATE = "duplicate"
    OUT_OF_ORDER = "out_of_order"
    SNAPSHOT_REQUIRED = "snapshot_required"


class OrderReconciler:
    def __init__(self) -> None:
        self._orders: dict[tuple[str, str], Order] = {}
        self._snapshot_time: dict[tuple[str, str], datetime] = {}
        self._snapshot_cumulative: dict[tuple[str, str], Decimal] = {}
        self._snapshot_has_cumulative_fee: dict[tuple[str, str], bool] = {}

    def apply(self, event: Order | OrderFill) -> ReconcileResult:
        if isinstance(event, Order):
            return self._apply_order(event)
        if isinstance(event, OrderFill):
            return self._apply_fill(event)
        raise TypeError("event must be Order or OrderFill")

    def get(self, request: OrderRequest) -> Order:
        try:
            return self._orders[_request_key(request)]
        except KeyError:
            raise OrderDataError("order snapshot is not available") from None

    def _apply_order(self, incoming: Order) -> ReconcileResult:
        key = _order_key(incoming)
        current = self._orders.get(key)
        if current is None:
            self._orders[key] = incoming
            self._record_snapshot_boundary(key, incoming)
            return ReconcileResult.APPLIED
        _same_order(current, incoming)
        if incoming == current:
            return ReconcileResult.DUPLICATE
        if (
            incoming.updated_time < current.updated_time
            or incoming.cumulative_filled_quantity
            < current.cumulative_filled_quantity
            or (
                current.status.is_terminal
                and incoming.status is not current.status
            )
        ):
            return ReconcileResult.OUT_OF_ORDER
        fills = _merge_fills(current.fills, incoming.fills)
        fee_asset = _fee_asset(current.fee_asset, incoming.fee_asset, fills)
        cumulative_fee = incoming.cumulative_fee
        carried_cumulative_fee = False
        if cumulative_fee == 0 and current.cumulative_fee != 0:
            cumulative_fee = current.cumulative_fee
            carried_cumulative_fee = (
                incoming.cumulative_filled_quantity
                == self._snapshot_cumulative[key]
                and self._snapshot_has_cumulative_fee[key]
            )
        if fills:
            tracked_fee = sum((fill.fee for fill in fills), Decimal(0))
            if abs(tracked_fee) > abs(cumulative_fee):
                cumulative_fee = tracked_fee
        original_quantity = incoming.original_quantity
        if incoming.order_type is OrderType.MARKET:
            original_quantity = current.original_quantity
        merged = replace(
            incoming,
            original_quantity=original_quantity,
            cumulative_fee=cumulative_fee,
            fee_asset=fee_asset,
            fills=fills,
        )
        self._orders[key] = merged
        self._record_snapshot_boundary(
            key,
            merged,
            has_cumulative_fee=(
                (incoming.cumulative_fee != 0 and not incoming.fills)
                or carried_cumulative_fee
            ),
        )
        return ReconcileResult.APPLIED

    def _apply_fill(self, event: OrderFill) -> ReconcileResult:
        key = _fill_key(event)
        current = self._orders.get(key)
        if current is None:
            return ReconcileResult.SNAPSHOT_REQUIRED
        if (
            current.instrument != event.instrument
            or current.exchange_order_id != event.exchange_order_id
        ):
            raise OrderDataError("fill identity does not match the order snapshot")
        if any(fill.fill_id == event.fill.fill_id for fill in current.fills):
            return ReconcileResult.DUPLICATE
        fills = (*current.fills, event.fill)
        snapshot_time = self._snapshot_time[key]
        if event.fill.executed_time > snapshot_time:
            added_quantity = event.fill.quantity
        else:
            covered = sum(
                (
                    fill.quantity
                    for fill in fills
                    if fill.executed_time <= snapshot_time
                ),
                Decimal(0),
            )
            if covered > self._snapshot_cumulative[key]:
                return ReconcileResult.SNAPSHOT_REQUIRED
            added_quantity = Decimal(0)
        cumulative = current.cumulative_filled_quantity + added_quantity
        if (
            current.order_type is OrderType.LIMIT
            and cumulative > current.original_quantity
        ):
            raise OrderDataError("fill quantity exceeds original order quantity")
        if added_quantity:
            notional = (
                current.average_price * current.cumulative_filled_quantity
                + event.fill.price * added_quantity
            )
            average = notional / cumulative
        else:
            average = current.average_price
        if (
            event.fill.executed_time <= snapshot_time
            and self._snapshot_has_cumulative_fee[key]
        ):
            cumulative_fee = current.cumulative_fee
        else:
            cumulative_fee = current.cumulative_fee + event.fill.fee
        status = current.status
        if not current.status.is_terminal:
            if (
                current.order_type is OrderType.LIMIT
                and cumulative == current.original_quantity
            ):
                status = OrderStatus.FILLED
            elif cumulative > 0:
                status = OrderStatus.PARTIALLY_FILLED
        fee_asset = _fee_asset(current.fee_asset, event.fill.fee_asset, fills)
        self._orders[key] = replace(
            current,
            status=status,
            cumulative_filled_quantity=cumulative,
            average_price=average,
            cumulative_fee=cumulative_fee,
            fee_asset=fee_asset,
            fills=fills,
            updated_time=max(current.updated_time, event.fill.executed_time),
        )
        return ReconcileResult.APPLIED

    def _record_snapshot_boundary(
        self,
        key: tuple[str, str],
        order: Order,
        *,
        has_cumulative_fee: bool | None = None,
    ) -> None:
        self._snapshot_time[key] = order.updated_time
        self._snapshot_cumulative[key] = order.cumulative_filled_quantity
        self._snapshot_has_cumulative_fee[key] = (
            order.cumulative_fee != 0 and not order.fills
            if has_cumulative_fee is None
            else has_cumulative_fee
        )


def _same_order(current: Order, incoming: Order) -> None:
    fields = [
        "instrument",
        "exchange_order_id",
        "side",
        "order_type",
    ]
    if current.order_type is OrderType.LIMIT:
        fields.append("original_quantity")
    if any(getattr(current, field) != getattr(incoming, field) for field in fields):
        raise OrderDataError("order update conflicts with the existing identity")


def _merge_fills(current: tuple[Fill, ...], incoming: tuple[Fill, ...]) -> tuple[Fill, ...]:
    by_id = {fill.fill_id: fill for fill in current}
    for fill in incoming:
        known = by_id.get(fill.fill_id)
        if known is not None and known != fill:
            raise OrderDataError("duplicate fill_id has conflicting data")
        by_id[fill.fill_id] = fill
    return tuple(sorted(by_id.values(), key=lambda fill: (fill.executed_time, fill.fill_id)))


def _fee_asset(
    current: str | None,
    incoming: str | None,
    fills: tuple[Fill, ...],
) -> str | None:
    assets = {asset for asset in (current, incoming) if asset is not None}
    assets.update(fill.fee_asset for fill in fills)
    if len(assets) > 1:
        raise OrderDataError("order updates use incompatible fee assets")
    return next(iter(assets), None)


def _request_key(request: OrderRequest) -> tuple[str, str]:
    return request.instrument.exchange.value, str(request.client_order_id)


def _order_key(order: Order) -> tuple[str, str]:
    return order.instrument.exchange.value, str(order.client_order_id)


def _fill_key(fill: OrderFill) -> tuple[str, str]:
    return fill.instrument.exchange.value, str(fill.client_order_id)
