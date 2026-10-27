-- The trash's history (#332): a row of page_trash_rev each time a page goes to the trash
-- or comes back (the PWA's delete and undo, MCP's trash_pages and undelete), so revisions
-- and its recent-changes feed show deletes, and the pages one call moved share a batch id
-- that undelete brings back at once. The Python step (store.AFTER[17], add_trash_revs)
-- creates the table only if missing, so migrating again is harmless; an older scrap never
-- reads it. No backfill: a page already in the trash has no row. Table:
--   page_trash_rev  id (AUTOINCREMENT), page_id, action ('trash' or 'restore'), author,
--                   source ('web' or 'mcp'), batch_id (else NULL), created_at; indexed by
--                   page and batch_id
SELECT 1;
