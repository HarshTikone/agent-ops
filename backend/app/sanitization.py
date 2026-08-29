"""Small, deterministic redaction helpers for persisted/logged failures."""

from __future__ import annotations

import re

_CONNECTION_CREDENTIALS = re.compile(r"(?i)\b(postgres(?:ql)?://)[^\s/@]+(?::[^\s/@]*)?@")
_NAMED_SECRET = re.compile(
    r"(?i)\b(authorization|x-agent-ops-key|api[_-]?key|token|secret|password)"
    r"(\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+"
)


def sanitize_error(value: object, *, max_length: int = 1_000) -> str:
    """Redact common credential shapes and bound stored/logged error text."""
    text = str(value)
    text = _CONNECTION_CREDENTIALS.sub(r"\1[REDACTED]@", text)
    text = _NAMED_SECRET.sub(r"\1\2[REDACTED]", text)
    if len(text) > max_length:
        return f"{text[:max_length]}…"
    return text
