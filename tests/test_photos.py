# pyright: reportOptionalSubscript=false
"""Adding photos to a page that exists (#260): POST /api/pages/{key}/captures."""

import io
import json
from contextlib import closing

from fastapi.testclient import TestClient
from PIL import Image

from scrap import claude, ingest
from scrap.app import create_app
from scrap.store import Store, connect, new_ulid, now, topics, transaction
from scrap.store.roles import should_enrich

BOARD = {
    "kind": "whiteboard", "title": "Queue design", "tags": ["design", "queues"],
    "description": "A sketch of a job queue", "text": "kafka consumer lag",
    "elements": [],
}  # fmt: skip


STICKY = {
    **BOARD, "title": "Actions", "intent": "list-of-actions", "confidence": "high",
    "items": [{"text": "ring Sam", "done": False}],
}  # fmt: skip


def reading(out):
    """Claude, reading every photo as out."""

    def call(model, system, messages, schema, blob, **kw):
        content = [{"type": "text", "text": json.dumps(out)}]
        usage = {"input_tokens": 1, "output_tokens": 1}
        return claude.Completion(out, content, usage, model, "end_turn")

    return call


fake = reading(BOARD)


def jpeg(colour="red") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 30), colour).save(out, "JPEG")
    return out.getvalue()


def add(client, key, *images, cid=None, name="b.jpg", mime="image/jpeg"):
    data = {"id": cid or new_ulid()}
    files = [("file", (name, data_, mime)) for data_ in images]
    return client.post(f"/api/pages/{key}/captures", data=data, files=files)


def embed(page, n):
    return f"![](/api/blobs/{blobs(page)[n]}/preview?size=2048)"


def blobs(page):
    return [b["sha256"] for c in page["captures"] for b in c["blobs"]]


def test_adding_a_photo_appends_its_embed_as_a_revision_and_queues_it(client, note):
    ref = note("Board notes\nfirst draft")
    r = add(client, ref["slug"], jpeg("red"), jpeg("blue"))
    assert r.status_code == 201, r.text
    page = r.json()
    assert (page["rev"], page["appended_on"]) == (2, 1)
    assert page["title"] == "Board notes"
    images = f"{embed(page, 0)}\n\n{embed(page, 1)}"
    assert page["body"] == f"Board notes\nfirst draft\n\n{images}"
    note_capture, photos = page["captures"]
    assert note_capture["kind"] == "note" and photos["kind"] == "photo"
    assert [b["ingest"]["state"] for b in photos["blobs"]] == ["queued", "queued"]


def test_a_retry_with_the_same_id_changes_nothing(client, note):
    ref = note("Retry me")
    cid = new_ulid()
    assert add(client, ref["page_id"], jpeg(), cid=cid).status_code == 201
    again = add(client, ref["page_id"], jpeg(), cid=cid)
    assert again.status_code == 200
    assert (again.json()["rev"], again.json()["appended_on"]) == (2, None)
    assert len(again.json()["captures"]) == 2
    other = note("Another page")
    assert add(client, other["page_id"], jpeg(), cid=cid).status_code == 422


def test_photos_go_onto_the_text_as_it_is_now(client, note):
    # No revision is checked (a base_rev sent is ignored): appending loses nothing
    ref = note("Edited meanwhile")
    edit = {"base_rev": 1, "body": "Edited meanwhile\nmore"}
    client.patch(f"/api/pages/{ref['page_id']}", json=edit)
    path = f"/api/pages/{ref['page_id']}/captures"
    data = {"id": new_ulid(), "base_rev": "1"}
    r = client.post(path, data=data, files=[("file", ("b.jpg", jpeg(), "image/jpeg"))])
    page = r.json()
    assert r.status_code == 201 and (page["rev"], page["appended_on"]) == (3, 2)
    assert page["body"] == f"Edited meanwhile\nmore\n\n{embed(page, 0)}"


def test_bad_requests_are_refused(client, note):
    ref = note("Refusals")
    path = f"/api/pages/{ref['page_id']}/captures"
    assert add(client, "no-such-page", jpeg()).status_code == 404
    assert add(client, ref["page_id"], jpeg(), cid="nope").status_code == 422
    assert add(client, ref["page_id"]).status_code == 422  # no file
    files = [("file", ("a.jpg", jpeg(), "image/jpeg"))]
    data = {"id": new_ulid(), "source": "mcp"}
    assert client.post(path, data=data, files=files).status_code == 422
    data = {"id": new_ulid(), "created_at": "soon"}
    assert client.post(path, data=data, files=files).status_code == 422
    assert client.post(path, json={"id": new_ulid()}).status_code == 422
    assert client.get(f"/api/pages/{ref['page_id']}").json()["rev"] == 1


