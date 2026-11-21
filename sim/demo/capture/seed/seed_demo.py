"""Seed a scratch scrap server with sample pages for the design sim."""

import io
import json
import random
import sys
import time
import urllib.request
import uuid

from PIL import Image, ImageDraw, ImageFilter, ImageFont

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
random.seed(7)

CROCK = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ulid(ms):
    t = "".join(CROCK[(ms >> (5 * i)) & 31] for i in range(9, -1, -1))
    return t + "".join(random.choice(CROCK) for _ in range(16))


def req(method, path, body=None, ctype="application/json"):
    data = body if isinstance(body, bytes) else json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    if data is not None:
        r.add_header("Content-Type", ctype)
    with OPENER.open(r) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else None


def font(size):
    for f in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            pass
    return ImageFont.load_default()


def jpeg(img):
    b = io.BytesIO()
    img.save(b, "JPEG", quality=78)
    return b.getvalue()


def whiteboard():
    w, h = 1600, 1100
    img = Image.new("RGB", (w, h), (226, 228, 224))
    d = ImageDraw.Draw(img)
    d.rectangle([60, 50, w - 60, h - 50], fill=(246, 247, 243), outline=(150, 150, 150), width=14)
    blue, red, green = (30, 60, 160), (180, 40, 40), (30, 120, 60)
    f = font(46)
    boxes = [(180, 200, "PWA"), (680, 200, "FastAPI"), (1180, 200, "SQLite"), (680, 650, "Ingest")]
    for x, y, t in boxes:
        d.rounded_rectangle([x, y, x + 300, y + 150], 24, outline=blue, width=7)
        d.text((x + 40, y + 48), t, fill=blue, font=f)
    for (x1, y1), (x2, y2) in [((480, 275), (680, 275)), ((980, 275), (1180, 275)), ((830, 350), (830, 650))]:
        d.line([x1, y1, x2, y2], fill=red, width=7)
        d.polygon([(x2, y2), (x2 - 24, y2 - 14), (x2 - 24, y2 + 14)] if y1 == y2 else [(x2, y2), (x2 - 14, y2 - 24), (x2 + 14, y2 - 24)], fill=red)
    d.text((1040, 720), "Claude: read,\nsummarise, redraw", fill=green, font=font(38))
    d.text((180, 900), "v0: one process, no login", fill=(40, 40, 40), font=font(40))
    return jpeg(img.filter(ImageFilter.GaussianBlur(1.2)).rotate(-1.5, fillcolor=(90, 90, 90)))


def fence():
    w, h = 1200, 900
    img = Image.new("RGB", (w, h), (120, 170, 90))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w, 260], fill=(170, 200, 230))
    for i in range(0, w, 110):
        tone = random.randint(-15, 15)
        d.rectangle([i + 8, 220, i + 98, 760], fill=(130 + tone, 90 + tone, 55 + tone))
    d.polygon([(560, 220), (650, 240), (700, 760), (600, 760)], fill=(90, 120, 70))
    return jpeg(img.filter(ImageFilter.GaussianBlur(2)))


def receipt():
    w, h = 900, 1300
    img = Image.new("RGB", (w, h), (80, 70, 60))
    d = ImageDraw.Draw(img)
    d.rectangle([150, 60, 750, 1240], fill=(250, 248, 240))
    f = font(30)
    lines = ["CAVERSHAM HARDWARE", "", "Fence panel 6x5   34.99", "Post 2.4m        12.50", "Screws x100       4.20",
             "Creosote 5L      18.00", "", "TOTAL            69.69", "", "VISA ****  21/10/2026"]
    for i, t in enumerate(lines):
        d.text((190, 120 + i * 60), t, fill=(30, 30, 30), font=f)
    return jpeg(img.rotate(3, fillcolor=(80, 70, 60)).filter(ImageFilter.GaussianBlur(0.8)))


