"""Reconciling the site with scrap's kept copies (docs/reference/public-site.md,
"Reconciling"), and the derived units built from them alone: home, the tag pages,
the Pagefind index and the assets."""

import gzip
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from publishhelp import WEB, Site, configure, page
from scrap.app import create_app
from scrap.publish import derived, digest, tag_key
from scrap.publish.kept import Kept
from scrap.store import new_ulid

CORPUS = json.loads((Path(__file__).parent / "data" / "katex_corpus.json").read_text())


@pytest.fixture
def site(tmp_path, monkeypatch):
    running = Site(tmp_path / "site")
    configure(monkeypatch, tmp_path, running)
    yield running
    running.stop()


@pytest.fixture
def app(tmp_path, site):
    return create_app(tmp_path / "data")


@pytest.fixture
def client(app):
    return TestClient(app)


def published(client, text: str, body: str, tags=("work",), maths=False) -> dict:
    ref = client.post("/api/captures", json={"id": new_ulid(), "text": text}).json()
    p = client.patch(f"/api/pages/{ref['slug']}",
                     json={"tags": list(tags), "public": True}).json()  # fmt: skip
    r = client.put(f"/api/pages/{p['slug']}/published", json={
        "html": page(body, p["title"], maths), "base_rev": p["rev"],
    })  # fmt: skip
    assert r.status_code == 200, r.text
    return p


def kept(app) -> Kept:
    return app.state.publisher.kept


def test_an_emptied_site_is_refilled(client, app, site, tmp_path, monkeypatch):
    a = published(client, "A\nx", "<p>alpha</p>")
    b = published(client, "B\ny", "<p>beta</p>", tags=("work", "home"))
    before = site.units()
    site.stop()  # the pod restarts with an empty emptyDir
    fresh = Site(tmp_path / "fresh")
    try:
        configure(monkeypatch, tmp_path, fresh)
        assert fresh.units() == {}
        app.state.publisher.reconcile()
        after = fresh.units()
        assert set(after) == {
            f"p/{a['slug']}", f"p/{b['slug']}", "home", "pagefind", "assets",
            f"t/{tag_key('work')}", f"t/{tag_key('home')}",
        }  # fmt: skip
        assert {u: v["digest"] for u, v in after.items()} == {
            u: v["digest"] for u, v in before.items() if u in after
        }
        assert fresh.file(f"p/{a['slug']}", "index.html") == site.file(
            f"p/{a['slug']}", "index.html"
        )
        assert app.state.publisher.last["ok"] is True
    finally:
        fresh.stop()


def test_reconcile_prunes_pages_no_longer_public(client, app, site):
    a = published(client, "A\nx", "<p>alpha</p>")
    keep = published(client, "B\ny", "<p>beta</p>")
    store = app.state.publisher.store
    with store.connect() as conn:  # behind the publisher's back
        conn.execute("UPDATE page SET public = 0 WHERE id = ?", (a["id"],))
        conn.commit()
    app.state.publisher.reconcile()
    assert f"p/{a['slug']}" not in site.units()
    assert f"p/{keep['slug']}" in site.units()
    assert kept(app).slugs() == [keep["slug"]]
    assert f'/p/{a["slug"]}"' not in site.file("home", "index.html").decode()


def test_a_damaged_copy_is_pruned(client, app, site):
    a = published(client, "A\nx", "<p>alpha</p>")
    copy = kept(app).root / "p" / a["slug"] / "index.html"
    copy.write_bytes(copy.read_bytes() + b"<!-- changed on disk -->")
    app.state.publisher.reconcile()
    assert f"p/{a['slug']}" not in site.units()
    assert kept(app).slugs() == []
    # the API says so: it comes back on the next Refresh all
    got = client.get(f"/api/pages/{a['slug']}").json()
    assert got["public"] is True and got["published_at"] is None


def test_strays_are_synced_away_and_a_changed_unit_pushed_again(client, app, site):
    a = published(client, "A\nx", "<p>alpha</p>")
    from publishhelp import TOKEN
    from scrap.publish.client import Receiver

    with Receiver(site.url, TOKEN) as r:
        r.put("p/stray", {"index.html": b"<p>stray</p>"})
        r.put(f"p/{a['slug']}", {"index.html": b"<p>someone else's</p>"})
    app.state.publisher.reconcile()
    units = site.units()
    assert "p/stray" not in units
    assert units[f"p/{a['slug']}"]["digest"] == kept(app).digest(f"p/{a['slug']}")


def test_derived_units_are_deterministic_and_from_the_copies_alone(client, app):
    published(client, "A\nx", "<p>alpha</p>", tags=("work", "personal/family"))
    published(client, "B\ny", "<p>beta</p>")
    one = derived.build(kept(app), WEB / "public")
    two = derived.build(kept(app), WEB / "public")
    assert {u: digest(f) for u, f in one.items()} == {
        u: digest(f) for u, f in two.items()
    }
    assert set(one) == {
        "home", "pagefind", "assets", f"t/{tag_key('work')}",
        f"t/{tag_key('personal/family')}",
    }  # fmt: skip
    assert sorted(one["home"]) == ["404.html", "index.html", "tags.html"]
    home = one["home"]["index.html"].decode()
    assert home.index(">B<") < home.index(">A<")  # newest published first
    assert "/pagefind/scrap-search.js" in home and "<script>" not in home
    tags = one["home"]["tags.html"].decode()
    assert "personal/family" in tags and f"/t/{tag_key('personal/family')}" in tags
    assert "<script" not in one["home"]["404.html"].decode()
    assert sorted(one["assets"]) == [
        "fonts/KaTeX_Main-Regular.woff2", "katex.css", "page.css", "pagefind-ui.css",
    ]  # fmt: skip
    assert not any(n.endswith(".css") for n in one["pagefind"])  # CSS only in assets
    assert "scrap-search.js" in one["pagefind"]


def fragments(units: dict) -> list[dict]:
    out = []
    for name, data in units["pagefind"].items():
        if name.endswith(".pf_fragment"):
            raw = gzip.decompress(data)
            assert raw.startswith(b"pagefind_dcd")
            out.append(json.loads(raw[len(b"pagefind_dcd") :]))
    return out


def test_search_holds_the_public_pages_text_and_tex_not_a_private_page(client, app):
    case = next(c for c in CORPUS["cases"] if c["tex"].startswith("\\frac"))
    published(client, "Zebra notes\nx", f"<p>zebras graze {case['html']}</p>",
              maths=True)  # fmt: skip
    client.post("/api/captures", json={"id": new_ulid(),
                                       "text": "Secret\nunicorns roam"})  # fmt: skip
    found = fragments(derived.build(kept(app), WEB / "public"))
    assert [f["url"] for f in found] == ["/p/zebra-notes"]
    content = found[0]["content"]
    assert "zebras graze" in content and "\\frac{a}{b}" in content
    assert "unicorns" not in json.dumps(found)
    assert found[0]["meta"]["title"] == "Zebra notes"


def test_a_tag_unit_goes_when_no_public_page_has_the_tag(client, app, site):
    p = published(client, "A\nx", "<p>alpha</p>", tags=("rare",))
    assert f"t/{tag_key('rare')}" in site.units()
    client.patch(f"/api/pages/{p['slug']}", json={"public": False})
    assert f"t/{tag_key('rare')}" not in site.units()
    assert "rare" not in site.file("home", "tags.html").decode()
