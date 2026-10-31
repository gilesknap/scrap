"""A test helper: claude.complete faked, for subclasses to answer by the call's
schema, and run_all, which runs the ingest worker with it until no job is left."""

import json
from typing import Any

from scrap import claude, enrich, ingest


class FakeClaude:
    """claude.complete, faked. A call's kind is told by its schema, among those the
    subclass names in `schemas` (photo, writeup, topic, discovery or related), and is
    "enrich" for any other; the subclass answers each kind but enrich with answer().
    record() keeps each call in self.calls; an answer that is an exception is raised."""

    schemas: tuple[str, ...] = ()

    def __init__(self):
        self.calls: list[Any] = []

    def answer(self, kind: str, system: Any, messages: Any) -> Any:
        raise NotImplementedError(kind)

    def record(self, kind: str, **call: Any) -> None:
        """Keep the call as a dict: kind, model, system, messages, blob and the rest."""
        self.calls.append({"kind": kind, **call})

    def kinds(self) -> list[str]:
        """The kinds of the calls made, in order (with record() as it is here)."""
        return [c["kind"] for c in self.calls]

    def __call__(self, model, system, messages, schema, blob, **kw):
        by_schema = {
            "photo": claude.SCHEMA,
            "writeup": enrich.WRITEUP_SCHEMA,
            "topic": enrich.TOPIC_SCHEMA,
            "discovery": enrich.DISCOVERY_SCHEMA,
            "related": enrich.RELATED_SCHEMA,
        }
        kind = next((k for k in self.schemas if schema is by_schema[k]), "enrich")
        self.record(
            kind, model=model, system=system, messages=messages, blob=blob, **kw
        )
        if kind == "enrich":
            out = {"tags": [], "summary": "", "title": "",
                   "intent": "other", "confidence": "low", "items": []}  # fmt: skip
        else:
            out = self.answer(kind, system, messages)
        if isinstance(out, BaseException):
            raise out
        usage = {"input_tokens": 1000, "output_tokens": 100}
        content = [{"type": "text", "text": json.dumps(out)}]
        return claude.Completion(out, content, usage, model, "end_turn")


def run_all(store, fake):
    """Run the ingest worker, calling fake for Claude, until no job is left."""
    w = ingest.Worker(store, fake)
    while w.step():
        pass
