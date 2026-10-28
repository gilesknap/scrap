"""Mask secrets in the text that leaves for Claude (ADR 0038, #418).

Applied once, in claude.complete(), to the text of `system` and `messages`. What is
stored is never changed and photo pixels are not touched. The rules are provider
shapes only: no hex or base64 run rules, which mangle git SHAs, digests and slugs.
A plain-text password still leaks; SCRAP_FILE_ENRICH=ask is the control for that.
"""

import re
from typing import Any

MASK = "[REDACTED]"

RULES = tuple(
    re.compile(rule, re.DOTALL)
    for rule in (
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        r"\bsk-(?:ant-)?[A-Za-z0-9_-]{16,}",
        r"\bgh[opsu]_[A-Za-z0-9]{16,}",
        r"\bxox[baprs]-[A-Za-z0-9-]{10,}",
        r"\bxapp-[A-Za-z0-9-]{10,}",
        r"\bAKIA[0-9A-Z]{16}\b",
        r"\bBearer\s+[A-Za-z0-9._~+/=-]{10,}",
        r"(?i)\b(?:api[_-]?key|secret|token|password|passwd|access[_-]?key)\b"
        r"\s*[:=]\s*\S{6,}",
    )
)


def redact_secrets(text: str) -> str:
    """text with every secret-shaped part replaced by [REDACTED]."""
    for rule in RULES:
        text = rule.sub(MASK, text)
    return text


def mask_messages(messages: list[dict]) -> list[dict]:
    """A copy of messages with each text block masked; other blocks (image blobs)
    and the stored list are untouched."""
    masked = []
    for message in messages:
        content = message["content"]
        if isinstance(content, str):
            content = redact_secrets(content)
        else:
            content = [_block(block) for block in content]
        masked.append({**message, "content": content})
    return masked


def _block(block: Any) -> Any:
    if isinstance(block, dict) and isinstance(block.get("text"), str):
        return {**block, "text": redact_secrets(block["text"])}
    return block
