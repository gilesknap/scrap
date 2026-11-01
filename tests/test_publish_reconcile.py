"""Reconciling the site with scrap's kept copies (docs/reference/public-site.md,
"Reconciling"), and the derived units built from them alone: home, the tag pages,
the Pagefind index and the assets."""

import gzip
import json
import os
import shlex
import sys
import time
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
        "confirmed": True,
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
    """A copy is read, and its damage found, only when the site needs it pushed."""
    from publishhelp import TOKEN
    from scrap.publish.client import Receiver

    a = published(client, "A\nx", "<p>alpha</p>")
    copy = kept(app).root / "p" / a["slug"] / "index.html"
    copy.write_bytes(copy.read_bytes() + b"<!-- changed on disk -->")
    app.state.publisher.reconcile()
    assert kept(app).slugs() == [a["slug"]]  # the site has it as pushed: not read
    with Receiver(site.url, TOKEN) as r:
        r.delete(f"p/{a['slug']}")  # the site lost it
    app.state.publisher.reconcile()
    assert f"p/{a['slug']}" not in site.units()
    assert kept(app).slugs() == []
    # the API says so: it comes back on the next Refresh all
    got = client.get(f"/api/pages/{a['slug']}").json()
    assert got["public"] is True and got["published_at"] is None


def test_reconcile_reads_no_copy_the_site_holds_as_pushed(client, app, site,
                                                          monkeypatch):  # fmt: skip
    published(client, "A\nx", "<p>alpha</p>")
    b = published(client, "B\ny", "<p>beta</p>")
    read = []
    real = Kept.files
    monkeypatch.setattr(Kept, "files", lambda self, slug: read.append(slug)
                        or real(self, slug))  # fmt: skip
    app.state.publisher.reconcile()
    assert read == [] and app.state.publisher.last["ok"] is True
    from publishhelp import TOKEN
    from scrap.publish.client import Receiver

    with Receiver(site.url, TOKEN) as r:
        r.delete(f"p/{b['slug']}")
    app.state.publisher.reconcile()
    assert read == [b["slug"]] and f"p/{b['slug']}" in site.units()


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


ICON_LINKS = (
    '<link rel="icon" href="/assets/icon.svg" type="image/svg+xml">\n'
    '<link rel="apple-touch-icon" href="/assets/icon-192.png">\n'
)


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
    # the 404 runs only the theme and width switches (#519), as every page does
    missing = one["home"]["404.html"].decode()
    assert missing.count("<script") == 1
    assert '<script src="/assets/prefs.js" defer blocking="render"></script>' in missing
    # every page of the site names scrap's icons (#527)
    for html in (home, tags, missing,
                 one[f"t/{tag_key('work')}"]["index.html"].decode()):  # fmt: skip
        assert ICON_LINKS in html
    assert sorted(one["assets"]) == [
        "fonts/KaTeX_Main-Regular.woff2", "icon-192.png", "icon.svg", "katex.css",
        "page.css", "pagefind-ui.css", "prefs.js",
    ]  # fmt: skip
    assert one["assets"]["icon.svg"] == (WEB / "public" / "icon.svg").read_bytes()
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


def test_search_is_built_once_for_the_same_records(client, app, monkeypatch):
    from scrap.publish import search

    published(client, "A\nx", "<p>alpha</p>")
    calls = []
    real = search._run

    def counted(records, timeout):
        calls.append(len(records))
        return real(records, timeout)

    monkeypatch.setattr(search, "_run", counted)
    one = derived.build(kept(app), WEB / "public")
    assert calls == []  # the publish's own build is cached
    published(client, "B\ny", "<p>beta</p>")
    assert calls == [2]  # new records: built again
    two = derived.build(kept(app), WEB / "public")
    assert calls == [2] and two["pagefind"] != one["pagefind"]


