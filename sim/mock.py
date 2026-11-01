#!/usr/bin/env python3
"""The sim's mock pages: python3 -I mock.py DUMP OUT writes OUT/sim-seed.js.

It loads the frozen sample pages (fixtures/dump.json, made by seed.py and dump.py) and
appends mock pages, one block per design that needed them, each headed by a
"# ----" comment: Later items with a medium, people under #person, todos due later,
the Contacts and Pinned pages, page chips, the tag picker's controls pages, topics, and
what ingest made of the photos. sim.js reads the three globals it writes:
window.__SIM_SEED (pages and drawings), __SIM_INGEST (by page title or slug) and
__SIM_TOPICS (by slug). For a new design, add a block here (see sim/README.md).

Kept as it was written, not formatted or linted (sim/ is excluded from ruff).
"""
import json, sys
dump, out = sys.argv[1], sys.argv[2]
d = json.load(open(dump))
# ---- search groups mock: Later items with a medium, people under #person, a Contacts index
import re, hashlib
from datetime import datetime, timedelta, timezone
SEED = datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc)
CROCK = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
def ulid(key):
    h = int(hashlib.sha256(key.encode()).hexdigest(), 16)
    return "01M5" + "".join(CROCK[(h >> (5 * i)) & 31] for i in range(22))
def slug(t):
    return re.sub(r"[\s_]+", "-", re.sub(r"[^\w\s-]", "", t.lower())).strip("-")[:60]
def page(title, body, kind, fields, tags, hours_ago, url=None):
    at = (SEED - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"id": ulid(title), "slug": slug(title), "title": title, "body": body, "kind": kind,
            "kind_fixed": 1, "fields": fields, "created_at": at, "updated_at": at, "due": None,
            "priority": None, "snoozed_until": None, "rev": 1, "tags": tags,
            "captures": [{"id": ulid("c" + title), "kind": "url" if url else "note",
                          "text": None if url else body, "url": url, "source": "pwa",
                          "author": "tagged", "created_at": at, "received_at": at, "blobs": []}],
            "removed": [], "tasks": {"done": 0, "total": 0}}
MEDIUM = {"blindsight-by-peter-watts-recommended-after-permutation-city": "book",
          "https-www-anthropic-com-research": "article",
          "https-en-wikipedia-org-wiki-integrated-information-theory": "article"}
for p in d["pages"]:
    if p["slug"] in MEDIUM: p["fields"]["media_type"] = MEDIUM[p["slug"]]
SUB = {"book": "read", "article": "read", "film": "watch", "tv": "watch", "video": "watch",
       "podcast": "listen", "music": "listen", "game": "play"}
