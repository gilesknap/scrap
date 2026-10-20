# pyright: reportOptionalSubscript=false
"""A photo's drawing through the API: view, save a human version, 409, restore, search,
and the drawing in a page download."""

import io
import json
import zipfile
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from scrap import ingest, sanitise
from scrap.app import create_app
from scrap.backup import export
from scrap.drawing import excalidraw_file
from scrap.sanitise import SCENE_BYTES
from scrap.store import InvalidError, Store, connect, new_ulid
from test_ingest import BOARD, Fake, jpeg


@pytest.fixture
def board(tmp_path):
    """A photo capture that Claude (faked) has drawn: (client, url of its drawing,
    page id)."""
    app = create_app(tmp_path)
    client = TestClient(app)
    files = [("file", ("board.jpg", jpeg(size=(800, 600)), "image/jpeg"))]
    ref = client.post("/api/captures", data={"id": new_ulid()}, files=files).json()
    assert ingest.Worker(Store(tmp_path), Fake(BOARD)).step()
    page = client.get(f"/api/pages/{ref['page_id']}").json()
    sha = page["captures"][0]["blobs"][0]["sha256"]
    return client, f"/api/captures/{ref['capture_id']}/photos/{sha}/drawing", ref


def scene(*texts, **extra):
    elements = [
        {"type": "text", "id": f"t{n}", "x": 10, "y": 10 * n, "text": t}
        for n, t in enumerate(texts)
    ]
    return {"elements": elements, **extra}


def test_the_model_drawing_is_current(board):
    client, url, _ = board
    got = client.get(url).json()
    assert got["version"] == 1 and got["producer"] != "human" and got["current"]
    assert got["data"]["format"] == "skeleton"
    assert (got["data"]["width"], got["data"]["height"]) == (800, 600)  # sent size
    assert [e["type"] for e in got["data"]["elements"]] == ["rectangle", "arrow"]


def test_save_versions_conflict_and_restore(board):
    client, url, ref = board
    put = client.put(url, json={"base_version": 1, "scene": scene("zebra crossing")})
    assert put.status_code == 200, put.text
    saved = put.json()
    assert (saved["version"], saved["producer"]) == (2, "human")
    assert saved["author"] == "tagged" and saved["data"]["format"] == "scene"
    assert (saved["data"]["width"], saved["data"]["height"]) == (800, 600)  # kept
    hits = client.get("/api/search", params={"q": "zebra"}).json()
    assert [h["id"] for h in hits] == [ref["page_id"]]  # its labels are searchable

    stale = client.put(url, json={"base_version": 1, "scene": scene("mine")})
    assert stale.status_code == 409 and stale.json()["version"] == 2
    assert client.get(url).json()["version"] == 2  # nothing written

    back = client.post(f"{url}/restore", json={"version": 1, "base_version": 2})
    assert back.status_code == 200
    restored = back.json()
    assert restored["version"] == 3 and restored["restored_from"] == 1
    assert restored["data"]["format"] == "skeleton"
    assert client.get("/api/search", params={"q": "zebra"}).json() == []
    stale = client.post(f"{url}/restore", json={"version": 2, "base_version": 2})
    assert stale.status_code == 409
    missing = client.post(f"{url}/restore", json={"version": 9, "base_version": 3})
    assert missing.status_code == 404

    history = client.get(f"{url}/versions").json()
    assert [(v["version"], v["current"]) for v in history] == [
        (3, True), (2, False), (1, False)
    ]  # fmt: skip
    assert history[1]["producer"] == "human" and history[0]["restored_from"] == 1
    # the page reports the current version for the PWA
    page = client.get(f"/api/pages/{ref['page_id']}").json()
    shown = page["captures"][0]["blobs"][0]["ingest"]["drawing"]
    assert (shown["version"], shown["width"], shown["height"]) == (3, 800, 600)


def test_an_unknown_photo_has_no_drawing(board):
    client, url, _ = board
    other = url.replace(url.split("/")[-2], "0" * 64)
    assert client.get(other).status_code == 404  # no such photo
    put = client.put(other, json={"base_version": None, "scene": scene()})
    assert put.status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        b'{"base_version": 1, "scene": {"elements": [{"type": "text", "x": NaN}]}}',
        b'{"base_version": 1, "scene": {"elements": [], "x": Infinity}}',
        b'{"base_version": 1, "scene": {"elements": [{"type": "image"}]}}',
        b'{"base_version": "1", "scene": {"elements": []}}',
        b'{"base_version": 1}',
        b"[]",
        b"not json",
    ],
)
def test_bad_scenes_are_422_and_change_nothing(board, body):
    client, url, _ = board
    response = client.put(url, content=body)
    assert response.status_code == 422, response.text
    assert client.get(url).json()["version"] == 1


