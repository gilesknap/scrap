"""Enrich: the schemas, limits and SQL."""

import re
from typing import Any

from .. import claude

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
SHORT = 200  # characters: a shorter note gets tags but no summary
MAX_BODY = 12_000  # characters of the page's text sent
MAX_NEW_TAGS = 5  # Claude's tags added to a page at most
MAX_INVENTED = 2  # of which at most this many not already in use
MAX_RELATED = 5
MAX_SUMMARY = 600
MAX_TITLE = 200
MAX_VOCAB = 600  # tags listed, most used first
MAX_CANDIDATES = 150  # pages in a related call's index (~40 tokens each)
BY_TAGS, BY_WORDS = 90, 60  # of which, at most, sharing tags and matching words
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


# Pages whose related pages are older than their last change (or never picked)
STALE = """
SELECT p.id FROM page p WHERE p.deleted_at IS NULL AND (:all OR NOT EXISTS (
    SELECT 1 FROM enrich_run r WHERE r.page_id = p.id AND r.status = 'ok'
      AND json_extract(r.request, '$.purpose') = 'related'
      AND r.started_at >= p.updated_at))
ORDER BY p.created_at LIMIT :limit
"""
