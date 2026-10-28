"""The section order search groups by (store/grouping.py) against the cases the PWA's
groups.ts and now.ts are held to too (web/tests/sections.test.ts): the two mirror each
other, so a change to one that the other lacks fails here or there."""

import json
from pathlib import Path

import pytest

from scrap.store import grouping

DATA = json.loads((Path(__file__).parent / "section_cases.json").read_text())


def key(group: str, page: dict, today: str) -> str:
    kind, due = page["kind"], page.get("due")
    fields = json.dumps(page.get("fields", {}))
    match group:
        case "letter":
            return grouping.letter(page["title"])
        case "type":
            return grouping.type_key(kind, fields)
        case "due":
            return grouping.due_key(kind, fields, due, today)
        case _:
            stamp = "2026-10-01T00:00:00Z"
            return grouping.now_key(
                kind, fields, due, page.get("priority"), stamp, today, 0
            )


@pytest.mark.parametrize("case", DATA["cases"], ids=lambda c: c["group"])
def test_the_server_orders_pages_as_the_pwa_sections_them(case):
    today = DATA["today"]
    pages = case["pages"]
    ordered = sorted(
        range(len(pages)), key=lambda i: (key(case["group"], pages[i], today), i)
    )
    assert [pages[i]["title"] for i in ordered] == case["order"]