def test_an_oversized_request_is_413(board):
    client, url, _ = board
    body = json.dumps({"base_version": 1, "scene": scene("x" * 9_000_000)})
    assert client.put(url, content=body).status_code == 413


def test_a_trashed_page_has_no_drawing(board):
    client, url, ref = board
    client.delete(f"/api/pages/{ref['page_id']}")
    assert client.get(url).status_code == 404
    assert client.get(f"{url}/versions").status_code == 404


def test_the_download_has_the_description_text_and_drawing(board):
    client, url, ref = board
    zf = zipfile.ZipFile(
        io.BytesIO(client.get(f"/api/pages/{ref['page_id']}/download").content)
    )
    names = zf.namelist()
    assert names[1:] == ["files/board.jpg", "files/board.excalidraw"]
    md = zf.read(names[0]).decode()
    assert "> A sketch of a job queue" in md
    assert "```text\nkafka consumer lag\nretry topic\n```" in md
    assert "[Drawing of board.jpg](files/board.excalidraw)" in md
    # the photo is in the text; below, named (not shown again) before Claude's notes
    assert "![board.jpg](files/board.jpg)" in md
    assert "\n[board.jpg](files/board.jpg)\n\n> A sketch" in md
    drawing = json.loads(zf.read("files/board.excalidraw"))
    assert drawing["type"] == "excalidraw" and drawing["files"] == {}
    rect, label, arrow = drawing["elements"]
    assert label["containerId"] == rect["id"] == "a" and label["text"] == "Queue"
    assert rect["boundElements"][0] == {"type": "text", "id": label["id"]}
    assert arrow["startBinding"]["elementId"] == "a" and arrow["endBinding"] is None
    assert arrow["points"] == [[0, 0], [50, 0]]
    # a human scene goes out as it was saved
    client.put(url, json={"base_version": 1, "scene": scene("mine")})
    zf = zipfile.ZipFile(
        io.BytesIO(client.get(f"/api/pages/{ref['page_id']}/download").content)
    )
    elements = json.loads(zf.read("files/board.excalidraw"))["elements"]
    assert [e["text"] for e in elements] == ["mine"]


def test_a_skeleton_file_names_every_element_once():
    skeleton = {"format": "skeleton", "elements": [
        {"type": "text", "x": 0, "y": 0, "text": "a\nlonger line", "fontSize": 20},
        {"type": "ellipse", "id": "e-label", "x": 0, "y": 0, "width": 10,
         "height": 10, "label": {"text": "x", "fontSize": 20}},
        {"type": "line", "x": 0, "y": 0, "points": [[0, 0], [3, 4]]},
    ]}  # fmt: skip
    elements = json.loads(excalidraw_file(skeleton))["elements"]
    ids = [e["id"] for e in elements]
    assert len(ids) == len(set(ids)) == 4
    assert elements[0]["height"] == 2 * 20 * 1.25
    assert elements[3]["width"] == 3 and elements[3]["endArrowhead"] is None


@pytest.mark.parametrize(
    "ask",
    [
        {"version": 1},  # no base_version: a stale history must not restore blindly
        {"version": True, "base_version": 1},
        {"version": "1", "base_version": 1},
        {"version": 10**30, "base_version": 1},
        {"version": 0, "base_version": 1},
        {"version": -1, "base_version": 1},
        {"version": 1, "base_version": 1.0},
    ],
)
def test_restore_takes_only_sensible_version_numbers(board, ask):
    client, url, _ = board
    assert client.post(f"{url}/restore", json=ask).status_code == 422


def nested(depth: int) -> dict:
    deep: dict = {}
    for _ in range(depth):
        deep = {"d": deep}
    return deep


@pytest.mark.parametrize(
    "body",
    [
        # stored, it could never be served again (serialisers have depth limits)
        json.dumps(
            {
                "base_version": 1,
                "scene": {
                    "elements": [
                        {
                            "type": "text",
                            "x": 0,
                            "y": 0,
                            "text": "t",
                            "customData": nested(255),
                        }
                    ]
                },
            }
        ).encode(),  # fmt: skip
        b'{"base_version": 1, "scene": ' + b"[" * 100_000 + b"]" * 100_000 + b"}",
        b'{"base_version": 1, "scene": {"elements": [{"type": "text", "x": '
        + b"9" * 400
        + b', "y": 0}]}}',
        b'{"base_version": 1, "scene": {"elements": [], "n": ' + b"9" * 5000 + b"}}",
        rb'{"base_version": 1, "scene": {"elements": [{"type": "text", "x": 0, "y": 0,'
        rb' "text": "t", "customData": {"n": "\udc00"}}]}}',
        rb'{"base_version": 1, "scene": {"elements": [{"type": "text", "x": 0, "y": 0,'
        rb' "text": "half \ud800 a pair"}]}}',
        rb'{"base_version": 1, "scene": {"elements": [], "\udc00": 1}}',
    ],
    ids=[
        "deep-custom-data",
        "deep-body",
        "400-digit-x",
        "5000-digit-int",
        "surrogate-custom-data",
        "surrogate-text",
        "surrogate-key",
    ],  # fmt: skip
)
def test_hostile_bodies_are_422_and_the_drawing_still_serves(board, body):
    client, url, _ = board
    response = client.put(url, content=body)
    assert response.status_code == 422, response.text
    assert client.get(url).status_code == 200


