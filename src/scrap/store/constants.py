"""Limits, patterns and SQL fragments the store shares."""

import re

from .todo import col

BlobRef = tuple[str, str, int, str | None]  # sha256, mime, size, filename
ULID = re.compile(r"[0-9A-HJKMNP-TV-Z]{26}")
SHA256 = re.compile(r"[0-9a-f]{64}")
BARE_URL = re.compile(r"https?://\S+")
# Ranking: bm25 weights of a page's title, tags, summary and text (chunk_fts's columns)
WEIGHTS = "10.0, 5.0, 3.0, 1.0"
# Each part stops at the next bracket, so no line takes more than linear time
MD_LINK = re.compile(
    r"!?\[([^\[\]\n]*)\]\((?:<[^<>\n]*>|[^()\s]*)(?:\s+\"[^\"\n]*\")?\)"
)
WIKI_LINK = re.compile(r"\[\[([^\[\]|\n]+)(?:\|([^\[\]\n]+))?\]\]")
# A file's address in a page's text (see body_refs). Linear: no backtracking.
BLOB_ADDRESS = re.compile(r"/api/blobs/([0-9a-f]{64})")
# A capture's token for one of its own uploads in its text (helpers.placed):
# ⟦image N⟧ or ⟦file N⟧ (⟦file N: name⟧ too), N the upload's place among the
# request's files from 1. The word is a hint for the reader; the stored type decides
# the embed. Linear.
UPLOAD_TOKEN = re.compile(r"⟦(?:image|file) ([1-9][0-9]{0,3})(?::[^⟦⟧\n]*)?⟧")
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
# The kinds a page can have (the schema allows only these), and the fields a page gets
# when it becomes that kind
KINDS = ("note", "todo", "consume", "whiteboard", "document")
DEFAULT_FIELDS = {
    "todo": {"status": "open"},
    "consume": {"subtype": "read", "status": "open"},
}
HINTS = ("todo", "consume")  # the older capture field, still accepted
# kind: in a search also takes the PWA's names for kinds
# A file of a page's capture whose embed or link the user deleted from the text (its
# SQL; mcp_tools/reading.py filters by Store.removed, the same test in Python, so
# the two are deliberately parallel): a template on the page ({p}) and the file's
# SHA-256 ({sha}).
# The capture still holds it (gc and orphans need that), but the page no longer shows
# it, so listings, counts and is:duplicate leave it out (#303). A file the text never
# mentioned (an older photo, a PDF) is not gone: it is listed below the text.
GONE = (
    "(NOT instr({p}.body, '/api/blobs/' || {sha}) AND EXISTS (SELECT 1"
    " FROM page_rev r WHERE r.page_id = {p}.id"
    " AND instr(r.body, '/api/blobs/' || {sha})))"
)
# A page p's thumbnail: the SHA-256 of its first image, if any (SQL, for a column)
THUMB = (
    "(SELECT b.sha256 FROM capture c JOIN capture_blob cb"
    " ON cb.capture_id = c.id JOIN blob b USING (sha256)"
    " WHERE c.page_id = p.id AND b.mime LIKE 'image/%'"
    # not one whose embed was deleted from the text
    f" AND NOT {GONE.format(p='p', sha='b.sha256')}"
    " ORDER BY c.received_at, cb.ord LIMIT 1)"
)
# Search filters on a page p's images (SQL): has:image, has:drawing, and image:K (the
# kind Claude gave a photo: photo, whiteboard, screenshot...)
HAS = {
    "image": "EXISTS (SELECT 1 FROM capture c JOIN capture_blob cb"
    " ON cb.capture_id = c.id JOIN blob b USING (sha256)"
    " WHERE c.page_id = p.id AND b.mime LIKE 'image/%'"
    f" AND NOT {GONE.format(p='p', sha='cb.sha256')})",
    "drawing": "EXISTS (SELECT 1 FROM capture c JOIN derived d ON d.capture_id = c.id"
    " WHERE c.page_id = p.id AND d.kind = 'excalidraw' AND d.superseded_at IS NULL)",
}
IMAGE_KIND = (
    "EXISTS (SELECT 1 FROM capture c JOIN derived d ON d.capture_id = c.id"
    " WHERE c.page_id = p.id AND d.kind = 'description' AND d.superseded_at IS NULL"
    " AND json_extract(d.data, '$.kind') = ?)"
)
KIND_NAMES = {
    "later": "consume",
    "read": "consume",
    "board": "whiteboard",
    "doc": "document",
}
# What each sort: orders a page p by (query.SORTS has its default direction)
SORT_SQL = {
    "updated": "p.updated_at",
    "created": "p.created_at",
    "title": "p.title COLLATE NOCASE",  # ASCII letters only: SQLite has no ICU here
    # A todo's: other kinds keep theirs (see the migration) but have none here
    "due": f"CASE WHEN p.kind = 'todo' THEN {col('due')} END",
    "priority": f"CASE WHEN p.kind = 'todo' THEN CASE {col('priority')}"
    " WHEN 'high' THEN 3 WHEN 'medium' THEN 2 WHEN 'low' THEN 1 END END",
}
TODO = ("due", "priority")  # a todo's own values (page_todo)
TODO_SQL = "p.kind = 'todo' AND "  # a filter on them: only a todo's count
RANK = f"coalesce({col('priority')}, 'none')"  # priority:none finds a todo with none
# Priorities as an imported todo may have them (Thoth's Urgent: the highest there is)
PRIORITY_NAMES = {"urgent": "high"}
SOURCES = ("pwa", "share")  # a capture's, from a client; "mcp" only from scrap.mcp
MCP = "mcp"  # the source of a page Claude wrote, over MCP
# The author of what Claude writes: its MCP captures, and its text revisions (page_rev)
# over MCP or of the task boxes it adds (actions.append). The PWA's author is whatever
# the identity header says (a Tailscale login, an address; behind oauth2-proxy, as on
# the cluster, the GitHub username), or "tagged": never CLAUDE (uploads.author ignores
# a header that says it, #153). Whether a revision is Claude's is its source, not this.
CLAUDE = "claude"
MAX_FIELDS = 32  # a page's fields are listed with every page: keep them small
MAX_TAGS = 64  # a page's, as the PWA sets them (MCP's write takes fewer)
MAX_TAG = 64  # characters, as the tag table's CHECK has it
MAX_PAGE = 1_000_000  # bytes of UTF-8: a page's text, however it is written (#62)
KINDS_SHOWN = ("ocr", "description", "excalidraw")
META_SOURCES = ("web", "mcp")  # who changed a page's kind or tags: the PWA, or Claude
# A text revision, with where it came from (page_rev.source, migration 16): mcp for
# Claude's text (over MCP, or the task boxes it adds: actions.append), else web (the
# PWA and the API, and scrap's own: import, gc, a topic page made). Folding a burst and
# is:claude-edited go by it, not by the author's name (#153).
REV_INSERT = (
    "INSERT INTO page_rev (page_id, rev, title, body, author, source, created_at)"
    " VALUES (?, ?, ?, ?, ?, ?, ?)"
)
# Every change to a page's kind and tags, newest first (see page_meta_rev)
META_REV = (
    "SELECT id, page_id, author, source, kind_before, kind_after, fixed_before,"
    " fixed_after, tags_before, tags_after, fields_added, fields_was, reverts,"
    " batch_id, created_at, updated_at, public_before, public_after FROM page_meta_rev"
)
# The files ingest reads locally for search (#234): a PDF's text layer, a text file's
# text. No model reads them. A blob's type as stored, without parameters (charset=).
FILE_TYPES = ("application/pdf", "text/plain", "text/markdown")
# Characters: a shorter note gets tags but no summary from enrich, and a file page
# whose files' text is shorter is not sent to Claude unasked (ADR 38)
SHORT = 200
IS_FILE = (
    "lower(trim(substr({b}.mime, 1, instr({b}.mime || ';', ';') - 1))) IN ("
    + ", ".join(f"'{t}'" for t in FILE_TYPES)
    + ")"
)
IS_IMAGE = "{b}.mime LIKE 'image/%'"
# A capture Claude made over MCP (add_svg's, or its /mcp upload): its images are its
# own, so Claude never reads them (#521). Keyed on the capture, not the file: the same
# file in one of the owner's captures is that capture's, and is read.
BY_CLAUDE = f"({{c}}.source = '{MCP}' AND {{c}}.author = '{CLAUDE}')"
# One ingest job per distinct image of a photo capture (or the one photo asked for),
# and per distinct readable file (FILE_TYPES) of any capture; job_one_active makes a
# repeat add nothing. An image of a file capture is not sent to Claude unasked, nor
# one of a capture Claude made (BY_CLAUDE), even asked.
ENQUEUE = f"""
INSERT INTO job (kind, capture_id, source_sha256, options, run_after, created_at,
                 updated_at)
SELECT DISTINCT 'ingest', cb.capture_id, cb.sha256, :options, :now, :now, :now
FROM capture_blob cb
JOIN capture c ON c.id = cb.capture_id
JOIN blob b ON b.sha256 = cb.sha256
WHERE cb.capture_id = :capture AND coalesce(:photo, cb.sha256) = cb.sha256
  AND (({IS_IMAGE.format(b="b")} AND (c.kind = 'photo' OR :photo IS NOT NULL)
        AND NOT {BY_CLAUDE.format(c="c")})
       OR {IS_FILE.format(b="b")})
ON CONFLICT DO NOTHING
"""
# An ingest job j of an image: what photo ingest sends to Claude. A file's job (IS_FILE)
# is read locally, and never counts for a page's first read or its write-up.
IMAGE_JOB = (
    "EXISTS (SELECT 1 FROM blob jb WHERE jb.sha256 = {j}.source_sha256"
    " AND jb.mime LIKE 'image/%')"
)