LATER = [  # title, medium, done, note, source, tags, hours ago
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
for title, medium, done, note, src, tags, ago in LATER:
    d["pages"].append(page(title, f"{note}\n\n{src}", "consume",
        {"subtype": SUB[medium], "status": "done" if done else "open", "source": src, "media_type": medium},
        tags, ago, url=src))
PEOPLE = [  # name, tags, a line or two (fictional people, example.com addresses)
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
    d["pages"].append(page(name, text, "note", {}, tags, 600 + 37 * i))
# Todos further out, for group:due's This week and Later (due days are the seed's: 21 Oct)
for title, due, pri, ago in [("Renew the passport", "2026-11-04", "medium", 90),
                             ("Submit the tax return", "2026-11-30", "high", 120)]:
    t = page(title, f"{title}.", "todo", {"status": "open"}, ["home"], ago)
    t["due"], t["priority"] = due, pri
    d["pages"].append(t)
d["pages"].append(page("Contacts",
    "The people I keep a note on are tagged #person, with family and work under it.\n\n"
    "- [Everyone](/search?q=tag:person%20group:letter)\n"
    "- [By group](/search?q=tag:person%20group:tag)\n"
    "- [Family](/search?q=tag:person/family%20sort:title)\n"
    "- [Work](/search?q=tag:person/work%20sort:title)\n\n"
    "Later's list: [what to read, watch, listen to and play](/search?q=kind:later).",
    "note", {}, [], 6))
# ---- search pins mock (#309 phase 2): the Pinned page, a page of links the launcher shows
d["pages"].append(page("Pinned",
    "- [People A–Z](/search?q=tag:person%20group:letter)\n"
    "- [Family](/search?q=tag:person/family%20sort:title)\n"
    "- [Contacts](/p/contacts)\n",
    "note", {}, [], 3))
# ---- page chips (short tag names, ✦ for Claude's, two rows): a todo like the owner's, its
# tags all Claude's, due 30 Oct (the seed's 25th: dates move with today), high; and a page
# with ten tags, for the +N chip
t = page("Pick a developer portal for the controls group",
    "Compare Backstage and the others against what the group needs.\n\n- [ ] list the needs\n- [ ] try two",
    "todo", {"status": "open"}, ["kind/project-management", "tools/developer-portal", "tech/epics/thoth"], 4)
t["due"], t["priority"] = "2026-10-25", "high"
t["model_tags"] = ["kind/project-management", "tools/developer-portal", "tech/epics/thoth"]
d["pages"].append(t)
m = page("Beamline 9 rack layout",
    "Where everything goes in the new rack, top to bottom.",
    "note", {}, ["work", "epics", "beamlines/i09", "hardware/racks", "hardware/power",
                 "people/imogen", "kind/reference", "tech/epics/ioc", "other/ioc", "site/diamond"], 2)
m["model_tags"] = ["kind/reference", "hardware/power"]
d["pages"].append(m)
# ---- tag picker mock: controls pages with many long hierarchical tags, some whose last parts clash
TP = [  # title, tags, Claude's, hours ago
    ("Controls roadmap for the winter shutdown", ["kind/project-management", "tools/developer-portal", "tech/epics/thoth", "work/controls"], ["tech/epics/thoth"], 8),
    ("Controls: Backstage trial notes", ["tools/developer-portal", "kind/meeting-notes", "work/controls", "tech/kubernetes/argocd"], [], 9),
    ("Controls IOC inventory", ["tech/epics/ioc", "kind/reference", "work/controls", "hardware/racks"], ["kind/reference"], 11),
    ("Controls weekly sync, 14 Oct", ["kind/meeting-notes", "work/controls", "tech/epics/thoth", "people/imogen"], [], 13),
    ("Controls: Thoth search experiments", ["projects/thoth", "tech/epics/thoth", "tech/python/packaging", "work/controls"], ["projects/thoth"], 15),
    ("Controls cluster upgrade plan", ["tech/kubernetes/k3s", "tech/kubernetes/argocd", "kind/project-management", "work/controls"], [], 17),
    ("Controls: ibek release checklist", ["tech/python/packaging", "tech/epics/ibek", "kind/checklist", "work/controls"], ["kind/checklist"], 19),
    ("Controls detector IOC notes", ["tech/epics/ioc", "beamlines/i09", "other/ioc", "work/controls"], [], 21),
    ("Controls onboarding guide", ["kind/reference", "tools/developer-portal", "people/lars", "work/controls"], [], 23),
    ("Controls: generic IOC builds", ["tech/epics/ioc", "tech/containers/generic-ioc", "kind/project-management"], [], 25),
]
for title, tags, ai, ago in TP:
    q = page(title, f"{title}. Notes for the controls group.", "note", {}, tags, ago)
    if ai: q["model_tags"] = ai
    d["pages"].append(q)
# ---- topics (Claude's topic pages, #261): pages of kind topic, with their sources; the sim
# works out each one's area (the top-level tag most common among its sources) as the server does
TOPICS = [  # title, key, summary, synthesis, source slugs, hours ago
    ("scrap's design", "scrap-design",
     "Capture first, keep the originals, one tap for the common action: the ideas the design notes and the whiteboard keep returning to.",
     "## Overview\n\nscrap is built around capture: the phone saves first and uploads later, and every original is kept.\n\n## Key facts\n\n- One process, no login, in v0 ([[2026-10-21-13-52]]).\n- The common action is one tap ([[scrap-design-notes]]).\n\n## Open questions\n\n- How long titles should wrap in a list.",
     ["scrap-design-notes", "2026-10-21-13-52", "body-text-for-the-long-title-check"], 20),
    ("Search and storage", "scrap-search",
     "SQLite holds everything; sqlite-vec may add similar-page search, and the page cap keeps big pages in check.",
     "## Overview\n\nEverything lives in SQLite. Two open threads: vector search with sqlite-vec, and the page size cap.\n\n## Key facts\n\n- The cap is under review in PR 125.",
     ["look-at-sqlite-vec-0-2-release-notes", "review-pr-125-page-cap", "scrap-design-notes"], 44),
    ("The garden through the year", "garden",
     "Bulbs before the first frost, a fence panel to mend, and the front border at its best in late summer.",
     "## Overview\n\nThe garden's year in three notes: planting, repairs and what flowered.",
     ["front-border-in-flower", "fix-the-broken-fence-panel", "plant-the-tulip-bulbs-before-the-first-frost-"], 70),
    ("Running the house", "house",
     "Gutters, the boiler, the gas safety certificate for the tenant and the dog's food: the jobs that come round again.",
     "## Overview\n\nThe house's recurring jobs, and who to call for each.",
     ["clear-the-gutters", "call-the-plumber-about-the-boiler", "send-the-gas-safety-certificate-to-the-tenant", "buy-dog-food"], 30),
    ("Keeping the car on the road", "car",
     "The MOT and the insurance renewal fall in the same month.",
     "## Overview\n\nTwo dates a year: the MOT and the insurance.",
     ["book-the-mot", "renew-car-insurance"], 100),
    ("IOC upkeep", "ioc-upkeep",
     "Releasing ibek 4.1, a spare power supply for the IOCs, and what the weekly controls sync decided.",
     "## Overview\n\nThe controls work that keeps coming back: releases, spares and the weekly sync.",
     ["release-ibek-4-1", "order-a-spare-ioc-power-supply", "weekly-controls-sync"], 26),
    ("Minds and machines", "minds",
     "Blindsight, integrated information theory and Anthropic's research: what it would take for a machine to be aware.",
     "## Overview\n\nThree reads that circle the same question.",
     ["blindsight-by-peter-watts-recommended-after-p", "https-www-anthropic-com-research", "https-en-wikipedia-org-wiki-integrated-inform"], 140),
    ("Who to ask", "who-to-ask",
     "The contacts index: where to find family, colleagues and the people who fix things.",
     "## Overview\n\nOne index page links the people searches.",
     ["contacts"], 200),
]
bylead = {p["slug"][:45]: p["slug"] for p in d["pages"]}
sim_topics = {}
for title, key, summary, text, srcs, ago in TOPICS:
    t = page(title, "", "topic", {}, [], ago)
    t["captures"] = []
    d["pages"].append(t)
    sim_topics[t["slug"]] = {"key": key, "summary": summary, "text": text,
                             "sources": [bylead.get(x[:45], x) for x in srcs]}
ingest = {
    "Architecture whiteboard": {"state": "done", "image_kind": "whiteboard",
        "description": "A whiteboard sketch of scrap's architecture: the PWA talks to FastAPI, which stores pages in SQLite; an Ingest worker sits under FastAPI, with a note that Claude reads, summarises and redraws.",
        "text": "PWA → FastAPI → SQLite\nIngest\nClaude: read, summarise, redraw\nv0: one process, no login"},
    "Hardware receipt — fence": {"state": "done", "image_kind": "document",
        "description": "A till receipt from a hardware shop for fencing materials.",
        "text": "CAVERSHAM HARDWARE\nFence panel 6x5 34.99\nPost 2.4m 12.50\nScrews x100 4.20\nCreosote 5L 18.00\nTOTAL 69.69"},
    "front-border-in-flower": {"state": "done", "image_kind": "photo",
        "description": "A garden border in full flower: red, yellow, white and purple blooms against green foliage under a pale sky."},
    "fix-the-broken-fence-panel": {"state": "queued"},
}
# ---- Claude's reading (#521): a maths page with Claude's own SVGs (add_svg: shown with
# nothing under them, one read before #521 too) and the owner's photo of his working (its reading in one closed
# fold), and a page of photos and files in each state (status and Retry outside the fold).
# An image with "_svg" is made into an object URL by sim.js.
def svgblob(name, svg, ingest):
    return {"sha256": hashlib.sha256(svg.encode()).hexdigest(), "mime": "image/svg+xml",
            "size": len(svg), "filename": name, "ingest": ingest, "_svg": svg}
def read(desc, text=None, state="done", **o):
    return {"state": state, "failures": 1 if state == "failed" else 0, "error": None, "text": text,
            "description": desc, "image_kind": "diagram", "drawing": None, **o}
TRI = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 150" font-family="serif" font-size="15">
<rect width="320" height="150" fill="#fff"/><g fill="none" stroke="#222" stroke-width="2.5">
<path d="M110 25 V125 H250 Z"/><path d="M110 112 h13 v13"/></g>
<text x="104" y="20">A</text><text x="104" y="144">B</text><text x="254" y="144">C</text>
<text x="56" y="80">5 cm</text><text x="158" y="146">12 cm</text></svg>"""
PQR = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 150" font-family="serif" font-size="15">
<rect width="320" height="150" fill="#fff"/><g fill="none" stroke="#222" stroke-width="2.5">
<path d="M160 22 L80 125 H240 Z"/><path d="M98 125 a18 18 0 0 0 -7 -14"/></g>
<text x="155" y="16">P</text><text x="66" y="140">Q</text><text x="244" y="140">R</text>
<text x="80" y="68">8 cm</text><text x="210" y="68">8 cm</text><text x="142" y="145">10 cm</text>
<text x="100" y="116" font-size="13">x°</text></svg>"""
WORK = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 200">
<defs><pattern id="g" width="16" height="16" patternUnits="userSpaceOnUse"><path d="M16 0H0V16" fill="none" stroke="#b9cbe0" stroke-width="1"/></pattern></defs>
<rect width="320" height="200" fill="#f7f4ea"/><rect width="320" height="200" fill="url(#g)"/>
<g font-family="'Comic Sans MS','Segoe Print','Bradley Hand',cursive" font-size="19" fill="#1d2f6e">
<text x="18" y="40">AC² = 5² + 12²</text><text x="18" y="76">     = 25 + 144 = 169</text>
<text x="18" y="112">AC = √169</text><text x="18" y="150">AC = 13 cm</text></g>
<path d="M14 160 h118" stroke="#1d2f6e" stroke-width="2"/><path d="M14 165 h118" stroke="#1d2f6e" stroke-width="2"/></svg>"""
tri = svgblob("triangle-abc.svg", TRI, None)
pqr = svgblob("triangle-pqr.svg", PQR, read("An isosceles triangle PQR with sides 8 cm, 8 cm and 10 cm.", "P Q R 8 cm 8 cm 10 cm x°"))
work = svgblob("my working.svg", WORK, read(
    "A photo of handwritten working on squared paper: Pythagoras' theorem applied to the triangle, giving AC = 13 cm, underlined twice.",
    "AC² = 5² + 12²\n= 25 + 144 = 169\nAC = √169\nAC = 13 cm"))
emb = lambda b: f"![](/api/blobs/{b['sha256']}/preview?size=2048)"
m = page("GCSE maths paper 2: triangles",
    "\n\n".join(["**3.** Work out the length of AC. Give your answer in centimetres.", emb(tri),
                 "My working, photographed:", emb(work),
                 "**4.** Work out the size of angle x. Give your answer to 1 decimal place.", emb(pqr)]),
    "note", {}, ["maths", "revision"], 2)
cap = m["captures"][0]
at = cap["created_at"]
m["captures"] = [
    {**cap, "id": ulid("c521-owner"), "kind": "photo", "text": None, "author": "you", "blobs": [work]},
    {"id": ulid("c521-claude-1"), "kind": "photo", "text": None, "url": None, "source": "mcp",
     "author": "claude", "created_at": at, "received_at": at, "blobs": [tri]},
    {"id": ulid("c521-claude-2"), "kind": "photo", "text": None, "url": None, "source": "mcp",
     "author": "claude", "created_at": at, "received_at": at, "blobs": [pqr]},
]
d["pages"].append(m)
# Each state: read (fold, Regenerate inside), failed (Retry outside), waiting, paused (Resume),
# never read (Generate, in the fold), a PDF that failed (Retry outside), a PDF read (its text)
FENCE, GARDEN, BOARD, RECEIPT = ("5bbacd0b5eac519aff0037a7d1de06d808e33a26f99567f18f0dc8e26e896f9d",
    "0b603180d1b9ef921a637e6ca28ab6c19fc52bf123e1db6162ccae4fc15342f5",
    "81fdcce0010c5ab1c03ac3ed241595b321d55aa1db5caa10d6b9f5da34d79a15",
    "6bc896a6148e0f14420edd7dcbb42705b0d9f7bd28f64a18f77a39a7747c6f7b")
def jpg(sha, name, ingest):
    return {"sha256": sha, "mime": "image/jpeg", "size": 60000, "filename": name, "ingest": ingest}
ph = lambda **o: {**read(None), "image_kind": "photo", **o}
st = page("Fence repair: photos and quotes (reading states)",
    "\n\n".join(["The broken panel, read by Claude:", emb({"sha256": FENCE}),
                 "The receipt: Claude couldn't read it this time.", emb({"sha256": RECEIPT}),
                 "The border, waiting for Claude:", emb({"sha256": GARDEN}),
                 "The whiteboard, never sent to Claude:", emb({"sha256": BOARD})]),
    "note", {}, ["house"], 3)
st["captures"][0].update(kind="photo", text=None, author="you", blobs=[
    jpg(FENCE, "IMG_2041.jpg", ph(description="A wooden garden fence with one panel split down the middle and leaning out; the concrete post beside it is intact.", text="CLOSEBOARD 6x5")),
    jpg(RECEIPT, "receipt.jpg", ph(state="failed", error="overloaded: try again later")),
    jpg(GARDEN, "IMG_2050.jpg", ph(state="queued")),
    jpg(BOARD, "whiteboard.jpg", None),
])
d["pages"].append(st)
open(f"{out}/sim-seed.js", "w").write(
    "window.__SIM_SEED=" + json.dumps({"pages": d["pages"], "drawings": d["drawings"]}) + ";\n"
    "window.__SIM_INGEST=" + json.dumps(ingest) + ";\n"
    "window.__SIM_TOPICS=" + json.dumps(sim_topics) + ";\n")
