"""The store's health checks (#262): each an is: or has: search term, as SQL on a page
p, so a finding is always current and needs no stored report. Search (store.search)
filters by them, GET /api/health counts them (counts). is:outdated is a board's
write-up outdated (writeups.OUTDATED): the owner's to regenerate (only a newly read
photo regenerates one on its own), or scrap enrich --writeups --outdated (#291). What
the scheduled passes refresh on their own is defined here too, but is no finding:
related pages (OUTDATED_RELATED: the nightly --related pass, enrich STALE) and a
topic's synthesis (OUTDATED_TOPIC: the weekly --topics pass, enrich TOPIC_DUE).
Nothing here calls a model.

A fragment is a template: {p} is the page's alias, and the outdated ones' {version} the
placeholder for the current prompt version (? in a search, :version in a pass). A
prompt version of None checks no version (a store whose maker set no prompts).
"""

import logging
import sqlite3
from datetime import date, timedelta
from typing import Any

from .topics import IS_TOPIC
from .writeups import OUTDATED

log = logging.getLogger(__name__)
_unversioned = False  # is:outdated has run with no prompt versions (logged once)
STALE_DAYS = 60  # an open todo not edited for this long is stale
# A review page: one scrap gc made, gathering capture files no page shows (its capture's
# source is gc), whatever it is titled now (orphans.py)
REVIEW = "EXISTS (SELECT 1 FROM capture c WHERE c.page_id = {p}.id AND c.source = 'gc')"
# Every page (not in the trash) linked one way or another to another such page: by a
# [[link]] in its text or its current write-up (either end), a related pick (either
# end), or a topic and its sources in (either end). One set for the whole store, made
# once a query, so is:orphan costs one pass over the pages, not one per page.
LINKED = """
SELECT s.id FROM page s, json_each(wiki_links(s.body)) l JOIN page t ON t.slug = l.value
WHERE s.deleted_at IS NULL AND t.deleted_at IS NULL AND t.id <> s.id
UNION SELECT t.id FROM page s, json_each(wiki_links(s.body)) l
  JOIN page t ON t.slug = l.value
WHERE s.deleted_at IS NULL AND t.deleted_at IS NULL AND t.id <> s.id
UNION SELECT s.id FROM writeup w JOIN page s ON s.id = w.page_id,
  json_each(wiki_links(w.text)) l JOIN page t ON t.slug = l.value
WHERE w.superseded_at IS NULL AND s.deleted_at IS NULL AND t.deleted_at IS NULL
  AND t.id <> s.id
UNION SELECT t.id FROM writeup w JOIN page s ON s.id = w.page_id,
  json_each(wiki_links(w.text)) l JOIN page t ON t.slug = l.value
WHERE w.superseded_at IS NULL AND s.deleted_at IS NULL AND t.deleted_at IS NULL
  AND t.id <> s.id
UNION SELECT r.page_id FROM related r JOIN page s ON s.id = r.page_id
  JOIN page t ON t.id = r.other_id WHERE s.deleted_at IS NULL AND t.deleted_at IS NULL
UNION SELECT r.other_id FROM related r JOIN page s ON s.id = r.page_id
  JOIN page t ON t.id = r.other_id WHERE s.deleted_at IS NULL AND t.deleted_at IS NULL
UNION SELECT s.page_id FROM topic_source s JOIN page t ON t.id = s.topic_id
  JOIN page q ON q.id = s.page_id
WHERE s.excluded = 0 AND t.deleted_at IS NULL AND q.deleted_at IS NULL
UNION SELECT s.topic_id FROM topic_source s JOIN page t ON t.id = s.topic_id
  JOIN page q ON q.id = s.page_id
WHERE s.excluded = 0 AND t.deleted_at IS NULL AND q.deleted_at IS NULL
"""
# Not a gc review page: it gathers files, and is linked to nothing on purpose
ORPHAN = f"({{p}}.id NOT IN ({LINKED}) AND NOT {REVIEW})"
# No tags. Not a topic nor a gc review page: made by a machine with none of their own
UNTAGGED = (
    "NOT EXISTS (SELECT 1 FROM tag g WHERE g.page_id = {p}.id)"
    f" AND NOT {IS_TOPIC} AND NOT {REVIEW}"
)
# An open todo (not done or cancelled), not snoozed now and not due today or later
# (args: today, today: its due date brings it up), whose text, title, kind and tags
# were last changed before the cut-off (args: that day). A status, due date or snooze
# change leaves no date to go by. Not a gc review page (a todo its due date brings up).
STALE = f"""({{p}}.kind = 'todo' AND NOT {REVIEW}
  AND coalesce(json_extract({{p}}.fields, '$.status'), 'open')
    NOT IN ('done', 'cancelled')
  AND NOT coalesce({{p}}.snoozed_until > ?, 0)
  AND NOT coalesce({{p}}.due >= ?, 0)
  AND max({{p}}.updated_at, coalesce((SELECT max(m.updated_at) FROM page_meta_rev m
    WHERE m.page_id = {{p}}.id), '')) < ?)"""
