-- Claude's topic pages (#261): one enrich job, reason 'topic' (a topic's synthesis, kept
-- as its write-up), a marker table and its sources. The Python step (store.AFTER[13],
-- add_topics) rebuilds enrich_job for its reason CHECK, keeping its rows and the runs'
-- job_id, unless the table takes 'topic' already, and creates the tables only if missing:
--   topic         which pages are topics, each with its key (never made again)
--   topic_source  a topic's sources, the owner's exclusions kept
--   topic_run     the discovery calls (of no one page), counted in the daily budget
SELECT 1;
