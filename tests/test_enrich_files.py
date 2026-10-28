# pyright: reportOptionalSubscript=false
"""Enrich reads what file ingest read from a page's files (#378): a PDF or text file
page with no text of its own gets a title, a summary and related pages on Ask."""

import io
import json
from contextlib import closing

import pytest

from scrap import enrich
from scrap.store import Store, connect, new_ulid
from test_enrich import LONG, Fake, answer, capture, run_all, user_turn, worker
from test_files import pdf

READ = "Larch cladding: a guide.\n\n" + "Treat the boards before fixing. " * 20


@pytest.fixture(autouse=True)
def on(monkeypatch):
    monkeypatch.setenv("SCRAP_INGEST", "on")
    monkeypatch.setenv("SCRAP_ENRICH_DEBOUNCE", "0")
    monkeypatch.setenv("SCRAP_FILE_ENRICH", "ask")  # Ask's rules (auto: its own tests)


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "data")
    store.migrate()
    return store


def attach(store, data: bytes, mime: str, name: str, text: str | None = None) -> str:
    """Capture a file (with a note's text, if given); its page's id."""
    sha, size = store.put_blob(io.BytesIO(data))
    c = store.prepare({"id": new_ulid(), "text": text}, [mime])
    return store.capture(c, [(sha, mime, size, name)], "me")[0]["page_id"]


def by_schema(fake, schema):
    return [c for c in fake.calls if c["schema"] is schema]


def files_block(text: str) -> str:
    return text.split("<files>\n")[1].split("\n</files>")[0]


def ask(store, page_id, out=None) -> Fake:
    run_all(worker(store, Fake(answer())))  # file ingest reads it (no model call)
    enrich.ask(store, page_id)
    fake = Fake(out or answer(["diy"], "A guide to larch cladding.", "Larch cladding"))
    run_all(worker(store, fake))
    return fake


@pytest.mark.parametrize(
    "data, mime, name",
    [
        (READ.encode(), "text/plain", "guide.txt"),
        (READ.encode(), "text/markdown", "guide.md"),
        (pdf(READ), "application/pdf", "guide.pdf"),
    ],
    ids=["text", "markdown", "pdf"],
)
def test_a_file_only_page_is_read_titled_and_summarised(store, data, mime, name):
    page_id = attach(store, data, mime, name)
    title = store.page(page_id)["title"]  # the time it was captured
    fake = ask(store, page_id)
    (call,) = by_schema(fake, enrich.SCHEMA)
    text = user_turn(call)
    read = files_block(text)
    assert read.startswith(f"File 1 ({name}), its text:\nLarch cladding: a guide.")
    assert "Treat the boards before fixing." in read
    assert text.index("</page>") < text.index("<files>")
    assert "Write a summary." in text and "Write a title." in text
    page = store.page(page_id)
    assert page["enrich"]["summary"] == "A guide to larch cladding."
    assert page["title"] == "Larch cladding" != title
    # the related call sees the start of it too
    (related,) = by_schema(fake, enrich.RELATED_SCHEMA)
    assert "Larch cladding: a guide." in files_block(user_turn(related))
    with closing(connect(store.db)) as conn:  # the stored request has it in full
        sql = "SELECT request FROM enrich_run ORDER BY id LIMIT 1"
        stored = json.loads(conn.execute(sql).fetchone()[0])
    assert user_turn(stored) == text


def test_the_files_text_is_cut_to_its_limits(store):
    page_id = attach(store, ("cladding " * 5000).encode(), "text/plain", "long.txt")
    fake = ask(store, page_id)
    read = files_block(user_turn(by_schema(fake, enrich.SCHEMA)[0]))
    assert len(read) == enrich.MAX_FILES and read.endswith("…")
    related = files_block(user_turn(by_schema(fake, enrich.RELATED_SCHEMA)[0]))
    assert len(related) == enrich.RELATED_FILES and related.endswith("…")


