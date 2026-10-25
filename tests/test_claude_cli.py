"""The claude -p backend, with a fake `claude` executable on PATH."""

import io
import json
import logging
import os
import sys
from contextlib import closing
from pathlib import Path

import pytest
from PIL import Image

from scrap import claude, claude_cli, enrich, ingest, preview
from scrap.store import Store, connect, new_ulid

TOKEN = "sk-ant-oat01-not-a-real-token"
OUTPUT = {
    "kind": "handwriting",
    "title": "Shopping",
    "tags": ["list"],
    "description": "A list.",
    "text": "milk",
    "elements": [],
}
# The CLI writes what it saw beside itself (its environment holds none of ours) and
# replays the stream-json lines in scenario.json (those in "before" ahead of a sleep)
FAKE = """#!{python}
import json, os, sys, time
here = os.path.dirname(os.path.abspath(__file__))
seen = {{"argv": sys.argv[1:], "env": dict(os.environ), "cwd": os.getcwd(),
        "stdin": sys.stdin.read()}}
json.dump(seen, open(os.path.join(here, "seen.json"), "w"))
scenario = json.load(open(os.path.join(here, "scenario.json")))
for line in scenario.get("before", []):
    print(json.dumps(line), flush=True)
time.sleep(scenario.get("sleep", 0))
for line in scenario["lines"]:
    print(line if isinstance(line, str) else json.dumps(line))
sys.stderr.write(scenario.get("stderr", ""))
sys.exit(scenario.get("exit", 0))
"""
INIT = {
    "type": "system",
    "subtype": "init",
    "tools": ["StructuredOutput"],
    "mcp_servers": [],
}
SERVED = "claude-opus-5-5-20261001"


def assistant(content, model=SERVED, error=None):
    usage = {"input_tokens": 6900, "output_tokens": 1}  # as at message_start
    message = {"id": "msg_1", "model": model, "content": content, "usage": usage}
    event = {"type": "assistant", "message": message}
    if error:  # as the real CLI marks a failed request
        event.update(error=error, is_api_error_message=True)
    return event


def result(**fields):
    base = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "stop_reason": "tool_use",
        "result": "",
        "usage": {"input_tokens": 6900, "output_tokens": 400},
        "total_cost_usd": 0.0436,
        "modelUsage": {SERVED: {}},
    }
    return {**base, **fields}


TOOL_USE = [{"type": "tool_use", "name": "StructuredOutput", "input": OUTPUT}]
SUCCESS = [INIT, assistant(TOOL_USE), result(structured_output=OUTPUT)]


def failure(error, text, status=None, served=False):
    """A failed call as the CLI reports it: a synthetic message, an error result."""
    model = SERVED if served else "<synthetic>"
    return [
        INIT,
        assistant([{"type": "text", "text": text}], model, error),
        result(
            is_error=True,
            result=text,
            api_error_status=status,
            total_cost_usd=0,
            stop_reason="stop_sequence",
        ),
    ]


