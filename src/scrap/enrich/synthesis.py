"""Enrich: a topic's synthesis (#261), one call, as an enrich job of reason topic.

A topic is a page (store.topics) whose body is the owner's notes; Claude's synthesis of
its sources is its write-up (store.writeups), stored apart from the text as a new
version, never in the body. One Opus call sees each source (its title, kind, tags,
summary, Claude's write-up of it, what was read from its images and its text, cut to
fit TOPIC_INPUT in all), the owner's notes and guidance, and cites sources by number,
made page links here (checking.cited), so it cannot name a page that is not one.
"""

import json
from typing import Any

from .. import claude
from ..runs import failed, start_run
from ..store import (
    Store,
    model_summary,
    roles,
    topics,
    transaction,
    writeups,
)
from .checking import checked_writeup
from .constants import MAX_TOPIC_SOURCES, TOPIC_INPUT, TOPIC_SCHEMA, TOPIC_SOURCE
from .prompts import page_images
from .topic_prompts import source_text, topic_message, topic_prompt
from .types import Call
from .writeup_store import written


def inputs(
    store: Store, page_id: str
) -> tuple[Any, list[dict[str, Any]], list[str], str | None] | None:
    """A topic's page, its sources (at most MAX_TOPIC_SOURCES, first added first, each
    with its tags, summary and body), their texts as the call sees them, and the
    owner's guidance; None if it is not a topic (or in the trash) or has no source
    in."""
    with store.connect() as conn:
        page = conn.execute(
            "SELECT * FROM page WHERE id = ? AND deleted_at IS NULL", (page_id,)
        ).fetchone()
        if page is None or not roles.is_topic(conn, page_id):
            return None
        found = topics.sources(conn, page_id)[:MAX_TOPIC_SOURCES]
        if not found:
            return None
        most = min(TOPIC_SOURCE, TOPIC_INPUT // len(found))
        sources, texts = [], []
        for s in found:
            row = conn.execute(
                "SELECT body, fields FROM page WHERE id = ?", (s["id"],)
            ).fetchone()
            human = json.loads(row["fields"]).get("summary")
            up = writeups.shown(conn, s["id"])
            source = {
                **s,
                "body": row["body"],
                "summary": human if isinstance(human, str)
                else model_summary(conn, s["id"]),
                "tags": [r[0] for r in conn.execute(
                    "SELECT tag FROM tag WHERE page_id = ? ORDER BY tag", (s["id"],))],
            }  # fmt: skip
            sources.append(source)
            images = page_images(conn, s["id"])
            texts.append(source_text(source, images, up["text"] if up else "", most))
        guidance = writeups.guidance(conn, page_id)
    return page, sources, texts, guidance


def synthesise(
    store: Store, call: Call, page_id: str, job_id: int | None = None
) -> claude.CallError | None:
    """One synthesis call for a topic; on success its synthesis is a new current
    write-up, and the page is indexed again. The run is recorded either way; a
    failure is returned for the caller to act on (pause, charge or carry on). None:
    done, or nothing to do (not a topic, in the trash, or no source in)."""
    got = inputs(store, page_id)
    if got is None:
        return None
    page, sources, texts, guidance = got
    slugs = [s["slug"] for s in sources]
    system, version = topic_prompt()
    messages = topic_message(page, sources, texts, guidance)
    model = claude.model_name()
    request = {
        "purpose": "topic", "model": model, "max_tokens": claude.MAX_TOKENS,
        "effort": claude.EFFORT, "system": system, "messages": messages,
        "schema": TOPIC_SCHEMA, "sources": [s["id"] for s in sources],
        "guidance": guidance, "backend": claude.backend(),
    }  # fmt: skip
    with store.connect() as conn, transaction(conn):
        run_id = start_run(conn, "enrich_run", page_id=page_id, job_id=job_id,
                           model=model, prompt_version=version,
                           request=json.dumps(request))  # fmt: skip
    try:
        done = call(
            model, system, messages, TOPIC_SCHEMA, None,
            effort=claude.EFFORT, max_tokens=claude.MAX_TOKENS,
        )  # fmt: skip
        try:
            out = checked_writeup(done.output, slugs)
        except ValueError as error:
            raise claude.CallError("invalid", str(error), completion=done) from None
    except claude.CallError as error:
        with store.connect() as conn, transaction(conn):
            failed(conn, "enrich_run", run_id, error)
        return error
    written(store, run_id, page_id, done, version, out, guidance)
    return None
