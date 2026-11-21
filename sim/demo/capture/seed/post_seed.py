"""Second pass on the demo server's database: the sim's slugs, photo readings, topics."""
import re, sys
from scrap.store import Store, now, transaction
from scrap.store import topics as T
from scrap.store import writeups as W
from scrap.ingest.jobs import put_derived

store = Store(sys.argv[1])
def slug(t):
    return re.sub(r"[\s_]+", "-", re.sub(r"[^\w\s-]", "", t.lower())).strip("-")[:60]

FIX = ["Pick a developer portal for the controls group", "Pinned", "Contacts", "Wren Alcott",
       "Benedict Quarrie", "Lars Oddvik", "Priya Ramaswell", "Kofi Mensah-Lyle", "Imogen Hartlow",
       "Felix Pell", "Rosa Vantongeren", "Theo Pell", "Marjorie Pell", "Outer Wilds", "Wingspan",
       "In Rainbows — Radiohead", "In Our Time — the measurement problem", "Mindscape — the hard problem",
       "But what is a neural network?", "Severance — season 2", "Ex Machina (2014)", "Arrival (2016)",
       "Strangler Fig Application", "Piranesi — Susanna Clarke", "The Dispossessed — Ursula K. Le Guin"]
READ = {
    "Architecture whiteboard": ("A whiteboard sketch of scrap's architecture: the PWA talks to FastAPI, which stores pages in SQLite; an Ingest worker sits under FastAPI, with a note that Claude reads, summarises and redraws.",
        "PWA → FastAPI → SQLite\nIngest\nClaude: read, summarise, redraw\nv0: one process, no login"),
    "Hardware receipt — fence": ("A till receipt from a hardware shop for fencing materials.",
        "CAVERSHAM HARDWARE\nFence panel 6x5 34.99\nPost 2.4m 12.50\nScrews x100 4.20\nCreosote 5L 18.00\nTOTAL 69.69"),
    "Front border in flower": ("A garden border in full flower: red, yellow, white and purple blooms against green foliage under a pale sky.", None),
}
TOPICS = [  # title, key, summary, synthesis, source titles
    ("scrap's design", "scrap-design",
     "Capture first, keep the originals, one tap for the common action: the ideas the design notes and the whiteboard keep returning to.",
     "## Overview\n\nscrap is built around capture: the phone saves first and uploads later, and every original is kept.\n\n## Key facts\n\n- One process, no login, in v0 ([[{board}]]).\n- The common action is one tap ([[scrap-design-notes]]).\n\n## Open questions\n\n- How long titles should wrap in a list.",
     ["scrap design notes", "Architecture whiteboard"]),
    ("Search and storage", "scrap-search",
     "SQLite holds everything; sqlite-vec may add similar-page search, and the page cap keeps big pages in check.",
     "## Overview\n\nEverything lives in SQLite. Two open threads: vector search with sqlite-vec, and the page size cap.\n\n## Key facts\n\n- The cap is under review in PR 125.",
     ["Look at sqlite-vec 0.2 release notes", "Review PR #125: page cap", "scrap design notes"]),
    ("The garden through the year", "garden",
     "Bulbs before the first frost, a fence panel to mend, and the front border at its best in late summer.",
     "## Overview\n\nThe garden's year in three notes: planting, repairs and what flowered.",
     ["Front border in flower", "Fix the broken fence panel", "Plant the tulip bulbs before the first frost. Move the rosemary somewhere sunnier."]),
    ("Running the house", "house",
     "Gutters, the boiler, the gas safety certificate for the tenant and the dog's food: the jobs that come round again.",
     "## Overview\n\nThe house's recurring jobs, and who to call for each.",
     ["Clear the gutters", "Call the plumber about the boiler", "Send the gas safety certificate to the tenants", "Buy dog food"]),
    ("Keeping the car on the road", "car",
     "The MOT and the insurance renewal fall in the same month.",
     "## Overview\n\nTwo dates a year: the MOT and the insurance.",
     ["Book the MOT", "Renew car insurance"]),
    ("IOC upkeep", "ioc-upkeep",
     "Releasing ibek 4.1, a spare power supply for the IOCs, and what the weekly controls sync decided.",
     "## Overview\n\nThe controls work that keeps coming back: releases, spares and the weekly sync.",
     ["Release ibek 4.1", "Order a spare IOC power supply", "Controls sync — 20 Oct"]),
    ("Minds and machines", "minds",
     "Blindsight, integrated information theory and Anthropic's research: what it would take for a machine to be aware.",
     "## Overview\n\nThree reads that circle the same question.",
     ["Blindsight — Peter Watts", "Anthropic research", "Integrated information theory"]),
    ("Who to ask", "who-to-ask",
     "The contacts index: where to find family, colleagues and the people who fix things.",
     "## Overview\n\nOne index page links the people searches.",
     ["Contacts"]),
]
with store.connect() as conn, transaction(conn):
    stamp = now()
    byt = {r["title"]: r["id"] for r in conn.execute("SELECT id, title FROM page WHERE deleted_at IS NULL")}
    for t in FIX:
        conn.execute("UPDATE page SET slug = ? WHERE id = ?", (slug(t), byt[t]))
    # the sim's dated slugs (sim/fixtures/dump.json), so links Claude writes open in the sim
    for t, s in (("Architecture whiteboard", "2026-10-21-13-52"), ("Hardware receipt — fence", "2026-10-21-08-52")):
        conn.execute("UPDATE page SET slug = ? WHERE id = ?", (s, byt[t]))
    for t, (desc, ocr) in READ.items():
        cap, sha = conn.execute("SELECT c.id, b.sha256 FROM capture c JOIN capture_blob b ON b.capture_id = c.id"
                                " WHERE c.page_id = ? ORDER BY b.ord LIMIT 1", (byt[t],)).fetchone()
        put_derived(conn, cap, sha, "description", "claude-sonnet-4-5", stamp, text=desc)
        if ocr:
            put_derived(conn, cap, sha, "ocr", "claude-sonnet-4-5", stamp, text=ocr)
        store.reindex(conn, byt[t])
    board = conn.execute("SELECT slug FROM page WHERE id = ?", (byt["Architecture whiteboard"],)).fetchone()[0]
    for title, key, summary, text, srcs in TOPICS:
        pid = T.create(conn, title, key, slug(title), "claude", stamp)
        T.add_sources(conn, pid, [byt[s] for s in srcs], "claude", stamp)
        W.put(conn, pid, stamp, producer="claude-sonnet-4-5", run_id=None, prompt_version="demo",
              summary=summary, text=text.replace("{board}", board), guidance=None)
        store.reindex(conn, pid)
    for pid in byt.values():
        store.reindex(conn, pid)
print("ok")