def garden():
    w, h = 1400, 1000
    img = Image.new("RGB", (w, h), (90, 140, 70))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w, 330], fill=(185, 210, 235))
    for _ in range(140):
        x, y, r = random.randint(0, w), random.randint(380, h), random.randint(10, 40)
        c = random.choice([(220, 80, 90), (240, 200, 60), (250, 250, 250), (160, 90, 200)])
        d.ellipse([x - r, y - r, x + r, y + r], fill=c)
    return jpeg(img.filter(ImageFilter.GaussianBlur(3)))


now = int(time.time() * 1000)
import datetime as _dt
DAYS = (_dt.date.today() - _dt.date(2026, 10, 21)).days
def shift(d):
    return (_dt.date.fromisoformat(d) + _dt.timedelta(days=DAYS)).isoformat() if d else d

step = [0]


def capture(kind=None, text=None, url=None, files=(), tags=(), due=None, priority=None, hours_ago=1):
    cid = ulid(now - int(hours_ago * 3600_000))
    created = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now / 1000 - hours_ago * 3600))
    fields = {"id": cid, "created_at": created}
    for k, v in (("kind", kind), ("text", text), ("url", url), ("due", shift(due)), ("priority", priority)):
        if v:
            fields[k] = v
    if not files:
        if tags:
            fields["tags"] = list(tags)
        return req("POST", "/api/captures", fields)
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for t in tags:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="tags"\r\n\r\n{t}\r\n'.encode())
    for name, blob in files:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
            f"Content-Type: image/jpeg\r\n\r\n".encode() + blob + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode())
    return req("POST", "/api/captures", b"".join(parts), f"multipart/form-data; boundary={boundary}")


def patch(page, **body):
    p = req("GET", f"/api/pages/{page['page_id']}")
    if "title" in body or "body" in body:
        body["base_rev"] = p["rev"]
    return req("PATCH", f"/api/pages/{page['page_id']}", body)


DESIGN = """# scrap design notes

A running list of what the PWA should feel like. **Capture first**, read later.

## Principles

1. Quick capture never waits on an LLM.
2. Originals are always kept.
3. One tap for the common thing; the rest under *More*.

## Open questions

- [ ] Should Todos open on *Today* or *All*?
- [x] Recent searches under the empty search box
- [ ] A swipe to tick a todo off?

## The capture path

```mermaid
flowchart LR
  Phone -->|share| Queue[Offline queue]
  Queue --> API[/api/captures/]
  API --> DB[(SQLite)]
  DB --> Ingest -->|Claude| DB
```

| Screen  | Primary action | Secondary |
| ------- | -------------- | --------- |
| Capture | Save           | Photo, Kind |
| Todos   | New todo       | Filters |
| Page    | Edit           | Share, Trash |

Inline `code`, a [link to the docs](https://gilesknap.github.io/scrap) and a footnote.[^1]

> Chat is poor at showing images, so the PWA is where you look at things.

```python
def capture(text: str) -> Page:
    return store.save(text)
```

[^1]: Footnotes render at the end of the page.
"""

MEETING = """Weekly controls sync.

- K3s upgrade on the beamline cluster: **Thursday**, needs a freeze notice
- ibek 4.x: generic IOC rebuilds pass; two support modules still pin the old schema
- argocd-ioc-monitor: Keith wants the restart count on the summary row

Actions: write the freeze notice; chase the two support modules."""

SHORT = "Plant the tulip bulbs before the first frost. Move the rosemary somewhere sunnier."

LONG_TITLE = ("A very long title to check how rows, headers and toolbars cope when the text "
              "goes on and on well past the width of a phone screen")

pages = {}
pages["design"] = capture("note", DESIGN, tags=["scrap", "scrap/design"], hours_ago=2)
pages["meeting"] = capture("note", MEETING, tags=["work", "work/meetings", "epics"], hours_ago=20)
pages["garden"] = capture(None, SHORT, tags=["home", "garden"], hours_ago=50)


patch(pages["meeting"], title="Controls sync — 20 Oct")
patch(pages["design"], fields={"personal": False})
patch(pages["garden"], fields={"personal": True})

