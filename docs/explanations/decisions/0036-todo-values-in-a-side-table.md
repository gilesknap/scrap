# 36. A todo's due date, priority and snooze are in a table of their own

Date: 2026-10-27 (migration 0018)

## Status

Accepted. Supersedes the typed `page` columns part of
[ADR 12](0012-kinds-flat-fields-and-typed-todo-columns.md); the rest of that ADR stands.

## Context

[ADR 12](0012-kinds-flat-fields-and-typed-todo-columns.md) made a todo's due date and priority
columns of `page`, and migration 0006 added `snoozed_until` beside them. Most pages are not
todos, so three of the sixteen `page` columns were empty for them, and the todo's own data sat in
the core row of every kind. The columns were also not used as indexes: every filter wraps the
column in `coalesce(p.kind = 'todo' AND ..., 0)`, which hides it from the query planner, so
`page_by_due` and `page_by_snooze` were never chosen (checked with `EXPLAIN QUERY PLAN`).

The schema is about to be squashed into one baseline for 1.0, so this was the last cheap moment
to move them: a data-moving migration is easiest to fold in while the store is small (about 380
pages and 40 todos on the live store).

## Decision

- Migration 0018 creates `page_todo (page_id PRIMARY KEY REFERENCES page(id) ON DELETE CASCADE,
  due, priority, snoozed_until) WITHOUT ROWID`, copies every page that has at least one of the
  three set, drops `page_by_due`, `page_by_snooze` and the three `page` columns, and adds the
  partial indexes `page_todo_by_due` and `page_todo_by_snooze`.
- The per-column `CHECK`s are the ones the columns had (a calendar day `YYYY-MM-DD`; priority
  `high`, `medium` or `low`). A further `CHECK` refuses a row with all three empty, so a row
  exists only while a value is set. Clearing the last value deletes the row
  (`store/todo.py`, `write`).
- Whether a page is a todo is still `page.kind = 'todo'`, not a row in `page_todo`. A todo turned
  into another kind keeps its row, hidden as before, so a stray tap loses nothing
  ([ADR 12](0012-kinds-flat-fields-and-typed-todo-columns.md)). `task_done`, `task_total` and
  `fields` stay on `page`: the task counts are of every page's boxes, not only a todo's.
- `store/todo.py` is the only code that names the table. SQL readers take a correlated scalar
  subquery from `todo.col`, which is NULL for a page with no row, so every existing `coalesce`,
  `NULLS LAST`, `priority:none` and `is:stale` expression means what it did. Everything else
  uses `todo.read` and `todo.write`. `tests/test_todo_gate.py` fails on any other mention of the
  values in SQL.
- The API, MCP and web shapes do not change: a page still carries `due`, `priority` and
  `snoozed_until`. Setting them is still not a revision.

## Consequences

- The migration is not additive. A scrap from before this migration cannot run on a database at schema 18, so
  going back means restoring the pre-upgrade backup (as for migration 16).
- Reading the three values for a list of pages costs a primary-key lookup each in `page_todo`.
  The plans for `due:` and `sort:due` are otherwise the same as before: neither used a due index.
- `tests/test_todo_migration.py` builds a schema 17 database with the real runner, migrates it and
  compares every value, search, list, export and MCP read before and after.
- Tests that pretend an older scrap ran in between (set `user_version` back and migrate again)
  call `tests/old_schema.py`'s `undo_0018` first, as 0018 cannot be run twice.
