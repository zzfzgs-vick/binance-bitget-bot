"""Fixed Bitget production REST and WebSocket endpoints."""

BITGET_BASE_URL = "https://api.bitget.com"
BITGET_SERVER_TIME_PATH = "/api/v2/public/time"
BITGET_INSTRUMENTS_PATH = "/api/v3/market/instruments"
BITGET_ACCOUNT_ASSETS_PATH = "/api/v3/account/assets"
BITGET_POSITIONS_PATH = "/api/v3/position/current-position"
BITGET_PLACE_ORDER_PATH = "/api/v3/trade/place-order"
BITGET_QUERY_ORDER_PATH = "/api/v3/trade/order-info"
BITGET_CANCEL_ORDER_PATH = "/api/v3/trade/cancel-order"
BITGET_FILLS_PATH = "/api/v3/trade/fills"

BITGET_PUBLIC_WS_URL = "wss://ws.bitget.com/v3/ws/public"
BITGET_PRIVATE_WS_URL = "wss://ws.bitget.com/v3/ws/private"