todo = [
    ("Renew car insurance", "2026-10-19", "high", ["home", "car"], 30),
    ("Call the plumber about the boiler", "2026-10-21", "high", ["home"], 26),
    ("Book the MOT", "2026-10-22", "medium", ["car"], 24),
    ("Review PR #125: page cap", "2026-10-26", None, ["work", "scrap"], 6),
    ("Order a spare IOC power supply", "2026-10-28", "low", ["work", "epics"], 40),
    ("Buy dog food", None, "low", ["home"], 3),
    ("Look at sqlite-vec 0.2 release notes", None, None, ["scrap"], 90),
]
for i, (title, due, pri, tags, ago) in enumerate(todo):
    pages[f"todo{i}"] = capture("todo", title, tags=tags, due=due, priority=pri, hours_ago=ago)

pages["done"] = capture("todo", "Send the gas safety certificate to the tenants", tags=["home"], due="2026-10-15", hours_ago=150)
patch(pages["done"], fields={"status": "done"})
pages["cancelled"] = capture("todo", "Cancel the old gym membership", tags=["home"], hours_ago=200)
patch(pages["cancelled"], fields={"status": "cancelled"})
pages["fence"] = capture("todo", "Fix the broken fence panel", files=[("IMG_2041.jpg", fence())], tags=["home", "garden"], due="2026-10-24", priority="medium", hours_ago=8)

pages["snoozed"] = capture("todo", "Clear the gutters", tags=["home"], due="2026-10-21", priority="medium", hours_ago=60)
patch(pages["snoozed"], snoozed_until=shift("2026-10-24"))
CAMPING = """Camping kit for the weekend

- [x] Tent and pegs
- [x] Sleeping bags
- [ ] Stove and gas
- [ ] Head torches
- [ ] First aid kit"""
pages["checklist"] = capture(None, CAMPING, tags=["home"], hours_ago=5)
RELEASE = """Release ibek 4.1

- [x] Bump the schema version
- [ ] Rebuild the generic IOCs
- [ ] Update the docs
- [ ] Tag and publish"""
pages["release"] = capture("todo", RELEASE, tags=["work", "epics"], due="2026-10-23", priority="high", hours_ago=7)

pages["read1"] =capture("consume", url="https://en.wikipedia.org/wiki/Integrated_information_theory", tags=["philosophy-of-mind"], hours_ago=12)
patch(pages["read1"], title="Integrated information theory")
pages["read2"] = capture("consume", url="https://www.anthropic.com/research", tags=["ai"], hours_ago=60)
patch(pages["read2"], title="Anthropic research")
pages["read3"] = capture("consume", "Blindsight by Peter Watts: recommended after Permutation City", tags=["books", "sf"], hours_ago=100)
patch(pages["read3"], title="Blindsight — Peter Watts", fields={"subtype": "read", "status": "done"})

pages["board"] = capture("whiteboard", files=[("whiteboard.jpg", whiteboard())], tags=["scrap", "scrap/design"], hours_ago=4)
patch(pages["board"], title="Architecture whiteboard")
pages["receipt"] = capture("document", files=[("receipt.jpg", receipt())], tags=["home", "receipts"], hours_ago=9)
patch(pages["receipt"], title="Hardware receipt — fence")
pages["photo"] = capture(None, "Front border in flower", files=[("IMG_2050.jpg", garden())], tags=["garden"], hours_ago=30)

# a drawing for the whiteboard, as if the user had drawn over it
b = req("GET", f"/api/pages/{pages['board']['page_id']}")
cap = b["captures"][0]
sha = cap["blobs"][0]["sha256"]


def el(i, type_, x, y, w, h, **kw):
    base = {"id": f"e{i}", "type": type_, "x": x, "y": y, "width": w, "height": h, "angle": 0,
            "strokeColor": "#1971c2", "backgroundColor": "transparent", "fillStyle": "solid",
            "strokeWidth": 2, "strokeStyle": "solid", "roughness": 1, "opacity": 100,
            "groupIds": [], "frameId": None, "roundness": {"type": 3}, "seed": 1000 + i,
            "version": 1, "versionNonce": 2000 + i, "isDeleted": False, "boundElements": None,
            "updated": 1, "link": None, "locked": False}
    base.update(kw)
    return base


