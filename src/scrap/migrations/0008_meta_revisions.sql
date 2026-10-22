-- Metadata revisions: every change to a page's kind or tags (by the user in the PWA, or by
-- Claude over MCP) is a row of page_meta_rev, its kind and tags before and after, so it can be
-- seen and reverted. Text keeps its own history in page_rev. Additive, as 0006: the Python
-- step (store.AFTER[8], add_meta_revs) creates the table only if missing, so an older scrap
-- still runs with user_version set back to 7 (it never reads it), and migrating again later
-- is harmless. No backfill: a page's first change records the state it had before. Table:
--   page_meta_rev  id, page_id, author, source ('web' or 'mcp'), kind_before, kind_after,
--                  tags_before, tags_after (JSON arrays, sorted), reverts (the revision a
--                  revert undid, else NULL), created_at, updated_at (the last edit folded in)
SELECT 1;
