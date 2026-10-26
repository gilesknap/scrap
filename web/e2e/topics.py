"""E2E fixture: a topic page (#261), three sources and a synthesis by a fake Claude.

Run as `uv run python web/e2e/topics.py DATA_DIR` while scrap serves DATA_DIR. It adds
three tagged notes, makes a topic of them as the weekly pass would, and has its
synthesis written with a canned answer instead of calling Claude (citing two of the
sources), then prints {"slug", "title", "sources": [{"id", "slug", "title"}]} as JSON.
Each run makes its own (a word of its own in every title). Nothing in it is real or
private.
"""

import json
import sys

from scrap import claude, enrich
from scrap.store import Store, new_ulid, topics, transaction


def synthesis(word: str):
    """The fake Claude: the topic's synthesis, citing sources 1 and 2."""

    def fake(model, system, messages, schema, blob, **kw):
        out = {
            "summary": f"How {word} builds IOCs from YAML, and where it runs.",
            "text": "## Overview\n\nIt makes IOCs from YAML [[1]].\n\n## Key facts\n\n"
            f"- It checks a schema [[2|the {word} schema]].\n\n"
            "## Contradictions and open questions\n\n- None yet.",
        }
        content = [{"type": "text", "text": json.dumps(out)}]
        usage = {"input_tokens": 1, "output_tokens": 1}
        return claude.Completion(out, content, usage, model, "end_turn")

    return fake


def main(data_dir: str) -> None:
    store = Store(data_dir)
    word = f"zeb{new_ulid().lower()[-6:]}"  # its own, so each run's topic is apart
    sources = []
    for title, tag in ((f"{word} yaml", "epics/ioc"), (f"{word} schema", "epics"),
                       (f"{word} runtime", "k8s")):  # fmt: skip
        c = store.prepare(
            {"id": new_ulid(), "text": f"{title}\n\nnotes on {title}"}, []
        )
        ref = store.capture(c, [], "e2e", [tag])[0]
        sources.append({"id": ref["page_id"], "slug": ref["slug"], "title": title})
    title = f"{word.capitalize()} toolkit"
    with store.connect() as conn, transaction(conn):  # as the weekly pass makes one
        slug = store._slug(conn, title)  # noqa: SLF001  one transaction
        page_id = topics.create(
            conn, title, word, slug, "claude", "2026-10-25T00:00:00Z"
        )
        assert page_id is not None
        topics.add_sources(conn, page_id, [s["id"] for s in sources], "claude",
                           "2026-10-25T00:00:00Z")  # fmt: skip
        store.reindex(conn, page_id)
    assert enrich.synthesise(store, synthesis(word), page_id) is None
    print(json.dumps({"slug": slug, "title": title, "word": word, "sources": sources}))


if __name__ == "__main__":
    main(sys.argv[1])