def text(i, x, y, s, color="#1971c2", size=36):
    return el(i, "text", x, y, len(s) * size * 0.55, size * 1.25, text=s, originalText=s, fontSize=size,
              fontFamily=5, textAlign="left", verticalAlign="top", containerId=None, autoResize=True,
              lineHeight=1.25, strokeColor=color, roundness=None)


elements = []
for i, (x, y, t) in enumerate([(180, 200, "PWA"), (680, 200, "FastAPI"), (1180, 200, "SQLite"), (680, 650, "Ingest")]):
    elements.append(el(i, "rectangle", x, y, 300, 150))
    elements.append(text(10 + i, x + 40, y + 50, t))
for i, (x1, y1, x2, y2) in enumerate([(480, 275, 680, 275), (980, 275, 1180, 275), (830, 350, 830, 650)]):
    elements.append(el(20 + i, "arrow", x1, y1, x2 - x1, y2 - y1, points=[[0, 0], [x2 - x1, y2 - y1]],
                       strokeColor="#e03131", startArrowhead=None, endArrowhead="arrow", roundness={"type": 2},
                       lastCommittedPoint=None, startBinding=None, endBinding=None, elbowed=False))
elements.append(text(30, 1040, 720, "Claude: read, summarise, redraw", "#2f9e44", 30))
elements.append(text(31, 180, 900, "v0: one process, no login", "#1e1e1e", 34))
req("PUT", f"/api/captures/{cap['id']}/photos/{sha}/drawing",
    {"base_version": None, "scene": {"elements": elements, "appState": {"viewBackgroundColor": "#ffffff"}, "width": 1600, "height": 1100}})

# ---- the sim's mock pages (sim/mock.py), less the test-only ones
LATER = [
    ("The Dispossessed — Ursula K. Le Guin", "book", False, "An ambiguous utopia: the next one after Blindsight.", "https://en.wikipedia.org/wiki/The_Dispossessed", ["books", "sf"], 30),
    ("Piranesi — Susanna Clarke", "book", True, "Short, strange and lovely. Finished on the train.", "https://en.wikipedia.org/wiki/Piranesi_(novel)", ["books"], 400),
    ("Strangler Fig Application", "article", False, "For the importer rewrite: replace it a piece at a time.", "https://martinfowler.com/bliki/StranglerFigApplication.html", ["work"], 52),
    ("Arrival (2016)", "film", False, "Linguistics and time; the short story first?", "https://en.wikipedia.org/wiki/Arrival_(film)", ["films", "sf"], 75),
    ("Ex Machina (2014)", "film", True, "Rewatched: still the best Turing test on film.", "https://en.wikipedia.org/wiki/Ex_Machina_(film)", ["films", "ai"], 520),
    ("Severance — season 2", "tv", False, "Catch up before the spoilers do.", "https://en.wikipedia.org/wiki/Severance_(TV_series)", ["tv"], 20),
    ("But what is a neural network?", "video", False, "3Blue1Brown, chapter 1 of the deep learning series.", "https://www.youtube.com/watch?v=aircAruvnKk", ["ai"], 98),
    ("Mindscape — the hard problem", "podcast", False, "Sean Carroll on consciousness, for the walk to work.", "https://www.preposterousuniverse.com/podcast/", ["philosophy-of-mind"], 12),
    ("In Our Time — the measurement problem", "podcast", True, "Melvyn Bragg and three physicists on quantum measurement.", "https://www.bbc.co.uk/programmes/b006qykl", ["physics"], 300),
    ("In Rainbows — Radiohead", "music", False, "Play it through on the good speakers, start to end.", "https://en.wikipedia.org/wiki/In_Rainbows", ["music"], 140),
    ("Wingspan", "game", False, "Board game for the family at Christmas: 1 to 5 players.", "https://en.wikipedia.org/wiki/Wingspan_(board_game)", ["games"], 160),
    ("Outer Wilds", "game", False, "Space exploration in a 22-minute time loop. Go in knowing nothing.", "https://en.wikipedia.org/wiki/Outer_Wilds", ["games"], 210),
]
for p in (pages["read1"], pages["read2"]):
    patch(p, fields={"media_type": "article", "subtype": "read"})
