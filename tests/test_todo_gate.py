"""Only store/todo.py knows where a todo's due and priority live (and nothing reads or
writes page_todo's snoozed_until, unused since Snooze was retired, kept for reuse).

A raw SQL mention anywhere else breaks when they move to a table of their own, so
this fails on one. API and pydantic field names are Python, not SQL, and are not
matched: only a column reference (an alias dot name, or SET/INSERT of it) is.
"""

import re
from pathlib import Path

import scrap

SRC = Path(scrap.__file__).parent
NAMES = r"(?:due|priority|snoozed_until)"
RAW = [
    re.compile(rf"\b(?:p|page|pg)\.{NAMES}\b"),  # an aliased column: p.due
    re.compile(rf"\{{p\}}\.{NAMES}\b"),  # a template alias: {p}.due
    re.compile(rf"\bSET\s+{NAMES}\b", re.I),  # UPDATE page SET due = ?
    re.compile(rf"\bUPDATE page SET [^\"']*\b{NAMES}\s*=", re.I),
    re.compile(rf"\bSELECT\b[^\"']*\b{NAMES}\b[^\"']*\bFROM page\b", re.I),
    re.compile(rf"\bINSERT INTO page\b[^\"']*\b{NAMES}\b", re.I),
    re.compile(rf"\b(?:ADD|DROP) COLUMN {NAMES}\b", re.I),
]
# The one home (the migrations are SQL files, not matched)
ALLOWED = {"store/todo.py"}


def hits() -> list[str]:
    found = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel in ALLOWED or rel.startswith("migrations/"):
            continue
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if not line.lstrip().startswith("#") and any(r.search(line) for r in RAW):
                found.append(f"{rel}:{n}: {line.strip()}")
    return found


def test_no_raw_todo_column_outside_store_todo():
    assert hits() == []


def test_the_gate_catches_what_it_should():
    bad = [
        "WHERE p.due < ?",
        "{p}.snoozed_until > ?",
        "UPDATE page SET due = ? WHERE id = ?",
        "SELECT id, priority FROM page",
        "INSERT INTO page (id, due) VALUES (?, ?)",
    ]
    ok = ['page["due"]', "body.priority", "due: str | None = None", "q.due(x)"]
    assert all(any(r.search(s) for r in RAW) for s in bad)
    assert not any(r.search(s) for s in ok for r in RAW)
