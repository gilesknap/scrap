"""The Claude call: one Messages API request, no tools, structured output.

complete() is the seam the worker calls (and tests replace). It never retries: the
queue does all retrying, so one claim is one call. Errors come back as CallError with
the class that decides what the queue does (see docs/explanations/ingest.md).
"""

import base64
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from importlib.resources import files as package_files
from typing import Any

import anthropic
import httpx2

from .spend import Ticket

__all__ = [
    "MODEL",
    "SCHEMA",
    "CallError",
    "Completion",
    "classify",
    "complete",
    "prompt",
]

MODEL = "claude-opus-5-5"
EFFORT = "medium"  # thinking cannot be disabled on Opus 5.5: set its depth explicitly
MAX_TOKENS = 16000
TIMEOUT = 240.0  # seconds, one request
KINDS = ["whiteboard", "handwriting", "diagram", "screenshot", "document", "photo"]
ELEMENT_TYPES = ["rectangle", "ellipse", "diamond", "text", "arrow", "line"]
KEYLIKE = re.compile(r"sk-ant-[\w-]+")

# Kept to the structured-output subset: no unions, no numeric or string bounds (the
# sanitiser enforces those), every element one flat object.
_NUMBER, _STRING = {"type": "number"}, {"type": "string"}
SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind", "title", "tags", "description", "text", "elements"],
    "properties": {
        "kind": {"type": "string", "enum": [*KINDS, "other"]},
        "title": _STRING,
        "tags": {"type": "array", "items": _STRING},
        "description": _STRING,
        "text": _STRING,
        "elements": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["type", "id", "x", "y"],
                "properties": {
                    "type": {"type": "string", "enum": ELEMENT_TYPES},
                    "x": _NUMBER,
                    "y": _NUMBER,
                    "id": _STRING,
                    "width": _NUMBER,
                    "height": _NUMBER,
                    "text": _STRING,
                    "fontSize": _NUMBER,
                    "label": _STRING,
                    "labelFontSize": _NUMBER,
                    "points": {"type": "array", "items": _NUMBER},
                    "start": _STRING,
                    "end": _STRING,
                    "strokeColor": _STRING,
                    "startArrowhead": {"type": "string", "enum": ["arrow"]},
                },
            },
        },
    },
}

logging.getLogger("anthropic").setLevel(logging.WARNING)  # debug logs request bodies
logging.getLogger("httpx").setLevel(logging.WARNING)


def prompt(name: str = "photo") -> tuple[str, str]:
    """A system prompt from src/scrap/prompts and its version: name@12 hex digits of
    the SHA-256 of the prompt and the schema."""
    text = (package_files("scrap") / "prompts" / f"{name}.md").read_text()
    digest = hashlib.sha256((text + json.dumps(SCHEMA, sort_keys=True)).encode())
    return text, f"{name}@{digest.hexdigest()[:12]}"


@dataclass
class Completion:
    output: dict[str, Any]  # the JSON the model returned, not yet sanitised
    content: list[dict[str, Any]]  # the content blocks exactly as returned
    usage: dict[str, Any]
    served_model: str
    stop_reason: str | None


class CallError(Exception):
    """A failed call, with its class (credit, auth, outage, timeout, invalid, content
    or internal), for an outage the seconds the API asked us to wait, and whether
    it may have been billed with no answer (a connection lost after the request was
    sent)."""

    def __init__(
        self,
        cls: str,
        message: str,
        retry_after: float | None = None,
        completion: Completion | None = None,
        maybe_billed: bool = False,
    ):
        super().__init__(message)
        self.cls, self.retry_after, self.completion = cls, retry_after, completion
        self.maybe_billed = maybe_billed


# Connection failures that prove the request never reached the API: free to retry.
UNSENT = (httpx2.ConnectError, httpx2.ConnectTimeout, httpx2.PoolTimeout,
          httpx2.ProxyError)  # fmt: skip


def _unsent(error: BaseException) -> bool:
    """Whether a connection error happened before the request was sent."""
    seen: set[int] = set()
    cause: BaseException | None = error
    while cause is not None and id(cause) not in seen:
        if isinstance(cause, UNSENT):
            return True
        seen.add(id(cause))
        cause = cause.__cause__ or cause.__context__
    return False


def _retry_after(error: anthropic.APIStatusError) -> float | None:
    try:
        return max(0.0, float(error.response.headers.get("retry-after", "")))
    except ValueError:
        return None


