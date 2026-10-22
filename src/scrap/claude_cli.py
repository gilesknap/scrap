"""The Claude call through Claude Code on a seat: `claude -p`, no tools, one user turn.

SCRAP_LLM_BACKEND=cli sends claude.complete() here (ADR 0021). The CLI is an agent
harness, so every call locks it down: no tools, no MCP servers, no settings or
CLAUDE.md, a throwaway HOME and working directory, its own retries off, and only the
environment it needs. The user turn (a photo's image block, or an enrich call's text)
goes in on stdin (stream-json), so no Read tool is needed; structured output comes
back in the result message.
Failures map onto the queue's classes as the API's do (see claude.classify).
"""

import json
import os
import shutil
import signal
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

__all__ = ["classify", "command", "complete", "configured", "unavailable"]

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
    "API_TIMEOUT_MS": str(int(TIMEOUT * 1000)),
    "DISABLE_PROMPT_CACHING": "1",  # each input is seen once: a cache write is waste
}
# Seconds for the whole process: two requests (the CLI makes a second if the model
# does not call StructuredOutput) and start-up
DEADLINE = 2 * TIMEOUT + 60
# The CLI's error kinds (on the failed assistant message) by queue class
AUTH = {
    "authentication_failed",
    "oauth_org_not_allowed",
    "account_on_hold",
    "verification_required",
    "model_not_found",  # as the API's 404: the model needs fixing, not retrying
}
OUTAGE = {"rate_limit", "overloaded", "server_error"}  # server_error: no connection too
# The one tool --json-schema adds; anything else means the lock-down failed
STRUCTURED = "StructuredOutput"
USAGE = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


def binary() -> str | None:
    return shutil.which(BINARY)


def configured() -> bool:
    """Whether the configured backend has its credential (the API key, or the seat
    token for cli)."""
    return bool(os.environ.get(TOKEN if backend() == "cli" else "ANTHROPIC_API_KEY"))


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


def command(
    path: str, model: str, system: str, schema: dict, effort: str = EFFORT
) -> list[str]:
    """The argv for one locked-down call; the prompt and image go on stdin."""
    return [
        path,
        "--print",
        "--input-format=stream-json",
        "--output-format=stream-json",
        "--verbose",  # stream-json output requires it
        "--tools",  # none: the model sees data only
        "",
        "--permission-mode",  # and any tool use would be refused, not asked about
        "dontAsk",
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
        effort,
        "--system-prompt",  # in place of Claude Code's own (it still adds a preamble)
        system,
        "--json-schema",
        json.dumps(schema),
    ]


