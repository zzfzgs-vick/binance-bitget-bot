"""Binance HMAC-SHA256 query signing."""

import hashlib
import hmac


def sign_query(query_string: str, secret: str) -> str:
    """Return the lowercase hexadecimal HMAC signature required by Binance."""
    return hmac.new(
        secret.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
