-- Claude's write-up of a board page (#256): one enrich job, reason 'writeup', and its
-- versions apart from the page's text. The Python step (store.AFTER[12], add_writeups)
-- rebuilds enrich_job for its reason CHECK, keeping its rows and the runs' job_id,
-- unless the table takes 'writeup' already, and creates the tables only if missing:
--   writeup           a page's write-ups, versioned, one current
--   writeup_guidance  the owner's note for the next one
SELECT 1;