def test_only_images_can_be_added(client, note):
    ref = note("Minutes")
    pdf = add(client, ref["page_id"], b"%PDF", name="m.pdf", mime="application/pdf")
    assert pdf.status_code == 415
    assert "Only images" in pdf.json()["detail"]
    mixed = client.post(
        f"/api/pages/{ref['page_id']}/captures",
        data={"id": new_ulid()},
        files=[("file", ("a.jpg", jpeg(), "image/jpeg")),
               ("file", ("m.pdf", b"%PDF", "application/pdf"))],
    )  # fmt: skip
    assert mixed.status_code == 415
    page = client.get(f"/api/pages/{ref['page_id']}").json()
    assert (page["rev"], len(page["captures"])) == (1, 1)


def test_a_trashed_page_takes_no_photos(client, note):
    ref = note("Binned")
    client.delete(f"/api/pages/{ref['page_id']}")
    assert add(client, ref["page_id"], jpeg()).status_code == 404
    assert add(client, ref["slug"], jpeg()).status_code == 404


def test_over_the_upload_limit_is_413(tmp_path, monkeypatch, note):
    monkeypatch.setenv("SCRAP_MAX_UPLOAD_MB", "0.01")  # about 10 KB
    client = TestClient(create_app(tmp_path / "small"))
    ref = client.post("/api/captures", json={"id": new_ulid(), "text": "Small"}).json()
    r = add(client, ref["page_id"], bytes(20_000))
    assert r.status_code == 413 and "upload limit" in r.json()["detail"]
    assert add(client, ref["page_id"], jpeg()).status_code == 201


def test_an_image_the_text_shows_already_adds_no_revision(client, note):
    ref = note("Pasted")
    first = add(client, ref["page_id"], jpeg("green")).json()
    body = f"Pasted\n\n{embed(first, 0)}"
    assert first["body"] == body
    again = add(client, ref["page_id"], jpeg("green")).json()  # the same bytes
    assert (again["rev"], again["appended_on"], again["body"]) == (2, 2, body)
    assert len(again["captures"]) == 3  # still a capture: its photo is read


def test_new_images_come_after_the_pages_own(client):
    data = {"id": new_ulid()}
    files = [("file", ("a.jpg", jpeg("red"), "image/jpeg"))]
    ref = client.post("/api/captures", data=data, files=files).json()
    add(client, ref["page_id"], jpeg("blue"))
    page = add(client, ref["page_id"], jpeg("white")).json()
    assert page["body"] == "\n\n".join(embed(page, n) for n in range(3))
    stamps = [c["received_at"] for c in page["captures"]]
    assert stamps == sorted(stamps)
    rows = client.get("/api/pages").json()
    assert rows[0]["thumb"] == blobs(page)[0]  # the page's first image, still


def run_all(tmp_path, out):
    worker = ingest.Worker(Store(tmp_path / "data"), reading(out))
    while worker.step():
        pass


def test_an_added_photo_is_read_but_changes_no_kind_title_or_tags(
    client, note, tmp_path
):
    # The page's first capture decides what it is; added photos only add content
    ref = note("My whiteboard")
    client.patch(f"/api/pages/{ref['page_id']}", json={"tags": ["mine"]})
    page = add(client, ref["page_id"], jpeg()).json()
    run_all(tmp_path, BOARD)
    read = client.get(f"/api/pages/{ref['page_id']}").json()
    assert (read["title"], read["kind"], read["kind_fixed"]) == (
        "My whiteboard",
        "note",
        0,
    )
    assert read["tags"] == ["mine"] and read["model_tags"] == []  # not BOARD's tags
    got = read["captures"][1]["blobs"][0]["ingest"]
    assert got["state"] == "done" and got["text"].startswith("kafka")
    assert got["image_kind"] == "whiteboard"  # read, as any photo
    assert read["body"] == page["body"]  # the text is the user's
    hits = client.get("/api/search", params={"q": "kafka"}).json()
    assert [h["id"] for h in hits] == [ref["page_id"]]  # what was read is searched
    # The owner can still file it by hand
    client.patch(f"/api/pages/{ref['page_id']}", json={"kind": "whiteboard"})
    assert client.get(f"/api/pages/{ref['page_id']}").json()["kind"] == "whiteboard"


