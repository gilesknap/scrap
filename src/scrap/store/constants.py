"""Limits, patterns and SQL fragments the store shares."""

import re

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
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
# The kinds a user can choose (memory and reference are in the schema, not offered yet),
# and the fields a page gets when it becomes that kind
KINDS = ("note", "todo", "consume", "whiteboard", "document")
DEFAULT_FIELDS = {
    "todo": {"status": "open"},
    "consume": {"subtype": "read", "status": "open"},
}
HINTS = ("todo", "consume")  # the older capture field, still accepted
ALL_KINDS = (*KINDS, "memory", "reference")  # in the schema, so a filter may ask
# kind: in a search also takes the PWA's names for kinds
# A page p's thumbnail: the SHA-256 of its first image, if any (SQL, for a column)
THUMB = (
    "(SELECT b.sha256 FROM capture c JOIN capture_blob cb"
    " ON cb.capture_id = c.id JOIN blob b USING (sha256)"
    " WHERE c.page_id = p.id AND b.mime LIKE 'image/%'"
    # not one whose embed was deleted from the text (see Store.removed)
    " AND (instr(p.body, '/api/blobs/' || b.sha256) OR NOT EXISTS (SELECT 1"
    " FROM page_rev r WHERE r.page_id = p.id"
    " AND instr(r.body, '/api/blobs/' || b.sha256)))"
    " ORDER BY c.received_at, cb.ord LIMIT 1)"
)
# Search filters on a page p's images (SQL): has:image, has:drawing, and image:K (the
# kind Claude gave a photo: photo, whiteboard, screenshot...)
HAS = {
    "image": "EXISTS (SELECT 1 FROM capture c JOIN capture_blob cb"
    " ON cb.capture_id = c.id JOIN blob b USING (sha256)"
    " WHERE c.page_id = p.id AND b.mime LIKE 'image/%')",
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
    "due": "CASE WHEN p.kind = 'todo' THEN p.due END",
    "priority": "CASE WHEN p.kind = 'todo' THEN CASE p.priority"
    " WHEN 'high' THEN 3 WHEN 'medium' THEN 2 WHEN 'low' THEN 1 END END",
}
TODO = ("due", "priority", "snoozed_until")  # a todo's own columns
TODO_SQL = "p.kind = 'todo' AND "  # a filter on them: only a todo's count
RANK = "coalesce(p.priority, 'none')"  # priority:none finds a todo with none
# Priorities as an imported todo may have them (Thoth's Urgent: the highest there is)
PRIORITY_NAMES = {"urgent": "high"}
SOURCES = ("pwa", "share")  # a capture's, from a client; "mcp" only from scrap.mcp
MCP = "mcp"  # the source of a page Claude wrote, over MCP
# The author of what Claude writes over MCP: of its captures, and of its text revisions
# (page_rev). Only MCP writes as it: the PWA's author is a Tailscale login (an address,
# with an @) or "tagged", so a text revision by CLAUDE is one made over MCP.
CLAUDE = "claude"
MAX_FIELDS = 32  # a page's fields are listed with every page: keep them small
MAX_TAGS = 64  # a page's, as the PWA sets them (MCP's write takes fewer)
MAX_TAG = 64  # characters, as the tag table's CHECK has it
MAX_PAGE = 1_000_000  # bytes of UTF-8: a page's text, however it is written (#62)
KINDS_SHOWN = ("ocr", "description", "excalidraw")
META_SOURCES = ("web", "mcp")  # who changed a page's kind or tags: the PWA, or Claude
# Every change to a page's kind and tags, newest first (see page_meta_rev)
META_REV = (
    "SELECT id, page_id, author, source, kind_before, kind_after, fixed_before,"
    " fixed_after, tags_before, tags_after, fields_added, reverts, batch_id,"
    " created_at, updated_at FROM page_meta_rev"
)
# One ingest job per distinct image of a photo capture (or the one photo asked for);
# job_one_active makes a repeat add nothing.
ENQUEUE = """
INSERT INTO job (kind, capture_id, source_sha256, options, run_after, created_at,
                 updated_at)
SELECT DISTINCT 'ingest', cb.capture_id, cb.sha256, :options, :now, :now, :now
FROM capture_blob cb
JOIN capture c ON c.id = cb.capture_id AND (c.kind = 'photo' OR :photo IS NOT NULL)
JOIN blob b ON b.sha256 = cb.sha256 AND b.mime LIKE 'image/%'
WHERE cb.capture_id = :capture AND coalesce(:photo, cb.sha256) = cb.sha256
ON CONFLICT DO NOTHING
"""


