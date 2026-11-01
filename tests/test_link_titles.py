"""A page link with no label shows its page's title (#508): the page's titles for the
PWA, the write-up's, downloads and exports."""

import io
import zipfile
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from scrap import export as export_module
from scrap.app import create_app
from scrap.store import topics, writeups
from scrap.store.db import connect
from scrap.store.helpers import new_ulid, now


@pytest.fixture
def data(tmp_path):
    return tmp_path / "data"


@pytest.fixture
def client(data):
    return TestClient(create_app(data))


def add(client, text, **extra):
    r = client.post("/api/captures", json={"id": new_ulid(), "text": text, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def page(client, ref):
    return client.get(f"/api/pages/{ref['page_id']}").json()


def rename(client, ref, title):
    p = page(client, ref)
    r = client.patch(
        f"/api/pages/{ref['page_id']}", json={"base_rev": p["rev"], "title": title}
    )
    assert r.is_success, r.text


@pytest.fixture
def linked(client):
    """Two pages to link to, and one in the trash."""
    a = add(client, "Front border in flower\nroses")
    b = add(client, "Back lawn\ngrass")
    gone = add(client, "Gone page\nbye")
    assert client.delete(f"/api/pages/{gone['page_id']}").status_code == 204
    return a, b, gone


def test_the_page_has_the_titles_of_the_pages_it_links_to(client, linked, monkeypatch):
    a, b, gone = linked
    monkeypatch.setenv("SCRAP_PUBLIC_URL", "https://scrap.example/")
    text = (
        f"Index\n- [[{a['slug']}]]\n- [[{a['slug']}#roses|Roses]]\n"
        f"- https://scrap.example/p/{b['slug']}\n"
        f"- [[{gone['slug']}]] [[no-such-page]]\n"
        "`[[in-code]]`"
    )
    index = add(client, text)
    titles = page(client, index)["titles"]
    assert titles == {a["slug"]: "Front border in flower", b["slug"]: "Back lawn"}
    assert page(client, add(client, "No links\nat all"))["titles"] == {}


def test_a_page_renamed_since_shows_its_current_title(client, linked):
    a, *_ = linked
    index = add(client, f"Index\nsee [[{a['slug']}]]")
    rename(client, a, "Front border, summer")
    assert page(client, index)["titles"] == {a["slug"]: "Front border, summer"}
    text = client.get(f"/api/pages/{index['page_id']}/download").text
    assert f"see [[{a['slug']}|Front border, summer]]" in text


def topic(data, text: str, body: str = "") -> tuple[str, str]:
    """A topic page (its notes body) with a synthesis of text: its id and slug."""
    with closing(connect(data / "scrap.db")) as conn:
        stamp = now()
        t = topics.create(conn, "Garden", "garden", "garden-topic", "m", stamp)
        assert t
        conn.execute("UPDATE page SET body = ? WHERE id = ?", (body, t))
        writeups.put(
            conn, t, stamp, producer="m", run_id=None, prompt_version="1",
            summary="Lead", text=text, guidance=None,
        )  # fmt: skip
        conn.commit()
    return t, "garden-topic"


def test_the_write_up_has_the_titles_of_the_pages_it_links_to(client, data, linked):
    a, b, gone = linked
    t, _ = topic(data, f"See [[{a['slug']}]] and [[{gone['slug']}]].")
    current = client.get(f"/api/pages/{t}").json()["writeup"]["current"]
    assert current["links"] == [a["slug"]]
    assert current["titles"] == {a["slug"]: "Front border in flower"}


def test_download_shows_titles_keeps_labels_and_dangling_links(
    client, linked, monkeypatch
):
    a, _, gone = linked
    slug = a["slug"]
    text = (
        f"Links\n[[{slug}]] [[{slug}|my words]] [[{gone['slug']}]] [[no-page#x]]\n\n"
        f"| a |\n| - |\n| [[{slug}]] |"
    )
    ref = add(client, text)
    got = client.get(f"/api/pages/{ref['page_id']}/download").text
    assert (
        f"[[{slug}|Front border in flower]] [[{slug}|my words]]"
        f" [[{gone['slug']}]] [[no-page#x]]" in got
    )
    assert f"| [[{slug}\\|Front border in flower]] |" in got
    monkeypatch.setenv("SCRAP_PUBLIC_URL", "https://scrap.example/")
    got = client.get(f"/api/pages/{ref['page_id']}/download").text
    there = "https://scrap.example/p/"
    assert (
        f"[Front border in flower]({there}{slug}) [my words]({there}{slug})"
        f" [{gone['slug']}]({there}{gone['slug']}) [no-page#x]({there}no-page)" in got
    )


def test_export_keeps_the_body_as_typed_and_titles_the_sidecar(client, data, linked):
    a, *_ = linked
    slug = a["slug"]
    t, tslug = topic(
        data,
        f"About [[{slug}]], [[{slug}|in words]] and [[no-page]].",
        f"see [[{slug}]]",
    )
    zf = zipfile.ZipFile(io.BytesIO(client.get("/api/store/download").content))
    assert f"see [[{slug}]]" in zf.read(f"{tslug}.md").decode()  # as typed: an import
    sidecar = zf.read(f"_claude/{tslug}.md").decode()
    assert (
        f"About [Front border in flower](../{slug}.md), [in words](../{slug}.md)"
        " and [no-page](../no-page.md)." in sidecar
    )


def test_sidecar_links_show_titles():
    titles = {"a": "A [page]"}
    assert export_module._sidecar_links("[[a]] [[a#h]] [[a|x]] [[b]]", titles) == (
        "[A (page)](../a.md) [A (page)](../a.md) [x](../a.md) [b](../b.md)"
    )
