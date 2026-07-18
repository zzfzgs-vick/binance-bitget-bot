"""Credential-safe text redaction."""

from __future__ import annotations


REDACTION = "[REDACTED]"


def redact_secrets(text: str, secrets: tuple[str, ...]) -> str:
    """Replace every non-empty secret value without exposing it elsewhere."""
    for secret in sorted(filter(None, secrets), key=len, reverse=True):
        text = text.replace(secret, REDACTION)
    return text