# Sharing a stored file with another page: one of its captures' files is also one of
# another's. Pages in the trash and gc's review pages (which gather files on purpose)
# are left out, on both sides. The files on two or more such pages: once a query.
SHARED = f"""
SELECT cb.sha256 FROM capture_blob cb JOIN capture c ON c.id = cb.capture_id
JOIN page q ON q.id = c.page_id
WHERE q.deleted_at IS NULL AND NOT {REVIEW.format(p="q")}
GROUP BY cb.sha256 HAVING count(DISTINCT q.id) > 1
"""
DUPLICATE = (
    f"(NOT {REVIEW} AND {{p}}.id IN (SELECT c.page_id FROM capture c"
    " JOIN capture_blob cb ON cb.capture_id = c.id"
    f" WHERE cb.sha256 IN ({SHARED})))"
)
# A [[link]] in its text (not in code, not an embed) to no page, or to one in the trash
DANGLING = """EXISTS (SELECT 1 FROM json_each(wiki_links({p}.body)) l
  WHERE NOT EXISTS (SELECT 1 FROM page t WHERE t.slug = l.value
                    AND t.deleted_at IS NULL))"""

# ---- outdated: derived data older than its inputs, or of an older prompt version. Only
# a write-up is a finding (is:outdated); the passes find the rest by the same SQL

# The latest change to what a page's related call or a topic's synthesis reads from its
# images: a current description or text photo ingest read ('' if none)
READ_AT = """coalesce((SELECT max(d.created_at) FROM derived d
    JOIN capture c ON c.id = d.capture_id WHERE c.page_id = {p}.id
    AND d.kind IN ('description', 'ocr') AND d.superseded_at IS NULL), '')"""
# A board page's current write-up outdated (writeups.OUTDATED, beside the worker's DUE)
OUTDATED_WRITEUP = OUTDATED
# A topic with a source in whose synthesis (its current write-up) is of another prompt
# version (unless the owner restored it), or older than the latest change to its
# inputs: the topic page itself (its title or the owner's notes), a source added,
# excluded or back from the trash, or a source's text, trash, summary, write-up or
# what photo ingest read from it. One with none yet is not outdated, only due.
OUTDATED_TOPIC = f"""({IS_TOPIC}
  AND EXISTS (SELECT 1 FROM topic_source s JOIN page q ON q.id = s.page_id
              WHERE s.topic_id = {{p}}.id AND s.excluded = 0 AND q.deleted_at IS NULL)
  AND EXISTS (SELECT 1 FROM writeup w WHERE w.page_id = {{p}}.id
    AND w.superseded_at IS NULL
    AND (coalesce(w.prompt_version <> {{version}} AND w.restored_from IS NULL, 0)
    OR w.created_at < max({{p}}.updated_at, coalesce((
      SELECT max(CASE WHEN s.excluded THEN s.changed_at ELSE max(
        s.changed_at, q.updated_at, coalesce(q.deleted_at, ''),
        coalesce((SELECT e.updated_at FROM enrichment e WHERE e.page_id = q.id), ''),
        coalesce((SELECT x.created_at FROM writeup x WHERE x.page_id = q.id
                  AND x.superseded_at IS NULL), ''),
        {READ_AT.format(p="q")}) END)
      FROM topic_source s JOIN page q ON q.id = s.page_id
      WHERE s.topic_id = {{p}}.id), '')))))"""
