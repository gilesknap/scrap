"""A PDF's read text for the page view's file card: GET
/api/captures/{cid}/files/{sha}/text."""

from scrap import ingest
from scrap.store import Store, new_ulid
from test_files import NoCall, pdf


def test_a_pdfs_text_once_read_and_nothing_else(client, tmp_path):
    r = client.post(
        "/api/captures",
        data={"id": new_ulid(), "text": "Minutes"},
        files=[
            ("file", ("m.pdf", pdf("wombat budget"), "application/pdf")),
            ("file", ("n.txt", b"plain words", "text/plain")),
        ],
    )
    ref = r.json()
    page = client.get(f"/api/pages/{ref['page_id']}").json()
    cid = page["captures"][0]["id"]
    doc, txt = (b["sha256"] for b in page["captures"][0]["blobs"])
    url = f"/api/captures/{cid}/files/{doc}/text"
    assert client.get(url).json() == {"text": None, "truncated": False}  # not read yet
    store = Store(tmp_path / "data")
    while ingest.Worker(store, NoCall()).step():
        pass
    got = client.get(url).json()
    assert got["text"].split() == ["wombat", "budget"] and not got["truncated"]
    # A text file's own link opens its text: not served here; nor another capture's file
    assert client.get(f"/api/captures/{cid}/files/{txt}/text").status_code == 404
    other = new_ulid()
    assert client.get(f"/api/captures/{other}/files/{doc}/text").status_code == 404
    client.delete(f"/api/pages/{ref['page_id']}")
    assert client.get(url).status_code == 404  # in the trash
