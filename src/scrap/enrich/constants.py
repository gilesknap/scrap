"""Enrich: the schemas, limits and SQL."""

import re
from typing import Any

from .. import claude
from ..store import writeups

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["tags", "summary", "title", *claude.INTENT_PROPERTIES],
    "properties": {
        **claude.INTENT_PROPERTIES,
        "tags": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
        "title": {"type": "string"},
    },
}
# Related pages: a call of its own (the nightly pass, and Ask Claude), not on every save
RELATED_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["related"],
    "properties": {"related": {"type": "array", "items": {"type": "integer"}}},
}
# A board page's write-up (#256): a lead of 1-2 sentences, and Markdown sections
WRITEUP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "text"],
    "properties": {"summary": {"type": "string"}, "text": {"type": "string"}},
}
# The tags that mark quoted data in a user turn, and one of them, opening or closing,
# in the data itself (any case, with spaces: < / Page >), to be neutralised
DELIMITERS = ("page", "images", "fetched", "guidance", "writeup")
DELIMITER = re.compile(
    r"<(?=\s*/?\s*(?:" + "|".join(DELIMITERS) + r")\b)", re.IGNORECASE
)
SHORT = 200  # characters: a shorter note gets tags but no summary
MAX_BODY = 12_000  # characters of the page's text sent
MAX_IMAGES = 8_000  # characters of what was read from its images (descriptions, text)
RELATED_BODY = 2_000  # the related call's start of the page's text
RELATED_IMAGES = 3_000  # and of what was read from its images
RELATED_WRITEUP = 2_000  # and of its write-up
MAX_BOARDS = 4  # board images a write-up call is sent (the photos themselves)
WRITEUP_BODY = 6_000  # characters of the page's own text a write-up call is sent
WRITEUP_IMAGES = 12_000  # and of what was read from its board images
MAX_WRITEUP = 20_000  # characters of a write-up kept
MAX_GUIDANCE = 2_000  # characters of the owner's guidance for one
MAX_NEW_TAGS = 5  # Claude's tags added to a page at most
MAX_INVENTED = 2  # of which at most this many not already in use
MAX_RELATED = 5
MAX_SUMMARY = 600
MAX_TITLE = 200
MAX_VOCAB = 600  # tags listed, most used first
MAX_CANDIDATES = 150  # pages in a related call's index (~40 tokens each)
BY_TAGS, BY_WORDS = 90, 60  # of which, at most, sharing tags and matching words
QUERY_WORDS = 24  # distinct words in the full-text search, the page's first ones
WORD = re.compile(r"[^\W_]{4,}")  # a word worth matching: 4 letters or more

CLAIM = """
UPDATE enrich_job SET state = 'running', updated_at = :now
WHERE id = (
    SELECT j.id FROM enrich_job j JOIN page p ON p.id = j.page_id
    WHERE j.state = 'queued' AND j.run_after <= :now AND p.deleted_at IS NULL
      AND NOT EXISTS (SELECT 1 FROM enrich_job r
                      WHERE r.page_id = j.page_id AND r.state = 'running')
    ORDER BY j.run_after, j.id LIMIT 1)
  AND NOT EXISTS (SELECT 1 FROM queue_state WHERE paused_until > :now)
RETURNING id, page_id, reason, failures
"""
# A saved link's title, while it is still the link as captured (no edit since)
TITLE_CAS = """
UPDATE page SET title = :title
WHERE id = :page AND deleted_at IS NULL
  AND title = (SELECT title FROM page_rev WHERE page_id = :page AND rev = 1)
  AND title = :url
  AND NOT EXISTS (SELECT 1 FROM page_rev WHERE page_id = :page AND rev > 1)
"""


# The run's fetch field for a save's re-reading of a link page: skipped, not failed
SAVE_REREAD = "skipped: save re-read"


# A page's images (each distinct image file of its captures once, in order) and what
# photo ingest read from each: its current description and text (NULL if none)
IMAGES = """
WITH once AS (
    SELECT c.id AS capture_id, cb.sha256, c.received_at, cb.ord,
           row_number() OVER (PARTITION BY cb.sha256
                              ORDER BY c.received_at, c.id, cb.ord) AS copy
    FROM capture c JOIN capture_blob cb ON cb.capture_id = c.id
    JOIN blob b USING (sha256)
    WHERE c.page_id = ? AND b.mime LIKE 'image/%')
SELECT
    (SELECT d.text FROM derived d WHERE d.capture_id = o.capture_id
       AND d.source_sha256 = o.sha256 AND d.kind = 'description'
       AND d.superseded_at IS NULL) AS description,
    (SELECT d.text FROM derived d WHERE d.capture_id = o.capture_id
       AND d.source_sha256 = o.sha256 AND d.kind = 'ocr'
       AND d.superseded_at IS NULL) AS text
FROM once o WHERE o.copy = 1 ORDER BY o.received_at, o.capture_id, o.ord
"""


# Pages whose related pages are older than their last change, or than what photo ingest
# last read from one of their images (a current description or text), or than their
# current write-up, or never picked
STALE = """
SELECT p.id FROM page p WHERE p.deleted_at IS NULL AND (:all OR coalesce((
    SELECT max(r.started_at) FROM enrich_run r WHERE r.page_id = p.id
      AND r.status = 'ok' AND json_extract(r.request, '$.purpose') = 'related'), '')
  < max(p.updated_at, coalesce((
    SELECT max(d.created_at) FROM derived d JOIN capture c ON c.id = d.capture_id
    WHERE c.page_id = p.id AND d.kind IN ('description', 'ocr')
      AND d.superseded_at IS NULL), ''), coalesce((
    SELECT w.created_at FROM writeup w WHERE w.page_id = p.id
      AND w.superseded_at IS NULL), '')))
ORDER BY p.created_at LIMIT :limit
"""
# Board pages (writeups.HAS_BOARD) with no write-up (or every one), oldest first
BOARDS = f"""
SELECT p.id FROM page p WHERE p.deleted_at IS NULL
  AND {writeups.HAS_BOARD.format(p="p")}
  AND (:all OR NOT EXISTS (SELECT 1 FROM writeup w WHERE w.page_id = p.id))
ORDER BY p.created_at LIMIT :limit
"""
