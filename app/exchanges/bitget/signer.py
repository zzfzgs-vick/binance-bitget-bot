"""Bitget REST prehash construction and HMAC signing."""

import base64
import hashlib
import hmac


def build_prehash(
    timestamp: str,
    method: str,
    request_path: str,
    query_string: str = "",
    body: str = "",
) -> str:
    query = f"?{query_string}" if query_string else ""
    return f"{timestamp}{method.upper()}{request_path}{query}{body}"


def sign_prehash(prehash: str, secret: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        prehash.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("ascii")


def sign_websocket_login(timestamp: str, secret: str) -> str:
    """Sign the Bitget WebSocket verification prehash."""
    return sign_prehash(f"{timestamp}GET/user/verify", secret)
