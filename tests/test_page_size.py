"""#62: a page's text is at most 1 MB of UTF-8, however it is written."""

from scrap.ingest import put_derived
from scrap.store import MAX_PAGE, Store, new_ulid, now, transaction

BIG = "é" * (MAX_PAGE // 2 + 1)  # just over in bytes, under in characters


def test_a_capture_over_the_limit_is_refused_and_one_at_it_is_kept(client):
    r = client.post("/api/captures", json={"id": new_ulid(), "text": BIG})
    assert r.status_code == 422
    assert "page text is 1.00 MB: a page holds at most 1 MB" in r.json()["detail"]
    assert client.get("/api/pages").json() == []
    r = client.post("/api/captures", json={"id": new_ulid(), "text": "x" * MAX_PAGE})
    assert r.status_code == 201


def test_a_capture_with_a_file_is_refused_before_the_file_is_kept(client, tmp_path):
    files = [("file", ("p.png", b"\x89PNG", "image/png"))]
    r = client.post("/api/captures", data={"id": new_ulid(), "text": BIG}, files=files)
    assert r.status_code == 422
    assert not [f for f in (tmp_path / "data" / "files").rglob("*") if f.is_file()]


def test_an_edit_over_the_limit_is_refused_and_changes_nothing(client, note):
    ref = note("Short")
    r = client.patch(f"/api/pages/{ref['page_id']}", json={"base_rev": 1, "body": BIG})
    assert r.status_code == 422 and "at most 1 MB" in r.json()["detail"]
    page = client.get(f"/api/pages/{ref['page_id']}").json()
    assert (page["body"], page["rev"]) == ("Short", 1)


def test_a_derived_text_is_cut_to_the_limit(client, note, tmp_path):
    ref = note("Photo text")
    store = Store(tmp_path / "data")
    with store.connect() as conn, transaction(conn):
        row = put_derived(
            conn, ref["capture_id"], "", "ocr", "m", now(), text="ab" * MAX_PAGE
        )
        text = conn.execute("SELECT text FROM derived WHERE id = ?", (row[0],))
        assert len(text.fetchone()[0].encode()) == MAX_PAGE