@pytest.fixture
def cli(tmp_path, monkeypatch):
    """A fake claude on PATH; returns a function setting its scenario and one
    reading what it saw."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "claude"
    fake.write_text(FAKE.format(python=sys.executable))
    fake.chmod(0o755)
    if not os.access(fake, os.X_OK):
        if os.environ.get("CI"):  # CI must run these, not skip them
            pytest.fail("the temporary directory is mounted noexec")
        pytest.skip("the temporary directory is mounted noexec: use --basetemp")
    monkeypatch.setenv("PATH", str(bin_dir))  # never the real claude
    monkeypatch.setenv("SCRAP_LLM_BACKEND", "cli")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", TOKEN)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-service-key")
    monkeypatch.setenv("SCRAP_SECRET_THING", "service only")

    class Cli:
        def __call__(self, lines, **more):
            (bin_dir / "scenario.json").write_text(json.dumps({"lines": lines, **more}))

        def seen(self):
            return json.loads((bin_dir / "seen.json").read_text())

    return Cli()


def call():
    system, _ = claude.prompt()
    messages = claude.photo_messages("sha", 40, 30)
    return claude.complete(
        "claude-opus-5-5",
        system,
        messages,
        claude.SCHEMA,
        lambda sha: (b"\xff\xd8jpeg", "image/jpeg"),
    )


def test_a_success_through_complete(cli):
    cli(SUCCESS)
    done = call()
    assert done.output == OUTPUT and done.content == TOOL_USE
    assert (done.served_model, done.stop_reason) == (SERVED, "tool_use")
    assert done.usage["input_tokens"] == 6900
    assert claude.cost_microusd(done.served_model, done.usage) == 43600  # the CLI's


def test_every_call_is_locked_down(cli):
    cli(SUCCESS)
    call()
    seen = cli.seen()
    argv = seen["argv"]

    def after(flag):
        return argv[argv.index(flag) + 1]

    assert "--print" in argv and "--strict-mcp-config" in argv
    assert after("--permission-mode") == "dontAsk"
    assert after("--tools") == "" and after("--setting-sources") == ""
    assert json.loads(after("--mcp-config")) == {"mcpServers": {}}
    assert after("--model") == "claude-opus-5-5" and after("--effort") == "medium"
    assert json.loads(after("--json-schema")) == claude.SCHEMA
    assert after("--system-prompt") == claude.prompt()[0]
    assert "--no-session-persistence" in argv
    env = seen["env"]
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == TOKEN
    assert "ANTHROPIC_API_KEY" not in env and "SCRAP_SECRET_THING" not in env
    assert "SCRAP_LLM_BACKEND" not in env
    assert env["HOME"] == seen["cwd"] and env["CLAUDE_CODE_MAX_RETRIES"] == "0"
    assert not Path(seen["cwd"]).exists()  # the throwaway home is gone
    assert TOKEN not in json.dumps(argv)
    # the image goes in as a content block: no Read tool, no file
    line = json.loads(seen["stdin"])
    image, size = line["message"]["content"]
    assert image["source"]["type"] == "base64" and image["source"]["data"]
    assert size["text"] == "The image is 40x30 pixels."


@pytest.mark.parametrize(
    "lines, cls, retry_after",
    [
        (
            failure("authentication_failed", "401 Invalid bearer token", 401),
            "auth",
            None,
        ),
        (failure("authentication_failed", "Not logged in"), "auth", None),
        (failure("oauth_org_not_allowed", "org disabled OAuth"), "auth", None),
        (failure("model_not_found", "no such model", 404), "auth", None),
        (failure("billing_error", "usage limit reached"), "credit", None),
        (failure("rate_limit", "rate limited", 429), "outage", None),
        (failure("overloaded", "overloaded", 529), "outage", None),
        (failure("server_error", "API error", 500), "outage", None),
        (  # as the real CLI reports no connection
            failure("server_error", "API Error: Connection refused (ECONNREFUSED)"),
            "outage",
            None,
        ),
        (failure("server_error", "Request timed out"), "timeout", None),  # real shape
        (failure("unknown", "something new"), "internal", None),
        (
            failure("invalid_request", "image could not be processed", 400),
            "content",
            None,
        ),
        (failure("max_output_tokens", "cut off", served=True), "invalid", None),
        (
            [
                INIT,
                {
                    "type": "rate_limit_event",
                    "rate_limit_info": {"status": "rejected", "resetsAt": 4102444800},
                },
                *failure("rate_limit", "You've hit your limit", 429)[1:],
            ],
            "outage",
            "reset",
        ),
        (
            [
                INIT,
                assistant(TOOL_USE),
                result(subtype="error_max_structured_output_retries"),
            ],
            "invalid",
            None,
        ),
        ([INIT, assistant(TOOL_USE), result(structured_output=["x"])], "invalid", None),
        ([INIT, assistant(TOOL_USE), result(stop_reason="refusal")], "content", None),
        ([INIT, "not json", assistant(TOOL_USE)], "internal", None),
        # the lock-down failed: pause until Resume, never charge the photo
        ([{**INIT, "tools": ["StructuredOutput", "Bash"]}, *SUCCESS[1:]], "auth", None),
        ([{**INIT, "mcp_servers": [{"name": "x"}]}, *SUCCESS[1:]], "auth", None),
        (SUCCESS[1:], "auth", None),  # no init message: fail closed
    ],
)
def test_error_classes(cli, lines, cls, retry_after):
    cli(lines)
    with pytest.raises(claude.CallError) as caught:
        call()
    assert caught.value.cls == cls
    if retry_after == "reset":  # waits for the seat's limit to reset
        assert (caught.value.retry_after or 0) > 3600
    else:
        assert caught.value.retry_after is None


def test_the_lock_down_failing_pauses_rather_than_charges(cli, tmp_path):
    store = Store(tmp_path / "data")
    store.migrate()
    photo(store)
    cli([{**INIT, "tools": ["StructuredOutput", "Bash"]}, *SUCCESS[1:]])
    ingest.Worker(store).step()
    status = ingest.status(store)
    assert status["paused"] and status["reason"] == "auth"
    assert status["jobs"] == {"queued": 1}


# The API rejected the image; the CLI dropped it, asked again without it and
# reported a success (as Claude Code 2.1.281 does)
IMAGE_DROPPED = [
    INIT,
    assistant(
        [
            {
                "type": "text",
                "text": "API Error: an image in the conversation could not be"
                " processed and was removed.",
            }
        ],
        "<synthetic>",
        "invalid_request",
    ),
    assistant(TOOL_USE),
    {"type": "rate_limit_event", "rate_limit_info": {"status": "allowed"}},
    result(structured_output=OUTPUT, api_error_status=None),
]


def test_a_success_without_the_image_is_not_stored(cli):
    cli(IMAGE_DROPPED)
    with pytest.raises(claude.CallError) as caught:
        call()
    assert caught.value.cls == "content" and "could not be processed" in str(
        caught.value
    )
    assert caught.value.completion is not None  # the second request is costed
    assert caught.value.completion.usage["total_cost_usd"] == 0.0436


OVERAGE = [
    INIT,
    assistant(TOOL_USE),
    {
        "type": "rate_limit_event",
        "rate_limit_info": {"status": "allowed", "isUsingOverage": True},
    },
    result(structured_output=OUTPUT),
]


def test_overage_pauses_until_resume(cli, tmp_path):
    cli(OVERAGE)
    with pytest.raises(claude.CallError) as caught:
        call()
    assert caught.value.cls == "credit" and caught.value.completion is not None
    store = Store(tmp_path / "data")
    store.migrate()
    photo(store)
    ingest.Worker(store).step()
    status = ingest.status(store)
    assert status["paused"] and status["reason"] == "credit"  # until Resume
    assert status["jobs"] == {"queued": 1}  # refunded, not charged
    with closing(connect(store.db)) as conn:
        run = conn.execute("SELECT * FROM model_run").fetchone()
    assert (run["error_class"], run["cost_microusd"]) == ("credit", 43600)


def test_the_cli_backend_sends_at_most_2000_pixels(monkeypatch):
    # Claude Code rescales a longer edge and adds its own note on coordinates
    monkeypatch.setenv("SCRAP_LLM_BACKEND", "cli")
    assert preview.claude_size(4032, 3024) == (2000, 1500)
    assert preview.claude_size(800, 600) == (800, 600)
    monkeypatch.setenv("SCRAP_LLM_BACKEND", "api")
    assert preview.claude_size(4032, 3024) == (2048, 1536)


def test_a_crash_and_a_hung_cli(cli, monkeypatch):
    cli([], stderr="Segmentation fault", exit=139)
    with pytest.raises(claude.CallError) as caught:
        call()
    assert caught.value.cls == "internal" and "exited 139" in str(caught.value)
    assert caught.value.completion is None
    monkeypatch.setattr(claude_cli, "DEADLINE", 0.5)
    cli([], before=[INIT, assistant(TOOL_USE)], sleep=30)
    with pytest.raises(claude.CallError) as caught:
        call()
    assert caught.value.cls == "timeout"
    done = caught.value.completion  # the request it made is still costed
    assert done is not None and done.served_model == SERVED
    assert done.usage["input_tokens"] == 6900
    cli(SUCCESS, sleep=30)
    with pytest.raises(claude.CallError) as caught:
        call()
    assert caught.value.cls == "timeout" and caught.value.completion is None


@pytest.mark.parametrize("token", [TOKEN, "opaque-token-without-a-known-prefix"])
def test_the_token_never_appears_in_errors(cli, monkeypatch, token):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", token)
    cli(failure("unknown", f"proxy echoed Bearer {token}"), stderr=token)
    with pytest.raises(claude.CallError) as caught:
        call()
    assert token not in str(caught.value) and "[key]" in str(caught.value)
    cli([], stderr=f"bad token {token}", exit=1)
    with pytest.raises(claude.CallError) as caught:
        call()
    assert token not in str(caught.value) and "[key]" in str(caught.value)


@pytest.mark.parametrize(
    "unset, backend, problem",
    [
        ("CLAUDE_CODE_OAUTH_TOKEN", "cli", "needs CLAUDE_CODE_OAUTH_TOKEN"),
        ("PATH", "cli", "needs the claude CLI"),
        (None, "cly", "must be api or cli"),
    ],
)
def test_a_missing_token_or_binary_pauses_until_resume(
    cli, monkeypatch, unset, backend, problem
):
    monkeypatch.setenv("SCRAP_LLM_BACKEND", backend)
    if unset == "PATH":
        monkeypatch.setattr(claude_cli, "BINARY", "no-such-claude")
    elif unset:
        monkeypatch.delenv(unset)
    assert problem in (claude_cli.unavailable() or "")
    with pytest.raises(claude.CallError) as caught:
        call()
    assert caught.value.cls == "auth" and problem in str(caught.value)


def test_the_api_backend_needs_neither(monkeypatch):
    monkeypatch.delenv("SCRAP_LLM_BACKEND", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    assert claude.backend() == "api" and claude_cli.unavailable() is None


def jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (400, 300), "red").save(out, "JPEG")
    return out.getvalue()


def photo(store):
    sha, size = store.put_blob(io.BytesIO(jpeg()))
    c = store.prepare({"id": new_ulid(), "text": None}, ["image/jpeg"])
    return store.capture(c, [(sha, "image/jpeg", size, None)], "me")[0]


def test_the_worker_records_a_cli_run(cli, tmp_path):
    store = Store(tmp_path / "data")
    store.migrate()
    ref = photo(store)
    cli(SUCCESS)
    assert ingest.Worker(store).step() is True
    with closing(connect(store.db)) as conn:
        run = conn.execute("SELECT * FROM model_run").fetchone()
    assert (run["status"], run["served_model"]) == ("ok", SERVED)
    assert json.loads(run["request"])["backend"] == "cli"
    assert run["cost_microusd"] == 43600
    assert store.page(ref["page_id"])["title"] == "Shopping"


def test_the_worker_does_not_start_without_its_token(
    cli, tmp_path, caplog, monkeypatch
):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN")
    store = Store(tmp_path / "data")
    store.migrate()
    photo(store)
    worker = ingest.Worker(store)
    with caplog.at_level(logging.ERROR):
        worker.start()
    worker.stop()
    worker._thread.join(10)
    assert not worker.alive()
    status = ingest.status(store)
    assert status["paused"] and status["reason"] == "auth"
    assert "needs CLAUDE_CODE_OAUTH_TOKEN" in caplog.text
    assert status["jobs"] == {"queued": 1}  # nothing was claimed


@pytest.mark.parametrize("token", [TOKEN, "opaque-token-without-a-known-prefix"])
def test_a_failed_run_stores_no_token(cli, tmp_path, caplog, monkeypatch, token):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", token)
    store = Store(tmp_path / "data")
    store.migrate()
    photo(store)
    cli(failure("authentication_failed", f"401 for {token}", 401))
    with caplog.at_level(logging.DEBUG):
        ingest.Worker(store).step()
    with closing(connect(store.db)) as conn:
        rows = [tuple(r) for r in conn.execute("SELECT * FROM model_run")]
        rows += [tuple(r) for r in conn.execute("SELECT * FROM job")]
    assert token not in json.dumps(rows, default=str) and token not in caplog.text
    assert ingest.status(store)["reason"] == "auth"


# Text enrichment (enrich/) on a seat: tags, summary, Ask Claude and related pages
# are the same shape of call (one user turn, a schema, no tools) with text only
TAGGED = {"tags": ["garden"], "summary": "A larch shed, planned.", "title": ""}
TEXT_MODEL_SERVED = "claude-haiku-5-5"


def text_run(out, basis="unknown"):
    """A text call's events; the CLI does not know Haiku 5.5's price (2.1.281)."""
    use = [{"type": "tool_use", "name": "StructuredOutput", "input": out}]
    usage = {basis and TEXT_MODEL_SERVED: {"costBasis": basis, "costUSD": 0.0178}}
    return [
        INIT,
        assistant(use, TEXT_MODEL_SERVED),
        result(
            structured_output=out,
            usage={"input_tokens": 1000, "output_tokens": 100},
            total_cost_usd=0.0178,
            modelUsage=usage,
        ),
    ]


def test_a_text_call_passes_its_effort_and_max_tokens(cli):
    cli(text_run(TAGGED))
    system, _ = claude.prompt("enrich", enrich.SCHEMA)
    messages = [{"role": "user", "content": [{"type": "text", "text": "a note"}]}]
    model, effort = claude.text_model()
    done = claude.complete(
        model, system, messages, enrich.SCHEMA, None,
        effort=effort, max_tokens=claude.TEXT_MAX_TOKENS,
    )  # fmt: skip
    assert done.output == TAGGED and done.served_model == TEXT_MODEL_SERVED
    seen = cli.seen()
    argv = seen["argv"]
    assert argv[argv.index("--model") + 1] == claude.TEXT_MODEL
    assert argv[argv.index("--effort") + 1] == "low"
    assert seen["env"]["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == str(claude.TEXT_MAX_TOKENS)
    assert json.loads(seen["stdin"])["message"]["content"] == messages[0]["content"]
    # the CLI's guess at an unknown price is not used: scrap's PRICES are
    assert "total_cost_usd" not in done.usage
    assert claude.cost_microusd(done.served_model, done.usage) == 150


def test_a_known_price_is_the_clis_own(cli):
    cli(text_run(TAGGED, basis="list"))
    messages = [{"role": "user", "content": [{"type": "text", "text": "a note"}]}]
    done = claude.complete(TEXT_MODEL_SERVED, "s", messages, enrich.SCHEMA, None)
    assert done.usage["total_cost_usd"] == 0.0178


def test_enrichment_runs_on_the_worker(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("SCRAP_INGEST", "on")
    monkeypatch.setenv("SCRAP_ENRICH_DEBOUNCE", "0")
    store = Store(tmp_path / "data")
    store.migrate()
    c = store.prepare({"id": new_ulid(), "text": "Plans for the shed " * 20}, [])
    ref = store.capture(c, [], "me")[0]
    cli(text_run(TAGGED))
    worker = ingest.Worker(store)
    assert worker.step() is True  # no photo: the text page
    page = store.page(ref["page_id"])
    assert page["tags"] == ["garden"] and page["enrich"]["state"] == "queued"  # related
    with closing(connect(store.db)) as conn:
        run = conn.execute("SELECT * FROM enrich_run").fetchone()
    assert run["status"] == "ok" and run["cost_microusd"] == 150
    assert json.loads(run["request"])["backend"] == "cli"
    # the related pass (nightly, and on Ask) on the same backend
    cli(text_run({"related": []}))
    counts = enrich.related_pass(store)
    assert (counts["done"], counts["stopped"]) == (1, None)
    # a failed lock-down stops it and pauses the queue, as on the worker
    enrich.ask(store, ref["page_id"])
    unlocked = {**INIT, "tools": ["StructuredOutput", "Bash"]}
    cli([unlocked, *text_run({"related": []})[1:]])
    counts = enrich.related_pass(store, every=True)
    assert counts["stopped"] == "auth" and ingest.status(store)["reason"] == "auth"


def test_the_related_pass_command_runs_with_a_seat_token(
    cli, tmp_path, capsys, monkeypatch
):
    from scrap.__main__ import main

    monkeypatch.setenv("SCRAP_INGEST", "on")
    monkeypatch.delenv("ANTHROPIC_API_KEY")  # the seat token is the credential
    main(["enrich", "--related", "--dry-run", "--data-dir", str(tmp_path)])
    assert "would pick related pages" in capsys.readouterr().out
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN")
    main(["enrich", "--related", "--data-dir", str(tmp_path)])
    assert "enrichment is off" in capsys.readouterr().out
