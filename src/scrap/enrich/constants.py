"""Enrich: the schemas, limits and SQL."""

import re
from typing import Any

from .. import claude
from ..query import MEDIA
from ..store import health, roles, writeups
from ..store.constants import IS_FILE
from ..store.constants import SHORT as SHORT  # characters: see there

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["tags", "summary", "title", "media_type", *claude.INTENT_PROPERTIES],
    "properties": {
        **claude.INTENT_PROPERTIES,
        "tags": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
        "title": {"type": "string"},
        "media_type": {"type": "string", "enum": [*MEDIA, ""]},
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
# A topic's synthesis (#261): as a write-up, a lead and Markdown sections (its own
# object, so the prompt's version and a test's fake can tell the calls apart)
TOPIC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "text"],
    "properties": {"summary": {"type": "string"}, "text": {"type": "string"}},
}
_NUMBERS = {"type": "array", "items": {"type": "integer"}}
# Topic discovery (#261): new topics, each a title, a key and its sources by number;
# and new sources for existing topics, by their numbers
DISCOVERY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["new", "add"],
    "properties": {
        "new": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "key", "sources"],
                "properties": {
                    "title": {"type": "string"},
                    "key": {"type": "string"},
                    "sources": _NUMBERS,
                },
            },
        },
        "add": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["topic", "sources"],
                "properties": {"topic": {"type": "integer"}, "sources": _NUMBERS},
            },
        },
    },
}
# The tags that mark quoted data in a user turn, and one of them, opening or closing,
# in the data itself (any case, with spaces: < / Page >), to be neutralised
DELIMITERS = (
    "page", "images", "files", "fetched", "guidance", "writeup", "source", "notes",
    "index", "topics",
)  # fmt: skip
DELIMITER = re.compile(
    r"<(?=\s*/?\s*(?:" + "|".join(DELIMITERS) + r")\b)", re.IGNORECASE
)
MAX_BODY = 12_000  # characters of the page's text sent
MAX_IMAGES = 8_000  # characters of what was read from its images (descriptions, text)
MAX_FILES = 8_000  # and from its files (a PDF's or text file's text, #378), on Ask
AUTO_FILES = 4_000  # and on a file page's own reading, unasked (ADR 38)
RELATED_BODY = 2_000  # the related call's start of the page's text
RELATED_IMAGES = 3_000  # and of what was read from its images
RELATED_FILES = 3_000  # and from its files, on Ask
AUTO_RELATED_FILES = 1_500  # and on a file page's own reading, unasked (ADR 38)
RELATED_WRITEUP = 2_000  # and of its write-up
MAX_BOARDS = 4  # board images a write-up call is sent (the photos themselves)
WRITEUP_BODY = 6_000  # characters of the page's own text a write-up call is sent
WRITEUP_IMAGES = 12_000  # and of what was read from its board images
MAX_WRITEUP = 20_000  # characters of a write-up kept
MAX_GUIDANCE = 2_000  # characters of the owner's guidance for one
TOPIC_INPUT = 60_000  # characters of a synthesis call's sources in all
TOPIC_SOURCE = 6_000  # and of one source, at most
TOPIC_NOTES = 4_000  # characters of the topic page's own text (the owner's notes)
MAX_TOPIC_SOURCES = 40  # sources a synthesis is sent (first added first)
TOPIC_INDEX = 2_000  # pages in a discovery call's index (~40 tokens each), newest
MAX_NEW_TOPICS = 5  # new topics a discovery pass makes at most
MIN_SOURCES = 2  # a new topic's sources at least (the prompt asks for 3, or 2)
MAX_TOPIC_TITLE = 120  # characters
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
# (roles.TITLE_UNTOUCHED)
TITLE_CAS = f"""
UPDATE page SET title = :title
WHERE id = :page AND deleted_at IS NULL
  AND {roles.TITLE_UNTOUCHED.format(page=":page")}
  AND title = :url
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


# A page's files (each distinct readable file, IS_FILE, of its captures once, in
# order) with its name and what file ingest read from it: its current text (NULL if
# not read yet, or it could not be)
FILES = f"""
WITH once AS (
    SELECT c.id AS capture_id, cb.sha256, cb.filename, c.received_at, cb.ord,
           row_number() OVER (PARTITION BY cb.sha256
                              ORDER BY c.received_at, c.id, cb.ord) AS copy
    FROM capture c JOIN capture_blob cb ON cb.capture_id = c.id
    JOIN blob b USING (sha256)
    WHERE c.page_id = ? AND {IS_FILE.format(b="b")})
