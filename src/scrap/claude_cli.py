"""The Claude call through Claude Code on a seat: `claude -p`, no tools, one image.

SCRAP_LLM_BACKEND=cli sends claude.complete() here (ADR 0019). The CLI is an agent
harness, so every call locks it down: no tools, no MCP servers, no settings or
CLAUDE.md, a throwaway HOME and working directory, its own retries off, and only the
environment it needs. The image goes in as a content block on stdin (stream-json),
so no Read tool is needed; structured output comes back in the result message.
Failures map onto the queue's classes as the API's do (see claude.classify).
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
from typing import Any

from .claude import (
    EFFORT,
    MAX_TOKENS,
    TIMEOUT,
    CallError,
    Completion,
    api_messages,
    backend,
    redact,
)

__all__ = ["classify", "command", "complete", "unavailable"]

BINARY = "claude"  # found on PATH (the -claude image installs it)
TOKEN = "CLAUDE_CODE_OAUTH_TOKEN"  # from `claude setup-token`; never logged
# Passed through when set: the network and its certificates. Nothing else of the
# service's environment (ANTHROPIC_API_KEY, SCRAP_*) reaches the CLI.
PASS = (
    "PATH",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "NO_PROXY",
    "https_proxy",
    "http_proxy",
    "no_proxy",
    "SSL_CERT_FILE",
    "NODE_EXTRA_CA_CERTS",
)
LOCKED = {
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",  # no updater, telemetry, reports
    "DISABLE_AUTOUPDATER": "1",
    "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
    "CLAUDE_CODE_MAX_RETRIES": "0",  # the queue does all retrying
    "CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(MAX_TOKENS),
    "API_TIMEOUT_MS": str(int(TIMEOUT * 1000)),
    "DISABLE_PROMPT_CACHING": "1",  # each photo is seen once: a cache write is waste
}
DEADLINE = TIMEOUT + 60  # seconds for the whole process: the request plus start-up
# The CLI's error kinds (on the failed assistant message) by queue class
AUTH = {
    "authentication_failed",
    "oauth_org_not_allowed",
    "account_on_hold",
    "verification_required",
    "model_not_found",  # as the API's 404: the model needs fixing, not retrying
}
OUTAGE = {"rate_limit", "overloaded", "server_error"}
# The one tool --json-schema adds; anything else means the lock-down failed
STRUCTURED = "StructuredOutput"


def binary() -> str | None:
    return shutil.which(BINARY)


def unavailable() -> str | None:
    """Why ingest cannot run on the configured backend, or None if it can."""
    chosen = backend()
    if chosen == "api":
        return None
    if chosen != "cli":
        return f"SCRAP_LLM_BACKEND must be api or cli, not {chosen[:20]!r}"
    if not os.environ.get(TOKEN):
        return f"SCRAP_LLM_BACKEND=cli needs {TOKEN} (from claude setup-token)"
    if binary() is None:
        return "SCRAP_LLM_BACKEND=cli needs the claude CLI on PATH (the -claude image)"
    return None


def command(path: str, model: str, system: str, schema: dict) -> list[str]:
    """The argv for one locked-down call; the prompt and image go on stdin."""
    return [
        path,
        "--print",
        "--input-format=stream-json",
        "--output-format=stream-json",
        "--verbose",  # stream-json output requires it
        "--tools",  # none: the model sees data only
        "",
        "--strict-mcp-config",  # and no MCP servers
        "--mcp-config",
        '{"mcpServers": {}}',
        "--setting-sources",  # no user, project or local settings
        "",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--model",
        model,
        "--effort",
        EFFORT,
        "--system-prompt",  # replaces Claude Code's own
        system,
        "--json-schema",
        json.dumps(schema),
    ]


def environment(home: str) -> dict[str, str]:
    env = {name: os.environ[name] for name in PASS if name in os.environ}
    env.update(LOCKED, HOME=home, TMPDIR=home, CLAUDE_CONFIG_DIR=f"{home}/.claude")
    env[TOKEN] = os.environ.get(TOKEN, "")
    return env


def stdin(messages: list[dict]) -> str:
    """One stream-json line per user turn, images already base64 (api_messages)."""
    lines = [
        {"type": "user", "message": m, "parent_tool_use_id": None, "session_id": ""}
        for m in messages
    ]
    return "".join(json.dumps(line) + "\n" for line in lines)


def classify(
    kind: str | None, status: int | None, text: str, limit: dict | None = None
) -> CallError:
    """The queue's class of a failed CLI call: its error kind, HTTP status and
    message, and a rejected rate_limit_event (a seat's usage limit), if any."""
    text = redact(text)[:500]
    if limit is not None and limit.get("status") == "rejected":
        resets = limit.get("resetsAt")  # a seat limit is an outage until it resets
        wait = (
            max(0.0, resets - time.time()) if isinstance(resets, int | float) else None
        )
        return CallError("outage", text or "seat usage limit reached", wait)
    if kind in AUTH or status in (401, 403, 404):
        return CallError("auth", text)
    if kind == "billing_error" or status == 402:
        return CallError("credit", text)
    if kind in OUTAGE or status == 429 or (status or 0) >= 500:
        return CallError("outage", text)
    if kind == "max_output_tokens":
        return CallError("invalid", text)
    if kind == "invalid_request" or status in (400, 409, 413, 422):
        return CallError("content", text)
    if "timed out" in text.lower() or "timeout" in text.lower():
        return CallError("timeout", text)
    return CallError("outage", text)  # a connection error, or one not yet known


def parse(lines: list[str], model: str, missing: str = "") -> Completion:
    """The Completion from the CLI's stream-json output; CallError on failure
    (missing describes a run that gave no result)."""
    events = []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    init = next((e for e in events if e.get("subtype") == "init"), {})
    if set(init.get("tools") or []) - {STRUCTURED} or init.get("mcp_servers"):
        raise CallError("internal", "the CLI offered tools: lock-down failed")
    content, served, kind, limit = [], None, None, None
    for event in events:
        if event.get("type") == "assistant":
            message = event.get("message") or {}
            kind = event.get("error") or kind
            if message.get("model") not in (None, "<synthetic>"):
                served = message["model"]
                content.extend(message.get("content") or [])
        elif event.get("type") == "rate_limit_event":
            limit = event.get("rate_limit_info")
    result = next((e for e in reversed(events) if e.get("type") == "result"), None)
    if result is None:
        raise CallError("internal", missing or "the CLI gave no result")
    usage = dict(result.get("usage") or {})
    if isinstance(result.get("total_cost_usd"), int | float):
        usage["total_cost_usd"] = result["total_cost_usd"]  # notional: see ADR 0019
    done = Completion(
        output={},
        content=content,
        usage=usage,
        served_model=served or next(iter(result.get("modelUsage") or {}), model),
        stop_reason=result.get("stop_reason"),
    )
    text = str(result.get("result") or result.get("errors") or "")
    if result.get("is_error"):
        error = classify(kind, result.get("api_error_status"), text, limit)
        error.completion = done if served else None
        raise error
    if done.stop_reason == "refusal":
        raise CallError("content", "the model refused", completion=done)
    if result.get("subtype") != "success":  # e.g. error_max_structured_output_retries
        ended = f"the CLI ended with {result.get('subtype')}"
        raise CallError("invalid", ended, completion=done)
    output = result.get("structured_output")
    if not isinstance(output, dict):
        raise CallError("invalid", "output is not an object", completion=done)
    done.output = output
    return done


def complete(
    model: str, system: str, messages: list[dict], schema: dict, blob: Any
) -> Completion:
    """claude.complete() through `claude -p`: one call, never retried."""
    problem = unavailable()
    if problem:
        raise CallError("auth", problem)  # a setting to fix: pause until Resume
    path = binary() or BINARY
    with tempfile.TemporaryDirectory(
        prefix="scrap-claude-", ignore_cleanup_errors=True
    ) as home:
        try:
            run = subprocess.run(
                command(path, model, system, schema),
                input=stdin(api_messages(messages, blob)),
                capture_output=True,
                text=True,
                cwd=home,
                env=environment(home),
                timeout=DEADLINE,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise CallError("timeout", f"the CLI ran over {DEADLINE:.0f} s") from None
        except OSError as error:
            raise CallError("auth", redact(f"the CLI did not start: {error}")) from None
    tail = redact(run.stderr.strip())[-300:]
    return parse(
        run.stdout.splitlines(), model, f"the CLI exited {run.returncode}: {tail}"
    )