HEADING = re.compile(r"^ {0,3}#{1,6}(?:[ \t]+|$)")  # an ATX heading's marker


SURROGATE = re.compile(r"[\ud800-\udfff]")  # half a UTF-16 pair: no UTF-8 for it


Value = str | int | float | bool  # a field's value: flat, no nulls
MAX_INT = 2**53  # the most a browser holds exactly: a field's number is within +-this


# The page kinds Claude reads for tags and a summary: notes (a saved link is one), todos
# and reads (consume). A photo, whiteboard or document page is not read as text (#155).
# Ask Claude is an explicit act and still works on any page.
ENRICH_KINDS = ("note", "todo", "consume")
# The slug of the Pinned page (pinned.py): a list of links, which Claude does not read
PINNED_SLUG = "pinned"
# The page kind photo ingest files an image of each kind as (a note nobody filed)
PAGE_KINDS = {
    "whiteboard": "whiteboard",
    "diagram": "whiteboard",
    "document": "document",
}


# A page's first related call, once it is first read: one job with reason 'related',
# ever. Never in place of a queued job (a save meanwhile: the nightly pass sees the
# change); a later save or Ask takes this one over (Ask picks related pages too).
RELATED_ENQUEUE = """
INSERT INTO enrich_job (page_id, reason, run_after, created_at, updated_at)
SELECT :page, 'related', :now, :now, :now
WHERE NOT EXISTS (SELECT 1 FROM enrich_job WHERE page_id = :page AND reason = 'related')
ON CONFLICT DO NOTHING
"""
# A page's first photo capture (the first with an image's ingest job), once none of its
# photos waits or is being read (each read, or dead): its page, else nothing. A file's
# job (a PDF's) counts for neither.
FIRST_READ = f"""
SELECT c.page_id FROM capture c WHERE c.id = :capture
  AND c.id = (SELECT f.id FROM capture f JOIN job j ON j.capture_id = f.id
              WHERE f.page_id = c.page_id AND {IMAGE_JOB.format(j="j")}
              ORDER BY f.received_at, f.id LIMIT 1)
  AND NOT EXISTS (SELECT 1 FROM job j WHERE j.capture_id = c.id
                  AND j.state IN ('queued', 'running') AND {IMAGE_JOB.format(j="j")})
"""


# One queued enrich job per page: a later trigger moves it (a save later, Ask now), and
# Ask is remembered (it may add tags to a page Claude has read before), as is a write-up
# but for Ask (which writes one too), and a topic's synthesis but for Ask
ENRICH_ENQUEUE = """
INSERT INTO enrich_job (page_id, reason, run_after, created_at, updated_at)
VALUES (:page, :reason, :run_after, :now, :now)
ON CONFLICT (page_id) WHERE state = 'queued' DO UPDATE SET
    run_after = excluded.run_after,
    reason = CASE WHEN reason = 'ask'
                    OR (reason IN ('writeup', 'topic') AND excluded.reason <> 'ask')
             THEN reason ELSE excluded.reason END,
    updated_at = excluded.updated_at
"""
