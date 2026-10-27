"""The ingest queue's limits and SQL."""

from ..store.constants import IS_FILE
from ..store.roles import FIRST_CAPTURE, TITLE_UNTOUCHED

FAR = "9999-12-31T00:00:00.000Z"  # paused until Resume
MAX_FAILURES = 3
RETRY = 600  # seconds after a charged failure (invalid output: at once)
POLL = 30  # seconds the idle worker sleeps unless woken
PAUSES = ("credit", "auth", "outage", "budget")

REV = "(SELECT max(rev) FROM page_rev WHERE page_id = p.id)"  # a page's text rev
# The oldest ready job, a photo's before any file's (a file may take a minute to
# parse); while the queue is paused, only a file's (IS_FILE: read locally, no model
# call to pause)
CLAIM = f"""
UPDATE job SET state = 'running', updated_at = :now
WHERE id = (
    SELECT j.id FROM job j
    JOIN capture c ON c.id = j.capture_id
    JOIN page p ON p.id = c.page_id
    JOIN blob b ON b.sha256 = j.source_sha256
    WHERE j.state = 'queued' AND j.run_after <= :now AND p.deleted_at IS NULL
      AND ({IS_FILE.format(b="b")}
           OR NOT EXISTS (SELECT 1 FROM queue_state WHERE paused_until > :now))
    ORDER BY {IS_FILE.format(b="b")}, j.run_after, j.id LIMIT 1)
RETURNING id, capture_id, source_sha256, failures, options
"""
# A page's title from its first capture's first photo (roles: the first capture
# decides), while the title is as made (roles.TITLE_UNTOUCHED) and that capture has no
# text
TITLE_CAS = """
UPDATE page SET title = :title, updated_at = :now
WHERE id = :page AND deleted_at IS NULL
  AND {untouched}
  AND EXISTS (SELECT 1 FROM capture c WHERE c.id = :capture AND c.page_id = :page
              AND c.text IS NULL
              AND c.id = {first}
              AND :photo = (SELECT sha256 FROM capture_blob
                            WHERE capture_id = c.id ORDER BY ord LIMIT 1))
""".format(
    untouched=TITLE_UNTOUCHED.format(page=":page"),
    first=FIRST_CAPTURE.format(page=":page"),
)
INSERT_DERIVED = """
INSERT INTO derived (capture_id, source_sha256, kind, version, producer, run_id, author,
                     text, data, superseded_at, created_at)
VALUES (:capture, :photo, :kind, (SELECT coalesce(max(version), 0) + 1 FROM derived
                                  WHERE capture_id = :capture AND source_sha256 = :photo
                                    AND kind = :kind),
        :producer, :run, :author, :text, :data, :superseded, :now)
RETURNING id, version
"""