def test_a_scene_as_deep_as_allowed_is_saved_and_served(board):
    client, url, _ = board
    element = {"type": "text", "x": 0, "y": 0, "text": "t", "customData": nested(27)}
    put = client.put(url, json={"base_version": 1, "scene": {"elements": [element]}})
    assert put.status_code == 200, put.text
    assert client.get(url).json()["version"] == 2


def test_export_keeps_each_pages_drawing_of_the_same_photo(tmp_path):
    """One photo on two pages, with different drawings: each page's Markdown links
    to its own drawing in the shared files/ folder."""
    client = TestClient(create_app(tmp_path))
    image = jpeg(size=(800, 600))
    refs = []
    for words in ("first", "second"):
        files = [("file", ("board.jpg", image, "image/jpeg"))]
        data = {"id": new_ulid(), "text": f"{words} page"}
        refs.append(client.post("/api/captures", data=data, files=files).json())
    page = client.get(f"/api/pages/{refs[0]['page_id']}").json()
    sha = page["captures"][0]["blobs"][0]["sha256"]
    for ref, words in zip(refs, ("ONE", "TWO"), strict=True):
        url = f"/api/captures/{ref['capture_id']}/photos/{sha}/drawing"
        put = client.put(url, json={"base_version": None, "scene": scene(words)})
        assert put.status_code == 200
    out = tmp_path / "export"
    assert export(Store(tmp_path), out) == 2
    for ref, words in zip(refs, ("ONE", "TWO"), strict=True):
        md = (out / f"{ref['slug']}.md").read_text()
        link = md.split("[Drawing of")[1].split("(files/")[1].split(")")[0]
        assert ref["capture_id"] in link
        drawing = json.loads((out / "files" / link).read_text())
        assert [e["text"] for e in drawing["elements"]] == [words]


def test_made_ids_never_collide_with_the_models():
    skeleton = {"format": "skeleton", "elements": [
        {"type": "rectangle", "id": "a", "x": 0, "y": 0, "width": 9, "height": 9,
         "label": {"text": "x", "fontSize": 20}},
        {"type": "text", "id": "a-label", "x": 0, "y": 0, "text": "t"},
        {"type": "text", "id": "e3", "x": 0, "y": 0, "text": "u"},
        {"type": "line", "x": 0, "y": 0, "points": [[0, 0], [1, 1]]},
    ]}  # fmt: skip
    ids = [e["id"] for e in json.loads(excalidraw_file(skeleton))["elements"]]
    assert len(ids) == len(set(ids)) == 5 and "a-label" in ids


def test_a_legacy_row_that_cannot_be_encoded_is_still_served(board, tmp_path):
    """A row stored before lone surrogates were refused: replaced, never a 500."""
    client, url, ref = board
    data = '{"format": "scene", "elements": [{"type": "text", "x": 0, "y": 0,'
    data += ' "text": "bad \\udc00 half"}]}'
    with closing(connect(tmp_path / "scrap.db")) as conn:
        cid, sha = url.split("/")[3], url.split("/")[5]
        conn.execute(
            "INSERT INTO derived (capture_id, source_sha256, kind, version, producer,"
            " author, data, created_at) VALUES (?, ?, 'excalidraw', 2, 'human', 'me',"
            " ?, '2099-01-01T00:00:00.000Z')",
            (cid, sha, data),
        )
    got = client.get(url)
    assert got.status_code == 200
    assert got.json()["data"]["elements"][0]["text"] == "bad ? half"
    assert client.get(f"/api/pages/{ref['page_id']}/download").status_code == 200


def test_the_5_mb_cap_counts_compact_json():
    """Exactly 5 MiB as the editor sends it (compact) is kept; spaced JSON of the
    same scene is bigger, so measuring that way would refuse it."""
    element = {"type": "text", "x": 0, "y": 0, "text": ""}
    shell = {"elements": [element]}
    pad = SCENE_BYTES - len(json.dumps(shell, separators=(",", ":")))
    element["text"] = "é" * (pad // 2) + "x" * (pad % 2)  # 2 bytes each in UTF-8
    compact = json.dumps(shell, separators=(",", ":"), ensure_ascii=False)
    assert len(compact.encode()) == SCENE_BYTES
    assert sanitise.scene(shell)["elements"][0]["text"] == element["text"]
    element["text"] += "x"
    with pytest.raises(InvalidError, match="5 MB"):
        sanitise.scene(shell)
