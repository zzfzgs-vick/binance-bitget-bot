# Order and arbitrage-position state machine

## Opening

Two normalized requests are preflighted before either order is sent. The first
leg must be fully filled before the second is submitted. Outcomes are explicit:
preflight failure, first/second failure, first/second incomplete, quantity
mismatch, or completed.

An uncertain opening submission remains attached to its original client order
id. The GUI recovery action queries that order and resumes the same execution;
it does not issue another create request.

Only `completed` may create an arbitrage position. The position uses each
order's reconciled cumulative fill, average price, fee, and update time; request
quantity is never used as a substitute for actual execution.

## Closing

Closing is manual and sequential:

```text
OPEN
  -> CLOSING
  -> PARTIALLY_CLOSED | CLOSE_UNKNOWN | CLOSE_FAILED | CLOSED
```

- Each close leg reverses its opening side and uses the current remaining base
  quantity.
- Central trading rules quantize both requests before the first submission.
- A partial first leg blocks the second leg until a reconciled order update says
  the first leg is filled.
- REST snapshots and private WebSocket order/fill events share the existing
  `OrderReconciler`; fill identifiers prevent duplicate accounting.
- A timeout or ambiguous submission remains query-only under its original
  client order id. It is never replaced by a blind retry.
- If both close orders finish but quantization leaves a remainder, the result is
  `remaining_quantity`, not `closed`.
- A later manual retry uses the current remaining quantity and fresh client
  order ids. If one leg is already closed, only the leg with remaining quantity
  is submitted.
- A failed or unknown leg is reported without automatic compensation, automatic
  close, stop loss, or other business-risk behavior.