def test_a_pagefind_failure_keeps_the_last_index(client, app, site, monkeypatch):
    from scrap.publish import search

    a = published(client, "A\nx", "<p>alpha</p>")
    before = site.units()

    def broken(records, out):
        return [sys.executable, "-c", "import sys; sys.exit('injected')"]

    monkeypatch.setattr(search, "_command", broken)
    ref = client.post("/api/captures", json={"id": new_ulid(), "text": "B\ny"}).json()
    b = client.patch(f"/api/pages/{ref['slug']}", json={"public": True}).json()
    r = client.put(f"/api/pages/{b['slug']}/published", json={
        "html": page("<p>beta</p>", b["title"]), "base_rev": b["rev"],
        "confirmed": True,
    })  # fmt: skip
    assert r.status_code == 200 and r.json()["derived"] == "pending", r.text
    units = site.units()
    assert f"p/{b['slug']}" in units  # the page went out
    assert units["pagefind"]["digest"] == before["pagefind"]["digest"]
    assert units["assets"]["digest"] == before["assets"]["digest"]  # cached CSS
    assert f'/p/{b["slug"]}"' in site.file("home", "index.html").decode()
    assert client.post("/api/public/rebuild").json()["derived"] == "pending"
    app.state.publisher.reconcile()  # keeps the old index, says so
    assert "pagefind" in site.units()
    last = app.state.publisher.last
    assert last["ok"] is False and "search index" in last["error"]
    out = client.patch(f"/api/pages/{a['slug']}", json={"public": False}).json()
    assert out["unpublish"] == "pending"  # the page is gone; search is not rebuilt
    assert f"p/{a['slug']}" not in site.units()
    monkeypatch.undo()
    configure(monkeypatch, app.state.publisher.store.dir.parent, site)
    app.state.publisher.reconcile()
    assert app.state.publisher.last["ok"] is True
    assert site.units()["pagefind"]["digest"] != before["pagefind"]["digest"]


def _gone(pid: int) -> bool:
    """Whether a process has ended (gone, or a zombie waiting to be reaped)."""
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except OSError:
        return True
    return state == "Z"


@pytest.mark.skipif(sys.platform != "linux", reason="reads /proc")
def test_a_pagefind_build_that_hangs_times_out_and_leaves_nothing_running(
    client, app, monkeypatch, tmp_path
):
    """A build that hangs is given up after TIMEOUT, and its process group is killed:
    what it started (Pagefind's service, here a sleep) does not outlive it."""
    from scrap.publish import search

    published(client, "A\nx", "<p>alpha</p>")
    pids = tmp_path / "pids"
    hang = (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen(['sleep', '60'])\n"
        f"open({str(pids)!r}, 'w').write(str(child.pid))\n"
        "time.sleep(60)\n"
    )
    monkeypatch.setattr(
        search, "_command", lambda records, out: [sys.executable, "-c", hang]
    )
    monkeypatch.setattr(search, "TIMEOUT", 1.5)
    published(client, "B\ny", "<p>beta</p>")  # records changed: built again
    start = time.monotonic()
    units = derived.build(kept(app), WEB / "public")
    assert time.monotonic() - start < 10
    assert "pagefind" not in units and derived.pending(units)
    child = int(pids.read_text())
    deadline = time.monotonic() + 5
    while not _gone(child):
        assert time.monotonic() < deadline, "the build's child outlived it"
        time.sleep(0.05)


def _stat(pid: int) -> list[str] | None:
    """A process's /proc stat fields from its state on (field 3), else None."""
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    except OSError:
        return None


@pytest.fixture
def services(tmp_path, monkeypatch):
    """The Pagefind services this test's builds start, as (pid, process group, start
    time). Pagefind runs through a wrapper (PAGEFIND_BINARY_PATH, which the build's
    process inherits) that logs its own stat line, then execs the pinned binary. Only
    this test's builds use it, so a parallel test's builds (xdist) are not counted."""
    from pagefind.service import get_executable

    real = get_executable()
    assert real is not None
    log = tmp_path / "services"
    wrapper = tmp_path / "pagefind-wrapper"
    wrapper.write_text(
        "#!/bin/sh\n"
        "read -r stat < /proc/$$/stat\n"
        f'echo "$stat" >> {shlex.quote(str(log))}\n'
        f'exec {shlex.quote(str(real))} "$@"\n'
    )
    wrapper.chmod(0o755)
    monkeypatch.setenv("PAGEFIND_BINARY_PATH", str(wrapper))

    def started() -> list[tuple[int, int, str]]:
        lines = log.read_text().splitlines() if log.exists() else []
        out = []
        for line in lines:
            fields = line.rsplit(")", 1)[1].split()
            out.append((int(line.split()[0]), int(fields[2]), fields[19]))
        return out

    return started


def _ticks() -> int:
    """Now, in the clock ticks since boot that /proc's start times use."""
    return int(time.clock_gettime(time.CLOCK_BOOTTIME) * os.sysconf("SC_CLK_TCK")) + 1


