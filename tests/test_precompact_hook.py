# ruff: noqa: E501
"""The PreCompact hook script in hooks/: pure parts, and that it never blocks compaction."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "hooks" / "scrap-precompact.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("scrap_precompact", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hook = _load()


def _entry(kind: str, content: object, **extra: object) -> str:
    return json.dumps({"type": kind, "message": {"content": content}, **extra})


def _transcript(path: Path, n: int = 3) -> Path:
    rows = []
    for i in range(n):
        rows.append(_entry("user", f"question {i} " + "x" * 120))
        rows.append(
            _entry("assistant", [{"type": "text", "text": f"answer {i} " + "y" * 120}])
        )
    rows.append(_entry("user", [{"type": "tool_result", "content": "SECRET OUTPUT"}]))
    rows.append(
        _entry("assistant", [{"type": "tool_use", "name": "Bash", "input": {}}])
    )
    path.write_text("\n".join(rows))
    return path


def test_dialogue_keeps_prose_drops_tool_output() -> None:
    lines = [
        _entry("user", "hello"),
        _entry(
            "assistant",
            [{"type": "text", "text": "hi"}, {"type": "tool_use", "name": "x"}],
        ),
        _entry("user", [{"type": "tool_result", "content": "RAW"}]),
        _entry("user", "meta", isMeta=True),
        "not json",
        _entry("system", "ignored"),
    ]
    assert hook.dialogue(lines) == "User: hello\n\nClaude: hi"
    assert hook.dialogue(lines, 1) == "Claude: hi"


def test_dialogue_skips_summaries_reminders_sidechains() -> None:
    lines = [
        _entry("user", "This session is being continued", isCompactSummary=True),
        _entry("user", "<system-reminder>x</system-reminder>"),
        _entry("assistant", "sub", isSidechain=True),
        _entry("user", "real"),
    ]
    assert hook.dialogue(lines) == "User: real"


def test_dialogue_cuts_long_turns_and_total() -> None:
    long = _entry("user", "z" * (hook.MAX_TURN_CHARS + 50))
    assert hook.dialogue([long]).endswith("[cut]")
    many = [_entry("user", "a" * 3000)] * 100
    assert "was cut" in hook.dialogue(many)


def test_build_prompt_new_and_append() -> None:
    new = hook.build_prompt("s1", "/w", "2026-10-26", None, "k1")
    assert "[auto-compact]" in new and "append_to" not in new and "k1" in new
    prev = {"slug": "my-page", "title": "[auto-compact] T", "count": 1}
    app = hook.build_prompt("s1", "/w", "2026-10-26", prev, "k2")
    assert "append_to `my-page`" in app and "Compaction 2" in app


def test_parse_slug_and_title() -> None:
    out = "done\nSLUG: my-page-2\nTITLE: [auto-compact] Hello\n"
    assert hook.parse_slug(out) == "my-page-2"
    assert hook.parse_title(out) == "[auto-compact] Hello"
    assert hook.parse_slug("no slug here") is None
    assert hook.parse_slug("**SLUG:** `my-page`") == "my-page"


def test_session_maps_to_one_page_and_appends(tmp_path: Path) -> None:
    transcript = _transcript(tmp_path / "t.jsonl")
    state = tmp_path / "state" / "p.json"
    calls: list[list[str]] = []

    def runner(cmd: list[str], stdin: str) -> str:
        calls.append(cmd)
        assert "SECRET OUTPUT" not in stdin
        assert "mcp__scrap__write" in cmd[cmd.index("--allowedTools") + 1]
        assert (
            cmd[cmd.index("--tools") + 1] == ""
        )  # no built-in tool, whatever the user allows
        denied = cmd[cmd.index("--disallowedTools") + 1].split(",")
        assert {"mcp__scrap__edit_page", "mcp__scrap__trash"} <= set(denied)
        assert not set(denied) & set(cmd[cmd.index("--allowedTools") + 1].split(","))
        return "SLUG: page-one\nTITLE: [auto-compact] One\n"

    payload = {"session_id": "sess", "transcript_path": str(transcript), "cwd": "/w"}
    assert hook.summarise(payload, state, runner)
    assert json.loads(state.read_text())["sess"]["slug"] == "page-one"
    assert "append_to" not in calls[0][2]

    # nothing new: no second call
    assert not hook.summarise(payload, state, runner)
    assert len(calls) == 1

    # more dialogue: appends to the same page, and only sends the new part
    with transcript.open("a") as f:
        f.write("\n" + _entry("user", "later " + "w" * 300))
    assert hook.summarise(payload, state, runner)
    assert "append_to `page-one`" in calls[1][2]
    saved = json.loads(state.read_text())["sess"]
    assert saved["slug"] == "page-one" and saved["count"] == 2


def test_missing_fields_skip(tmp_path: Path) -> None:
    assert not hook.summarise({}, tmp_path / "s.json", lambda c, s: "")


def test_no_slug_records_nothing(tmp_path: Path) -> None:
    payload = {"session_id": "s", "transcript_path": str(_transcript(tmp_path / "t"))}
    assert not hook.summarise(payload, tmp_path / "s.json", lambda c, s: "oops")
    assert not (tmp_path / "s.json").exists()


@pytest.mark.parametrize(
    "stdin", ["", "not json", "[]", json.dumps({"session_id": "s"})]
)
def test_main_never_fails(
    stdin: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert hook.main(stdin) == 0


def test_main_swallows_runner_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    payload = {"session_id": "s", "transcript_path": str(_transcript(tmp_path / "t"))}

    def boom(cmd: list[str], stdin: str) -> str:
        raise FileNotFoundError("claude")

    assert hook.main(json.dumps(payload), boom) == 0


def test_main_guard_skips_nested_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(hook.GUARD, "1")

    def boom(cmd: list[str], stdin: str) -> str:
        raise AssertionError("must not run")

    assert hook.main("{}", boom) == 0