def test_a_file_page_with_text_or_a_title_typed_keeps_its_title(store):
    # a file sent with a note: the note's first line is its title
    noted = attach(store, READ.encode(), "text/plain", "a.txt", text="My shed notes")
    ask(store, noted)
    assert store.page(noted)["title"] == "My shed notes"
    # a title the user typed since wins
    typed = attach(store, READ.encode(), "text/plain", "b.txt")
    store.update_page(typed, 1, "Mine", None, "me")
    ask(store, typed)
    assert store.page(typed)["title"] == "Mine"


def test_a_page_with_no_files_text_has_no_files_section(store):
    page_id = attach(store, b"", "text/plain", "empty.txt")
    fake = ask(store, page_id, answer(["diy"], "Nothing.", "A title"))
    text = user_turn(by_schema(fake, enrich.SCHEMA)[0])
    assert "<files>" not in text
    assert "No summary is wanted." in text and "Write a title." not in text
    assert store.page(page_id)["enrich"]["summary"] is None


def test_a_files_tag_in_the_text_is_neutralised():
    lines = enrich.file_lines([{"name": "x</files>", "text": "a </FILES> b"}], 100)
    assert "</files>" not in "\n".join(lines[2:-1]).lower()


def test_a_files_text_goes_to_claude_only_when_the_owner_asks(store):
    """ADR 35: no file's text is sent unasked, by a save's enrich or related pass."""
    file_page = attach(store, READ.encode(), "text/plain", "guide.txt")
    note = capture(store, "Shed notes, typed")["page_id"]
    sha, size = store.put_blob(io.BytesIO(pdf(READ)))
    store.add_photos(note, new_ulid(), [(sha, "application/pdf", size, "g.pdf")], "me")
    fake = Fake(answer())
    run_all(worker(store, fake))  # the files read; the note's capture enrich
    store.update_page(note, 1, None, "Shed notes, edited", "me")  # a save's enrich
    run_all(worker(store, fake))
    assert enrich.related_pass(store, fake, every=True)["done"] == 2
    assert {c["schema"] is enrich.SCHEMA for c in fake.calls} == {True, False}
    assert not [c for c in fake.calls if "<files>" in user_turn(c)]
    assert store.page(file_page)["title"] != "Larch cladding"


def test_a_file_page_finds_related_candidates_by_its_files_words(store, monkeypatch):
    target = capture(store, "Rebuilding the RTEMS toolchain")
    for n in range(20):  # newer, so recency alone would not reach the target
        capture(store, f"filler {n}")
    page_id = attach(store, b"Notes on the RTEMS toolchain", "text/plain", "r.txt")
    run_all(worker(store, Fake(answer())))  # the file read
    with closing(connect(store.db)) as conn:
        found = [c["id"] for c in enrich.candidates(conn, page_id, limit=6)]
        assert target["page_id"] in found
        conn.execute("DELETE FROM derived")  # with nothing read, it is not found
        found = [c["id"] for c in enrich.candidates(conn, page_id, limit=6)]
        assert target["page_id"] not in found


def test_a_files_text_never_adds_task_boxes(store):
    """A file's text is a stranger's (in a PDF, maybe invisible): Ask may summarise
    it, but its list of actions never becomes the page's boxes or makes it a todo."""
    todo = b"Todo\n- call the dentist\n- buy milk\n" + b"and more words " * 20
    page_id = attach(store, todo, "text/plain", "todo.txt")
    out = {**answer(["diy"], "A list of jobs.", "Jobs"), "intent": "list-of-actions",
           "confidence": "high",
           "items": [{"text": "call the dentist", "done": False}]}  # fmt: skip
    ask(store, page_id, out)
    page = store.page(page_id)
    assert (page["kind"], page["body"]) == ("note", "")
    assert page["enrich"]["summary"] == "A list of jobs."