def _left(started: list[tuple[int, int, str]], within: float = 10) -> set[int]:
    """The processes of started, and of their process groups, still running (not a
    zombie) after up to within seconds: polled, so empty as soon as all have ended.
    Call it once the build has returned: a group member started later is a reused
    group id (another build's), not this one's."""
    groups = {group for _, group, _ in started}
    ended = _ticks()
    deadline = time.monotonic() + within
    while True:
        alive = set()
        for pid, _, since in started:  # the same process: not a reused pid
            if (f := _stat(pid)) and f[0] != "Z" and f[19] == since:
                alive.add(pid)
        for d in Path("/proc").iterdir():
            if d.name.isdigit() and (f := _stat(int(d.name))):
                if f[0] != "Z" and int(f[2]) in groups and int(f[19]) <= ended:
                    alive.add(int(d.name))
        if not alive or time.monotonic() > deadline:
            return alive
        time.sleep(0.05)


@pytest.mark.skipif(sys.platform != "linux", reason="reads /proc")
def test_the_real_pagefind_build_leaves_nothing_running(tmp_path, services):
    """A real build (the pinned binary) ends with its Pagefind service, and anything
    else in its process group, gone."""
    from scrap.publish import search

    unit, css = search.build_index([("/p/a", "A", "alpha words")], tmp_path / "cache")
    assert "pagefind-entry.json" in unit and css
    started = services()
    assert len(started) == 1  # the build did run the real service
    assert _left(started) == set()


@pytest.mark.skipif(sys.platform != "linux", reason="reads /proc")
def test_a_real_build_that_dies_leaves_no_pagefind_running(
    tmp_path, services, monkeypatch
):
    """A build that dies with the real Pagefind service running (its stdin held open
    by a child, so it does not see end of file and stop by itself) fails, and its
    process group is killed: the service does not outlive it."""
    from scrap.publish import search

    die = (
        "import asyncio, os, subprocess\n"
        "from pagefind.index import PagefindIndex\n"
        "async def main():\n"
        "    async with PagefindIndex() as index:\n"
        "        await index.add_custom_record(url='/p/a', content='alpha',"
        " language='en')\n"
        "        stdin = index._service._backend.stdin.get_extra_info('pipe')\n"
        "        quiet = subprocess.DEVNULL\n"
        "        subprocess.Popen(['sleep', '60'], pass_fds=[stdin.fileno()],\n"
        "                         stdout=quiet, stderr=quiet)\n"
        "        os._exit(3)  # silent: any other failure says what it was\n"
        "asyncio.run(main())\n"
    )
    monkeypatch.setattr(
        search, "_command", lambda records, out: [sys.executable, "-c", die]
    )
    with pytest.raises(search.SearchError, match="^Pagefind failed: no detail$"):
        search.build_index([("/p/a", "A", "alpha words")])
    started = services()
    assert len(started) == 1
    assert _left(started) == set()


def test_started_with_the_receiver_down_it_retries_soon(tmp_path, site, monkeypatch):
    """The receiver may be starting too: a failed reconcile is retried after
    RETRY_FIRST seconds (here a moment), doubling, not after the 10 minute period."""
    from scrap.publish import Publisher

    configure(monkeypatch, tmp_path, None)  # nobody listens yet
    publisher = Publisher(create_app(tmp_path / "data").state.publisher.store)
    publisher.start(every=600, retry=0.2)
    try:
        deadline = time.monotonic() + 10
        while publisher.last["ok"] is not False:
            assert time.monotonic() < deadline
            time.sleep(0.02)
        assert "unreachable" in publisher.last["error"]
        configure(monkeypatch, tmp_path, site)  # the receiver is up
        while publisher.last["ok"] is not True:
            assert time.monotonic() < deadline, publisher.last
            time.sleep(0.02)
        assert {"home", "pagefind", "assets"} <= set(site.units())
    finally:
        publisher.stop()


def test_dates_show_as_the_pwa_writes_them_and_search_has_a_label(client, app):
    import re

    from scrap.publish.templates import shown_date

    p = published(client, "A\nx", "<p>alpha</p>")
    when = kept(app).meta(p["slug"])["published_at"]  # type: ignore[index]
    units = derived.build(kept(app), WEB / "public")
    want = f'<time class="when" datetime="{when}">{shown_date(when)}</time>'
    assert re.fullmatch(r"[1-9][0-9]? [A-Z][a-z]{2} [0-9]{4}", shown_date(when))
    for html in (units["home"]["index.html"], units["home"]["tags.html"],
                 units[f"t/{tag_key('work')}"]["index.html"]):  # fmt: skip
        assert want in html.decode()
    home = units["home"]["index.html"].decode()
    assert '<h2 class="site-search-label">Search</h2>\n<div id="search"' in home
