-- Kinds memory and reference become document (#298). The Python step (store.AFTER[14],
-- collapse_kinds) tags the pages first (memory; entity, for a reference page that is
-- not a topic), changes their kind, keeps kind_fixed, maps the old kinds in
-- page_meta_rev to document, indexes the tagged pages again, and edits page's kind
-- CHECK to note, todo, consume, whiteboard and document. Safe to run again.
SELECT 1;