patch(pages["read3"], fields={"media_type": "book"})
SUB = {"book": "read", "article": "read", "film": "watch", "tv": "watch", "video": "watch",
       "podcast": "listen", "music": "listen", "game": "play"}
for i, (title, medium, done, note, src, tags, ago) in enumerate(LATER):
    p = capture("consume", note, url=src, tags=tags, hours_ago=ago)
    patch(p, title=title, fields={"subtype": SUB[medium], "media_type": medium, "status": "done" if done else "open", "source": src})
    pages[f"later{i}"] = p
PEOPLE = [
    ("Marjorie Pell", ["person/family"], "Aunt Marjorie, in Whitby.\nmarjorie.pell@example.com · birthday 3 March"),
    ("Theo Pell", ["person/family"], "Cousin; climbs at the Reading wall on Thursdays.\ntheo@example.com"),
    ("Rosa Vantongeren", ["person/family"], "Sister-in-law. Vegetarian; allergic to walnuts.\nrosa.v@example.com"),
    ("Felix Pell", ["person/family", "person/work"], "Cousin, and now on the controls team too.\nfelix.pell@example.com"),
    ("Imogen Hartlow", ["person/work"], "Beamline scientist on I99; owns the detector IOCs.\nimogen.hartlow@example.com"),
    ("Kofi Mensah-Lyle", ["person/work"], "Kubernetes and the cluster upgrades; ask him about K3s.\nkofi@example.com"),
    ("Priya Ramaswell", ["person/work"], "Runs the Python packaging guild; reviews ibek PRs.\npriya.r@example.com"),
    ("Lars Oddvik", ["person/work"], "Visiting from the Lund facility until December.\nlars.oddvik@example.com"),
    ("Benedict Quarrie", ["person"], "Plumber: did the boiler service in May.\n01632 960 412 · ben@example.com"),
    ("Wren Alcott", ["person"], "Piano teacher, Tuesdays at 5.\nwren.alcott@example.com"),
]
for i, (name, tags, text) in enumerate(PEOPLE):
    p = capture("note", text, tags=tags, hours_ago=600 + 37 * i)
    patch(p, title=name)
    pages[f"person{i}"] = p
for i, (title, due, pri, ago) in enumerate([("Renew the passport", "2026-11-04", "medium", 90),
                                           ("Submit the tax return", "2026-11-30", "high", 120)]):
    pages[f"later_todo{i}"] = capture("todo", f"{title}.", tags=["home"], due=due, priority=pri, hours_ago=ago)
    patch(pages[f"later_todo{i}"], title=title)
c = capture("note", "The people I keep a note on are tagged #person, with family and work under it.\n\n"
    "- [Everyone](/search?q=tag:person%20group:letter)\n"
    "- [By group](/search?q=tag:person%20group:tag)\n"
    "- [Family](/search?q=tag:person/family%20sort:title)\n"
    "- [Work](/search?q=tag:person/work%20sort:title)\n\n"
    "Later's list: [what to read, watch, listen to and play](/search?q=kind:later).", hours_ago=6)
patch(c, title="Contacts"); pages["contacts"] = c
c = capture("note", "- [People A–Z](/search?q=tag:person%20group:letter)\n"
    "- [Family](/search?q=tag:person/family%20sort:title)\n"
    "- [Contacts](/p/contacts)\n", hours_ago=3)
patch(c, title="Pinned"); pages["pinned"] = c
c = capture("todo", "Compare Backstage and the others against what the group needs.\n\n- [ ] list the needs\n- [ ] try two",
    tags=["kind/project-management", "tools/developer-portal", "tech/epics/thoth"], due="2026-10-25", priority="high", hours_ago=4)
patch(c, title="Pick a developer portal for the controls group"); pages["portal"] = c

print(json.dumps({k: v["page_id"] for k, v in pages.items()}, indent=1))
