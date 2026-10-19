from __future__ import annotations

import re

_PATTERNS = [
    re.compile(r"(?i)\b(api[_-]?key|secret|token|password|passwd|authorization)\b\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bbearer\s+[a-z0-9._\-]{12,}"),
    re.compile(r"\bsk-[a-zA-Z0-9]{10,}\b"),
    re.compile(r"\bghp_[a-zA-Z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[a-zA-Z0-9_]{20,}\b"),
    re.compile(r"\bxai-[a-zA-Z0-9]{10,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
]


def redact(text: str) -> str:
    cleaned = text
    for pattern in _PATTERNS:
        cleaned = pattern.sub("[redacted]", cleaned)
    return cleaned.strip()