def test_an_added_photo_never_retitles_the_page(client, note, tmp_path):
    # Its image shown already (a pasted link): no revision, yet the title stays
    first = note("Pasted board")
    shown = add(client, first["page_id"], jpeg("red")).json()
    ref = note(f"My title\n\n{embed(shown, 0)}")
    page = add(client, ref["page_id"], jpeg("red")).json()
    assert page["rev"] == 1
    run_all(tmp_path, BOARD)
    assert client.get(f"/api/pages/{ref['page_id']}").json()["title"] == "My title"


def test_an_added_sticky_writes_no_task_boxes(client, tmp_path):
    files = [("file", ("a.jpg", jpeg("red"), "image/jpeg"))]
    ref = client.post("/api/captures", data={"id": new_ulid()}, files=files).json()
    run_all(tmp_path, BOARD)  # filed as a whiteboard by ingest, not by the user
    board = client.get(f"/api/pages/{ref['page_id']}").json()
    assert (board["kind"], board["kind_fixed"]) == ("whiteboard", 0)
    add(client, ref["page_id"], jpeg("blue"))
    run_all(tmp_path, STICKY)
    page = client.get(f"/api/pages/{ref['page_id']}").json()
    assert page["kind"] == "whiteboard" and "- [ ]" not in page["body"]
    # Nor an unfixed note: its boxes would file it as a todo
    note = client.post("/api/captures", json={"id": new_ulid(), "text": "Plan"}).json()
    add(client, note["page_id"], jpeg("green"))
    run_all(tmp_path, STICKY)
    page = client.get(f"/api/pages/{note['page_id']}").json()
    assert page["kind"] == "note" and "- [ ]" not in page["body"]


def test_a_text_page_stays_enrichs_with_photos_added(client, note, tmp_path):
    text = note("Typed first")
    add(client, text["page_id"], jpeg())
    files = [("file", ("a.jpg", jpeg("blue"), "image/jpeg"))]
    photo = client.post("/api/captures", data={"id": new_ulid()}, files=files).json()
    with closing(connect(tmp_path / "data" / "scrap.db")) as conn:
        assert should_enrich(conn, text["page_id"])  # saves queue enrich still
        assert not should_enrich(conn, photo["page_id"])  # ingest's


def test_a_photo_and_files_import_reads_its_photo_first(tmp_path):
    # Received together: the file capture is last, whatever its (hash-derived) id
    s = Store(tmp_path / "data")
    s.migrate()
    img, size = s.put_blob(io.BytesIO(jpeg()))
    pdf, n = s.put_blob(io.BytesIO(b"%PDF"))
    stamp = "2026-01-01T00:00:00.000Z"
    p = {"slug": "board", "title": "Board", "body": "notes", "kind": "note",
         "fields": {}, "tags": [], "created_at": stamp,
         "updated_at": stamp}  # fmt: skip
    main, files = "01J0000000000000000000000F", "01J0000000000000000000000E"
    caps = [(main, "photo", "notes", [(img, "image/jpeg", size, None)]),
            (files, "file", None, [(pdf, "application/pdf", n, None)])]  # fmt: skip
    s.import_page(p, caps, "me", enqueue=True)
    run_all(tmp_path, BOARD)
    assert s.page("board")["tags"] == ["design", "queues"]  # Claude's, from the photo


def test_adding_photos_queues_no_save_enrich(client, note, tmp_path, monkeypatch):
    monkeypatch.setenv("SCRAP_INGEST", "on")
    ref = note("Typed first")
    add(client, ref["page_id"], jpeg())
    with closing(connect(tmp_path / "data" / "scrap.db")) as conn:
        reasons = [r[0] for r in conn.execute("SELECT reason FROM enrich_job")]
    assert reasons == ["capture"]  # the note's own; the photos' reading brings the rest


def test_a_topic_page_takes_no_photos(client, tmp_path):
    # Its synthesis is its write-up: a board photo would queue one over it
    s = Store(tmp_path / "data")
    with closing(connect(s.db)) as conn, transaction(conn):
        page_id = topics.create(conn, "Queues", "queues", "queues", "me", now())
    r = add(client, "queues", jpeg())
    assert r.status_code == 422 and "topic page" in r.json()["detail"]
    page = client.get(f"/api/pages/{page_id}").json()
    assert (page["rev"], page["captures"], page["topic"]["key"]) == (1, [], "queues")