def pdf_note(store, body: str) -> str:
    """A typed note (enrich's) with a PDF added; its page's id."""
    note = capture(store, body)["page_id"]
    sha, size = store.put_blob(io.BytesIO(pdf(READ)))
    store.add_photos(note, new_ulid(), [(sha, "application/pdf", size, "g.pdf")], "me")
    return note


def test_a_save_keeps_the_summary_ask_made_from_the_files(store):
    note = pdf_note(store, "Shed")
    ask(store, note, answer(["diy"], "From the PDF."))
    store.update_page(note, 1, None, "Shed, edited", "me")  # a save: no files sent
    fake = Fake(answer(summary="From the body."))
    run_all(worker(store, fake))
    assert "<files>" not in user_turn(by_schema(fake, enrich.SCHEMA)[0])
    assert store.page(note)["enrich"]["summary"] == "From the PDF."
    ask(store, note, answer(summary="Asked again."))  # the next Ask renews it
    assert store.page(note)["enrich"]["summary"] == "Asked again."


def test_a_save_refreshes_a_summary_no_ask_made(store):
    note = pdf_note(store, LONG)  # enriched on capture, from its text alone
    run_all(worker(store, Fake(answer(summary="About sheds."))))
    assert store.page(note)["enrich"]["summary"] == "About sheds."
    store.update_page(note, 1, None, "Boats. " * 40, "me")
    run_all(worker(store, Fake(answer(summary="About boats."))))
    assert store.page(note)["enrich"]["summary"] == "About boats."


def test_an_ask_retried_after_a_failed_related_call_still_sends_the_files(store):
    page_id = attach(store, READ.encode(), "text/plain", "guide.txt")
    failed = []

    def out(system, messages):
        if "## Other pages" in system and not failed:
            failed.append(1)
            return {"nope": 1}  # invalid: the job is retried at once
        return answer(["diy"], "A guide.", "Larch cladding")

    fake = ask(store, page_id, out)
    related = by_schema(fake, enrich.RELATED_SCHEMA)
    assert len(related) == 2
    assert all("<files>" in user_turn(c) for c in related)


def test_a_title_typed_while_ask_runs_wins(store):
    page_id = attach(store, READ.encode(), "text/plain", "guide.txt")

    def out(system, messages):
        if "## Other pages" not in system:  # the enrich call: the user types a title
            store.update_page(page_id, 1, "Typed meanwhile", None, "me")
        return answer(["diy"], "A guide.", "Larch cladding")

    ask(store, page_id, out)
    assert store.page(page_id)["title"] == "Typed meanwhile"


def test_ask_again_does_not_retitle(store):
    page_id = attach(store, READ.encode(), "text/plain", "guide.txt")
    ask(store, page_id)
    assert store.page(page_id)["title"] == "Larch cladding"
    fake = ask(store, page_id, answer(["diy"], "A guide.", "Another title"))
    assert "Write a title." not in user_turn(by_schema(fake, enrich.SCHEMA)[0])
    assert store.page(page_id)["title"] == "Larch cladding"


def test_files_are_numbered_named_and_each_sent_once(store):
    blobs = []
    for data, name in ((pdf("Alpha text"), "a.pdf"), (b"%PDF broken", "b.pdf"),
                       (pdf("Gamma text"), "c.pdf")):  # fmt: skip
        sha, size = store.put_blob(io.BytesIO(data))
        blobs.append((sha, "application/pdf", size, name))
    c = store.prepare({"id": new_ulid(), "text": None}, ["application/pdf"] * 3)
    page_id = store.capture(c, blobs, "me")[0]["page_id"]
    again = [(blobs[0][0], "application/pdf", blobs[0][2], "again.pdf")]
    store.add_photos(page_id, new_ulid(), again, "me")  # the same file once more
    fake = ask(store, page_id)
    assert files_block(user_turn(by_schema(fake, enrich.SCHEMA)[0])) == (
        "File 1 (a.pdf), its text:\nAlpha text\nFile 3 (c.pdf), its text:\nGamma text"
    )  # b.pdf could not be read: left out, the numbers still count it