def environment(home: str, max_tokens: int = MAX_TOKENS) -> dict[str, str]:
    env = {name: os.environ[name] for name in PASS if name in os.environ}
    env.update(LOCKED, HOME=home, TMPDIR=home, CLAUDE_CONFIG_DIR=f"{home}/.claude")
    env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(max_tokens)
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
    message, and its rate_limit_event's info (a seat's usage limit), if any."""
    text = redact(text)[:500]
    if limit is not None and limit.get("status") == "rejected":
        resets = limit.get("resetsAt")  # a seat limit is an outage until it resets
        wait = (
            max(0.0, resets - time.time()) if isinstance(resets, int | float) else None
        )
        return CallError("outage", text or "seat usage limit reached", wait)
    if limit is not None and limit.get("isUsingOverage"):
        # Past the seat's limit on paid overage: calls may be billed for real, so
        # only a person restarts them (credit waits for Resume)
        return CallError("credit", "the seat is past its usage limit, on overage")
    if kind in AUTH or status in (401, 403, 404):
        return CallError("auth", text)
    if kind == "billing_error" or status == 402:
        return CallError("credit", text)
    # The CLI reports a request timeout as a server_error with no status: test it
    # first, or every timeout would be a free outage retry and a poison image would
    # never die (as in claude.classify)
    low = text.lower()
    if status is None and ("timed out" in low or "timeout" in low):
        return CallError("timeout", text)
    if kind in OUTAGE or status == 429 or (status or 0) >= 500:
        return CallError("outage", text)
    if kind == "max_output_tokens":
        return CallError("invalid", text)
    if kind == "invalid_request" or status in (400, 409, 413, 422):
        return CallError("content", text)
    return CallError("internal", text)  # one not yet known: charged, as the API's


def _events(lines: list[str]) -> list[dict]:
    events = []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _text(message: dict) -> str:
    blocks = message.get("content") or []
    return " ".join(
        str(b.get("text", "")) for b in blocks if isinstance(b, dict)
    ).strip()


def parse(lines: list[str], model: str, missing: str = "") -> Completion:
    """The Completion from the CLI's stream-json output; CallError on failure
    (missing describes a run that gave no result)."""
    events = _events(lines)
    init = next((e for e in events if e.get("subtype") == "init"), None)
    if init is not None:
        extra = sorted(set(init.get("tools") or []) - {STRUCTURED})
        if extra or init.get("mcp_servers"):
            offered = ", ".join(extra) or "MCP servers"
            raise CallError("auth", f"lock-down failed: the CLI offered {offered}")
    content, served, error, limit = [], None, None, None
    usage: dict[str, dict] = {}  # each served message's latest usage, by id
    for event in events:
        if event.get("type") == "assistant":
            message = event.get("message") or {}
            if error is None and (
                event.get("error") or event.get("is_api_error_message")
            ):  # a failed request, even one the CLI went on past
                error = (event.get("error") or "unknown", _text(message))
            if message.get("model") not in (None, "<synthetic>"):
                served = message["model"]
                content.extend(message.get("content") or [])
                usage[str(message.get("id"))] = message.get("usage") or {}
        elif event.get("type") == "rate_limit_event":
            limit = event.get("rate_limit_info")
    result = next((e for e in reversed(events) if e.get("type") == "result"), None)
    if result is None:  # a crash or a kill: keep what the requests so far used
        partial = {k: sum(u.get(k) or 0 for u in usage.values()) for k in USAGE}
        raise CallError(
            "internal",
            missing or "the CLI gave no result",
            completion=Completion({}, content, partial, served, None)
            if served
            else None,
        )
    if init is None:  # fail closed: nothing shows the lock-down held
        raise CallError("auth", "lock-down failed: the CLI sent no init message")
    done = Completion(
        output={},
        content=content,
        usage=dict(result.get("usage") or {}),
        served_model=served or next(iter(result.get("modelUsage") or {}), model),
        stop_reason=result.get("stop_reason"),
    )
    # The CLI's own cost (notional on a seat: ADR 0021), but only when it knows the
    # model's list price: for one it does not (2.1.281: Haiku and Sonnet 5.5) it
    # guesses, and scrap's PRICES apply instead
    priced = all(
        isinstance(u, dict) and u.get("costBasis") in (None, "list")
        for u in (result.get("modelUsage") or {}).values()
    )
    if priced and isinstance(result.get("total_cost_usd"), int | float):
        done.usage["total_cost_usd"] = result["total_cost_usd"]
    overage = limit is not None and bool(limit.get("isUsingOverage"))
    if result.get("is_error") or error or overage:
        kind, said = error or (None, "")
        text = said or str(result.get("result") or result.get("errors") or "")
        failure = classify(kind, result.get("api_error_status"), text, limit)
        failure.completion = done if served else None
        raise failure
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
    model: str,
    system: str,
    messages: list[dict],
    schema: dict,
    blob: Any,
    effort: str = EFFORT,
    max_tokens: int = MAX_TOKENS,
) -> Completion:
    """claude.complete() through `claude -p`, never retried by scrap: one claim is
    one CLI run, which is one request, or two if the CLI has to ask again for the
    structured output."""
    problem = unavailable()
    if problem:
        raise CallError("auth", problem)  # a setting to fix: pause until Resume
    path = binary() or BINARY
    with tempfile.TemporaryDirectory(
        prefix="scrap-claude-", ignore_cleanup_errors=True
    ) as home:
        try:
            proc = subprocess.Popen(
                command(path, model, system, schema, effort),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=home,
                env=environment(home, max_tokens),
                start_new_session=True,  # so a kill takes any children with it
            )
        except OSError as error:
            raise CallError("auth", redact(f"the CLI did not start: {error}")) from None
        with proc:
            try:
                out, err = proc.communicate(
                    stdin(api_messages(messages, blob)), timeout=DEADLINE
                )
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                out, _ = proc.communicate()  # what it wrote before the kill
                return _overran(out.splitlines(), model)
    tail = redact(err.strip())[-300:]
    return parse(out.splitlines(), model, f"the CLI exited {proc.returncode}: {tail}")


def _overran(lines: list[str], model: str) -> Completion:
    """A run killed at DEADLINE: its result if it had finished, else a timeout
    carrying the usage of the requests it made, so their cost is recorded."""
    try:
        return parse(lines, model)
    except CallError as error:
        if error.cls != "internal":
            raise
        over = f"the CLI ran over {DEADLINE:.0f} s"
        raise CallError("timeout", over, completion=error.completion) from None
