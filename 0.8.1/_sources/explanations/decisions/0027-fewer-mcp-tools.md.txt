# 27. Fewer MCP tools: recent, todos and revert_text folded away

Date: 2026-10-25

## Status

Accepted

## Context

The MCP server offered fifteen tools. Models choose better among fewer, and three of them did
nothing another tool could not: `recent` listed pages by `updated_at` (what `search` does for a
query of filters alone), `todos` was one fixed search query with a sort, and `revert_text` was a
second undo beside `revert`.

## Decision

- `search` takes an empty `query`, which lists the most recently changed pages. `recent` is gone
  (`kind:K` replaces its `kind`).
- `todos` is gone. Its list is `search` with `kind:todo -is:done -is:cancelled -is:snoozed
  sort:due` (or `sort:priority`; the tool did exactly this).
- `revert_text` is `revert` with `page` and `to_rev` (and `rev`, `restore_title`,
  `allow_empty`). `revert` takes exactly one of `revision`, `batch` or `page` with `to_rev`. The
  text form is refused with `SCRAP_MCP_CONTENT_EDIT=0`, as `revert_text` was unlisted.
- `rename_tag` stays. It renames nested tags, refuses a name under the old one, needs `merge` to
  join two tags in use and counts trashed pages: none of that fits `edit_meta`'s add, remove and
  set of exact tags without overloading it.
- `/sc-session` is `/sc-summarise all`.

## Consequences

Twelve tools. Clients that allow or deny `mcp__scrap__recent`, `todos` or `revert_text` by name
need `search` and `revert` instead. Nothing is lost: every call maps to one of the new forms.
