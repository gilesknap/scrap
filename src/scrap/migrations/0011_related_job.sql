-- A page's first related call (#255): one enrich job, reason 'related', queued when the
-- page is first read (its first enrich, or photo ingest of its first photo capture). The
-- Python step (store.AFTER[11], add_related_reason) rebuilds enrich_job for its reason
-- CHECK, keeping its rows and the runs' job_id, unless the table takes 'related' already.
SELECT 1;
