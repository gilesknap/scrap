-- Markdown-aware search text (#71): a page's own chunk now holds its text as markdown.py
-- parses it (link text, not addresses; code as typed; a table's cells), not just with link
-- addresses cut by a regex. Nothing changes in the schema: the runner re-indexes every
-- page's own chunk in Python, in this same transaction (store.AFTER[4]), and sets
-- PRAGMA user_version = 4.
SELECT 1;