# When a page's related pages were last picked (NULL: never)
PICKED = """(SELECT max(r.started_at) FROM enrich_run r WHERE r.page_id = {p}.id
    AND r.status = 'ok' AND json_extract(r.request, '$.purpose') = 'related')"""
# The latest change to what a related call reads: the page's last edit, a reading of its
# images, its current write-up
RELATED_INPUTS = f"""max({{p}}.updated_at, {READ_AT}, coalesce((
    SELECT w.created_at FROM writeup w WHERE w.page_id = {{p}}.id
      AND w.superseded_at IS NULL), ''))"""
# Related pages picked before the latest change to their inputs (never picked: not
# outdated, only due)
OUTDATED_RELATED = f"{PICKED} < {RELATED_INPUTS}"


def outdated(p: str = "p", version: str = "?") -> str:
    """is:outdated as SQL on a page p: a board's write-up outdated (OUTDATED_WRITEUP),
    never a topic's synthesis or related pages, which their passes refresh on their own
    (#291). One placeholder: the write-up's prompt version."""
    return OUTDATED_WRITEUP.format(p=p, version=version)


# The checks, in the order the health screen lists them: (key, value) as a filter
CHECKS = [
    ("is", "orphan"),
    ("is", "untagged"),
    ("is", "stale"),
    ("is", "duplicate"),
    ("has", "dangling"),
    ("is", "outdated"),
]


def condition(
    key: str, value: str, prompts: dict[str, str], today: date | None = None
) -> tuple[str, list[Any]]:
    """A check's SQL on a page p, and its args: prompts are the current prompt versions
    (is:outdated reads writeup's; missing, it is not checked: an empty prompts, as a
    Store nobody set them on has, skips is:outdated's version check, logged once at
    debug level), today the server's day (stale)."""
    global _unversioned
    day = today or date.today()
    if key == "is" and value == "outdated" and not prompts and not _unversioned:
        _unversioned = True
        log.debug("is:outdated: no prompt versions given (Store.prompts): not checked")
    match key, value:
        case "is", "orphan":
            return ORPHAN.format(p="p"), []
        case "is", "untagged":
            return UNTAGGED.format(p="p"), []
        case "is", "stale":
            cut = day - timedelta(days=STALE_DAYS)
            today_ = day.isoformat()
            return STALE.format(p="p"), [today_, today_, cut.isoformat()]
        case "is", "duplicate":
            return DUPLICATE.format(p="p"), []
        case "has", "dangling":
            return DANGLING.format(p="p"), []
        case "is", "outdated":
            return outdated(), [prompts.get("writeup")]
    raise KeyError((key, value))


def counts(
    conn: sqlite3.Connection, prompts: dict[str, str], today: date | None = None
) -> list[dict[str, Any]]:
    """Each check's count of pages (not in the trash), in CHECKS' order: term (as
    typed in a search) and count. One query a check."""
    out = []
    for key, value in CHECKS:
        sql, args = condition(key, value, prompts, today)
        n = conn.execute(
            f"SELECT count(*) FROM page p WHERE p.deleted_at IS NULL AND ({sql})", args
        ).fetchone()[0]
        out.append({"term": f"{key}:{value}", "count": n})
    return out
