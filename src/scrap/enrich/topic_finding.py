"""Enrich: topic discovery (#261), one call over the whole library, and the weekly
pass (scrap enrich --topics) that runs it and queues the syntheses due.

One Opus call sees a compact index of every page (number, title, tags, summary; at
most TOPIC_INDEX, the most recently changed), the topics with their sources' numbers,
and the keys of those in the trash (the owner's veto). It returns new topics and new
sources for existing ones, citing pages by number only, so it cannot name a page that
does not exist. New topics are made at once, with no approval step: a page (kind
reference, an empty body for the owner's notes) and its sources. Its run is a
topic_run (it is of no one page), counted in the daily budget.
"""

import json
import os
import sqlite3
from typing import Any

from .. import claude
from ..ingest import resume
from ..store import Store, now, queue_topic, topics, transaction, writeups
from .checking import checked_topics, record
from .constants import DISCOVERY_SCHEMA, TOPIC_DUE, TOPIC_INDEX
from .relating import run_pass
from .synthesis import failed
from .topic_prompts import discovery_message, discovery_prompt, topic_prompt
from .types import Call


def page_index(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """The pages discovery sees, oldest first: every page not in the trash and not a
    topic (at most TOPIC_INDEX, the most recently changed), each with its id, title,
    tags and summary (the owner's, else its write-up's, else enrich's)."""
    rows = conn.execute(
        "SELECT * FROM (SELECT p.id, p.title, p.fields, p.created_at,"
        " coalesce(nullif(w.summary, ''), e.summary, '') AS summary,"
        " (SELECT group_concat(tag, '\x1f') FROM tag WHERE page_id = p.id) AS tags"
        " FROM page p LEFT JOIN enrichment e ON e.page_id = p.id"
        " LEFT JOIN writeup w ON w.page_id = p.id AND w.superseded_at IS NULL"
        f" AND {writeups.HAS_BOARD.format(p='p')}"
        f" WHERE p.deleted_at IS NULL AND NOT {topics.IS_TOPIC.format(p='p')}"
        " ORDER BY p.updated_at DESC, p.id LIMIT ?) ORDER BY created_at, id",
        (TOPIC_INDEX,),
    ).fetchall()
    out = []
    for r in rows:
        human = json.loads(r["fields"]).get("summary")
        out.append({
            "id": r["id"],
            "title": r["title"],
            "tags": r["tags"].split("\x1f") if r["tags"] else [],
            "summary": human if isinstance(human, str) else r["summary"],
        })  # fmt: skip
    return out


def discover(
    store: Store, call: Call, dry_run: bool = False
) -> tuple[claude.CallError | None, dict[str, Any]]:
    """One discovery call; unless dry_run, its new topics are made (each queued for
    its synthesis by the pass) and its new sources added. The run is recorded either
    way (a dry run's call is paid for too). Returns a failure, for the caller to act
    on, and what was found: new (title, key, sources: page ids and titles) and add
    (topic, its title, sources), sources already in left out."""
    with store.connect() as conn:
        pages = page_index(conn)
        existing = topics.every(conn)
    found: dict[str, Any] = {"new": [], "add": []}
    if not pages:
        return None, found
    alive = [t for t in existing if not t["trashed"]]
    rejected = [t["key"] for t in existing if t["trashed"]]
    number = {p["id"]: n for n, p in enumerate(pages, start=1)}
    system, version = discovery_prompt()
    messages = discovery_message(pages, alive, number, rejected)
    model = claude.model_name()
    request = {
        "purpose": "topics", "model": model, "max_tokens": claude.MAX_TOKENS,
        "effort": claude.EFFORT, "system": system, "messages": messages,
        "schema": DISCOVERY_SCHEMA, "pages": [p["id"] for p in pages],
        "topics": [t["id"] for t in alive], "dry_run": dry_run,
        "backend": claude.backend(),
    }  # fmt: skip
    with store.connect() as conn, transaction(conn):
        run_id = conn.execute(
            "INSERT INTO topic_run (model, prompt_version, request, started_at)"
            " VALUES (?, ?, ?, ?) RETURNING id",
            (model, version, json.dumps(request), now()),
        ).fetchone()[0]
    try:
        done = call(
            model, system, messages, DISCOVERY_SCHEMA, None,
            effort=claude.EFFORT, max_tokens=claude.MAX_TOKENS,
        )  # fmt: skip
        try:
            taken = {t["key"] for t in existing}
            out = checked_topics(done.output, len(pages), len(alive), taken)
        except ValueError as error:
            raise claude.CallError("invalid", str(error), completion=done) from None
    except claude.CallError as error:
        failed(store, run_id, error, "topic_run")
        return error, found

    def cited(ns: list[int]) -> list[dict[str, str]]:
        return [{"id": pages[n - 1]["id"], "title": pages[n - 1]["title"]} for n in ns]

    found["new"] = [{**t, "sources": cited(t["sources"])} for t in out["new"]]
    for a in out["add"]:
        topic = alive[a["topic"] - 1]
        fresh = [s for s in cited(a["sources"]) if s["id"] not in topic["sources"]]
        if fresh:
            found["add"].append(
                {"topic": topic["id"], "title": topic["title"], "sources": fresh}
            )
    with store.connect() as conn, transaction(conn):
        record(conn, run_id, done, "topic_run", status="ok", output=json.dumps(found))
        if not dry_run:
            make(store, conn, found, done.served_model)
        resume(conn, now())  # a success ends any pause
    return None, found


def make(
    store: Store, conn: sqlite3.Connection, found: dict[str, Any], producer: str
) -> None:
    """What discovery found, made: each new topic's page (indexed for search) and its
    sources, and new sources for existing topics. One whose key was taken meanwhile
    is left out."""
    stamp = now()
    for t in found["new"]:
        slug = store._slug(conn, t["title"])  # noqa: SLF001  one transaction
        page_id = topics.create(conn, t["title"], t["key"], slug, producer, stamp)
        if page_id is None:
            t["made"] = False
            continue
        t["made"], t["id"] = True, page_id
        topics.add_sources(conn, page_id, [s["id"] for s in t["sources"]], producer,
                           stamp)  # fmt: skip
        store.reindex(conn, page_id)
    for a in found["add"]:
        topics.add_sources(conn, a["topic"], [s["id"] for s in a["sources"]],
                           producer, stamp)  # fmt: skip


def due(
    conn: sqlite3.Connection, every: bool = False, limit: int | None = None
) -> list[str]:
    """The topics whose synthesis is due (TOPIC_DUE; every: all of them), those with
    none first, at most limit."""
    return [r[0] for r in conn.execute(TOPIC_DUE, {
        "all": every, "version": topic_prompt()[1],
        "limit": -1 if limit is None else limit,
    })]  # fmt: skip


def topics_pass(
    store: Store,
    call: Call | None = None,
    every: bool = False,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """The weekly topics pass (scrap enrich --topics): one discovery call here and
    now (as the related pass's, it stops at a queue pause or the day's budget, or
    makes one), then a synthesis queued for each topic due (every: each topic), at
    most limit, for the service's worker. dry_run makes the call (and records it)
    but writes nothing and queues nothing. Returns the counts and what was found."""
    call = call or claude.complete
    budget = int(float(os.environ.get("SCRAP_BUDGET_DAY_USD", "3")) * 1e6)
    found: dict[str, Any] = {"new": [], "add": []}

    def one(_: str) -> claude.CallError | None:
        error, got = discover(store, call, dry_run)
        found.update(got)
        return error

    counts = run_pass(store, ["discovery"], one, budget)
    with store.connect() as conn, transaction(conn):
        ids = due(conn, every, limit)
        if not dry_run:
            for page_id in ids:
                queue_topic(conn, page_id)
    return {
        "stopped": counts["stopped"],
        "failed": counts["failed"],
        "new": [t for t in found["new"] if t.get("made", dry_run)],
        "add": found["add"],
        "queued": len(ids),
    }