HEADING = re.compile(r"^ {0,3}#{1,6}(?:[ \t]+|$)")  # an ATX heading's marker


SURROGATE = re.compile(r"[\ud800-\udfff]")  # half a UTF-16 pair: no UTF-8 for it


Value = str | int | float | bool  # a field's value: flat, no nulls
MAX_INT = 2**53  # the most a browser holds exactly: a field's number is within +-this


# The page kinds Claude reads for tags and a summary: notes (a saved link is one), todos
# and reads (consume). A photo, whiteboard or document page is not read as text (#155).
# Ask Claude is an explicit act and still works on any page.
ENRICH_KINDS = ("note", "todo", "consume")
# The page kind photo ingest files an image of each kind as (a note nobody filed)
PAGE_KINDS = {
    "whiteboard": "whiteboard",
    "diagram": "whiteboard",
    "document": "document",
}


# The id of a page's first capture (SQL; page: an expression for the page's id).
# A page's first capture decides what the page is; later captures only add content
# (#260): what automation infers from them never changes its kind, title or tags, or
# whether enrich or ingest maintains it. The one test of it, for TITLE_CAS, the photo
# worker and NOT_BY_INGEST.
# Captures received at the same moment (an import's): a file capture last, then one
# with no files before one with them, then the id, so an import's main capture (its
# text, with its images) is first whatever its hash-derived id.
FIRST_CAPTURE = (
    "(SELECT f.id FROM capture f WHERE f.page_id = {page}"
    " ORDER BY f.received_at, f.kind = 'file',"
    " EXISTS (SELECT 1 FROM capture_blob b WHERE b.capture_id = f.id), f.id LIMIT 1)"
)
# A page made by a photo or file capture (its first) is read by ingest, not enrich,
# whatever its kind (a photo page is stored as a note until ingest reclassifies it).
NOT_BY_INGEST = (
    "coalesce((SELECT c.kind FROM capture c WHERE c.id = "
    + FIRST_CAPTURE.format(page="{p}.id")
    + "), '') NOT IN ('photo', 'file')"
)


# A page's first related call, once it is first read: one job with reason 'related',
# ever. Never in place of a queued job (a save meanwhile: the nightly pass sees the
# change); a later save or Ask takes this one over (Ask picks related pages too).
RELATED_ENQUEUE = """
INSERT INTO enrich_job (page_id, reason, run_after, created_at, updated_at)
SELECT :page, 'related', :now, :now, :now
WHERE NOT EXISTS (SELECT 1 FROM enrich_job WHERE page_id = :page AND reason = 'related')
ON CONFLICT DO NOTHING
"""
# A page's first photo capture (the first with an ingest job), once none of its photos
# waits or is being read (each read, or dead): its page, else nothing
FIRST_READ = """
SELECT c.page_id FROM capture c WHERE c.id = :capture
  AND c.id = (SELECT f.id FROM capture f JOIN job j ON j.capture_id = f.id
              WHERE f.page_id = c.page_id ORDER BY f.received_at, f.id LIMIT 1)
  AND NOT EXISTS (SELECT 1 FROM job j WHERE j.capture_id = c.id
                  AND j.state IN ('queued', 'running'))
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