def redact(text: str) -> str:
    """Error text with anything like an API key (or the key itself) removed: an
    error a proxy echoes back could hold the request headers."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        text = text.replace(key, "[key]")
    return KEYLIKE.sub("[key]", text)


def classify(error: BaseException) -> CallError:
    """The queue's class of an exception raised by the SDK; its text redacted."""
    message = redact(str(error))[:500]
    # APITimeoutError subclasses APIConnectionError: test it first, or every timeout
    # would be a free outage retry and a poison image would never die.
    if isinstance(error, anthropic.APITimeoutError):
        return CallError("timeout", message)
    if isinstance(error, anthropic.APIConnectionError):
        # lost after sending (a dropped or reset connection): it may have been
        # billed, so the ledger counts its worst case, but the queue backs off
        return CallError("outage", message, maybe_billed=not _unsent(error))
    if not isinstance(error, anthropic.APIStatusError):
        return CallError("internal", message)
    status = error.status_code
    body = error.body if isinstance(error.body, dict) else {}
    detail = body["error"] if isinstance(body.get("error"), dict) else body
    text = redact(str(detail.get("message", message)))[:500]
    code = (detail.get("details") or {}).get("error_code")
    spend_limit = "reached your specified" in text and "API usage limits" in text
    if (
        status == 402
        or (status == 400 and (spend_limit or "credit balance" in text))
        or (status == 429 and code == "enforced_spend_limit_reached")
    ):
        return CallError("credit", text)
    if status in (401, 403, 404):
        return CallError("auth", text)
    if status == 429 or status >= 500:
        return CallError("outage", text, _retry_after(error))
    return CallError("content", text)  # any other 400, 409, 413, 422


_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    """One SDK client, with no retries and the request timeout; it reads
    ANTHROPIC_API_KEY from the environment."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic(max_retries=0, timeout=TIMEOUT)
    return _client


def photo_messages(sha: str, width: int, height: int) -> list[dict[str, Any]]:
    """The user turn for a photo: the sent JPEG (a blob reference) and its size. The
    API must refuse it rather than scale it, so drawings stay in sent pixels."""
    image = {
        "type": "image",
        "source": {"type": "blob", "sha256": sha},
        "transformations": {"oversized_image": "error"},
    }
    size = {"type": "text", "text": f"The image is {width}x{height} pixels."}
    return [{"role": "user", "content": [image, size]}]


def api_messages(messages: list[dict], blob: Any) -> list[dict]:
    """Stored messages as sent: image blocks name a blob by sha256 (blob(sha) gives
    its bytes and MIME type) and become base64 here, never in the database."""
    sent = []
    for message in messages:
        content = []
        for block in message["content"]:
            if block.get("type") == "image" and block["source"].get("type") == "blob":
                data, mime = blob(block["source"]["sha256"])
                source = {
                    "type": "base64",
                    "media_type": mime,
                    "data": base64.standard_b64encode(data).decode(),
                }
                block = {**block, "source": source}
            content.append(block)
        sent.append({**message, "content": content})
    return sent


def complete(
    model: str,
    system: str,
    messages: list[dict],
    schema: dict,
    blob: Any,
    *,
    ticket: Ticket,
) -> Completion:
    """Call Claude once and return its JSON output; raise CallError on any failure.
    ticket, from spend.admit(), is the leave to spend: no call without one."""
    if not isinstance(ticket, Ticket):
        raise TypeError("complete() needs a spend.Ticket")
    try:
        response = client().messages.create(
            model=model,
            max_tokens=ticket.max_tokens,
            system=system,
            messages=api_messages(messages, blob),  # type: ignore[arg-type]
            output_config={
                "effort": EFFORT,
                "format": {"type": "json_schema", "schema": schema},
            },
        )
    except Exception as error:  # every SDK error, classified
        raise classify(error) from None
    blocks = [block.model_dump(mode="json") for block in response.content]
    done = Completion(
        output={},
        content=blocks,
        usage=response.usage.model_dump(mode="json"),
        served_model=response.model,
        stop_reason=response.stop_reason,
    )
    if response.stop_reason == "refusal":
        raise CallError("content", "the model refused", completion=done)
    if response.stop_reason == "max_tokens":
        raise CallError("invalid", "output cut off at max_tokens", completion=done)
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    try:
        done.output = json.loads(text)
    except ValueError:
        raise CallError("invalid", "output is not JSON", completion=done) from None
    if not isinstance(done.output, dict):
        raise CallError("invalid", "output is not an object", completion=done)
    return done


def model_name() -> str:
    return os.environ.get("SCRAP_VISION_MODEL") or MODEL
