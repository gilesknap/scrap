"""A model call's run row (#499): started, then finished with its outcome, in any of
the run tables (model_run for photo ingest, enrich_run, topic_run). Below ingest and
enrich, which both record runs, so neither imports the other for it."""

import hashlib
import json
import sqlite3
from typing import Any

from . import claude
from .store import now


def prompt_digest(system: str) -> dict[str, Any]:
    """What an enrich or topic run's stored request keeps of its system prompt
    (#571): its SHA-256 (hex, of the UTF-8) and length in characters, not the text.
    The template is its prompt_version and the pages rendered into it are in the
    request (candidates, sources or pages), so the text was ~35 KB a row of what
    those already say. A failed call whose answer was refused or invalid keeps the
    text as well (failed, below), to debug it."""
    digest = hashlib.sha256(system.encode()).hexdigest()
    return {"system_sha256": digest, "system_len": len(system)}


def start_run(conn: sqlite3.Connection, table: str, **fields: Any) -> int:
    """A new run row in table, its fields as given and started now; its id."""
    fields["started_at"] = now()
    names, marks = ", ".join(fields), ", ".join("?" * len(fields))
    return conn.execute(
        f"INSERT INTO {table} ({names}) VALUES ({marks}) RETURNING id",
        tuple(fields.values()),
    ).fetchone()[0]


def record(
    conn: sqlite3.Connection,
    table: str,
    run_id: int,
    done: claude.Completion | None,
    **fields: Any,
) -> None:
    """Finish a run row in table: its outcome, and the response, usage and cost."""
    if done is not None:
        fields.update(
            served_model=done.served_model,
            response=json.dumps(
                {"content": done.content, "stop_reason": done.stop_reason}
            ),
            usage=json.dumps(done.usage),
            cost_microusd=claude.cost_microusd(done.served_model, done.usage),
        )
    fields["finished_at"] = now()
    names = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE {table} SET {names} WHERE id = ?", (*fields.values(), run_id))


def status(error: claude.CallError) -> str:
    """A failed call's status: refused (the model refused, whatever the error's
    class), invalid (its output failed the check) or error."""
    refused = error.completion is not None and (
        error.completion.stop_reason == "refusal"
    )
    return "refused" if refused else ("invalid" if error.cls == "invalid" else "error")


def failed(
    conn: sqlite3.Connection,
    table: str,
    run_id: int,
    error: claude.CallError,
    system: str | None = None,
) -> None:
    """Finish a failed call's run: its status, class and message (and the response,
    if there was one). system: the prompt sent, for a request that keeps only its
    digest (prompt_digest), added to the request when the model refused or its
    answer was invalid, the failures the prompt may explain (#571)."""
    outcome = status(error)
    record(conn, table, run_id, error.completion, status=outcome,
           error_class=error.cls, error=str(error)[:500])  # fmt: skip
    if system is not None and outcome in ("refused", "invalid"):
        conn.execute(
            f"UPDATE {table} SET request = json_set(request, '$.system', ?)"
            " WHERE id = ?",
            (system, run_id),
        )