SELECT o.filename AS name,
    (SELECT d.text FROM derived d WHERE d.capture_id = o.capture_id
       AND d.source_sha256 = o.sha256 AND d.kind = 'ocr'
       AND d.superseded_at IS NULL) AS text
FROM once o WHERE o.copy = 1 ORDER BY o.received_at, o.capture_id, o.ord
"""
# A page :page made from a file, with no title of its own: its first capture is a
# file's with no text (titled by the time it came), and its title is as made
# (roles.TITLE_UNTOUCHED). Enrich titles it, as photo ingest titles a photo's (#378).
_FIRST = roles.FIRST_CAPTURE.format(page=":page")
FILE_UNTITLED = f"""
{roles.TITLE_UNTOUCHED.format(page=":page")}
  AND EXISTS (SELECT 1 FROM capture c WHERE c.id = {_FIRST}
              AND c.kind = 'file' AND c.text IS NULL)
"""
# A page's summary, if an Ask made it (its run's job was an Ask's: it may have read the
# page's files, which nothing else sends); none once that run or job is pruned
ASKED_SUMMARY = """
SELECT e.summary FROM enrichment e JOIN enrich_run r ON r.id = e.run_id
JOIN enrich_job j ON j.id = r.job_id WHERE e.page_id = ? AND j.reason = 'ask'
"""
UNTITLED_FILE = f"SELECT 1 FROM page WHERE id = :page AND {FILE_UNTITLED}"
FILE_TITLE_CAS = f"""
UPDATE page SET title = :title
WHERE id = :page AND deleted_at IS NULL AND {FILE_UNTITLED}
"""


# Pages whose related pages are due: never picked, or outdated (health.OUTDATED_RELATED:
# older than their last change, than what photo ingest last read from one of their
# images, or than their current write-up), or every one with :all; oldest first
STALE = f"""
SELECT p.id FROM page p WHERE p.deleted_at IS NULL AND {roles.NOT_PINNED.format(p="p")}
  AND (:all OR {health.PICKED.format(p="p")} IS NULL
    OR {health.OUTDATED_RELATED.format(p="p")})
ORDER BY p.created_at LIMIT :limit
"""
# Board pages (roles.HAS_BOARD) with no write-up; with :outdated, those with an
# outdated one instead (writeups.OUTDATED, :version the write-up prompt's: never one the
# owner restored); with :all, every one. Oldest first.
BOARDS = f"""
SELECT p.id FROM page p WHERE p.deleted_at IS NULL
  AND {roles.HAS_BOARD.format(p="p")}
  AND CASE WHEN :all THEN 1
    WHEN :outdated THEN {writeups.OUTDATED.format(p="p", version=":version")}
    ELSE NOT EXISTS (SELECT 1 FROM writeup w WHERE w.page_id = p.id) END
ORDER BY p.created_at LIMIT :limit
"""
# Topic pages (not in the trash, with a source in) whose synthesis is due, none
# queued or running: every one with :all, else one with none, or outdated
# (health.OUTDATED_TOPIC: of another prompt version, :version, unless the owner
# restored it: Restore is kept; or older than the latest change to its inputs: the
# topic page itself, a source added, excluded or back from the trash, or a source's
# text, trash, summary, write-up or what photo ingest read from it). Those with none
# first.
TOPIC_DUE = f"""
SELECT p.id FROM topic t JOIN page p ON p.id = t.page_id
LEFT JOIN writeup w ON w.page_id = p.id AND w.superseded_at IS NULL
WHERE p.deleted_at IS NULL
  AND EXISTS (SELECT 1 FROM topic_source s JOIN page q ON q.id = s.page_id
              WHERE s.topic_id = p.id AND s.excluded = 0 AND q.deleted_at IS NULL)
  AND NOT EXISTS (SELECT 1 FROM enrich_job j WHERE j.page_id = p.id
                  AND j.state IN ('queued', 'running'))
  AND (:all OR w.id IS NULL
    OR {health.OUTDATED_TOPIC.format(p="p", version=":version")})
ORDER BY w.created_at IS NOT NULL, w.created_at, p.created_at LIMIT :limit
"""
