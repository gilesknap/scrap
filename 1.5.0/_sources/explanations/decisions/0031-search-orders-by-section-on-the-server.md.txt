# 31. Search orders results by section on the server

Date: 2026-10-26

## Status

Accepted

## Context

The PWA groups a list in sections (Later by type, Todos by Now or Due, any list A to Z or by
tag). It grouped the hits it had fetched, 100 at a time. Pages came back in the search's order,
so a section could start on one page and continue on the next, and "Show more" re-sorted rows
the reader had already seen.

## Decision

- `group:G` (`letter`, `tag`, `type`, `now`, `due`) is a search term. The server puts a page in
  a section by the same rules as the app and orders by section first, then by the search's own
  order (or A to Z for `group:letter`). Paging by `offset` then never splits a section. The
  section keys are SQL functions registered on the connection (`store/grouping.py`); done and
  cancelled pages sort last, as the Done fold.
- Later has a medium, `media_type` (book, article, film, tv, video, podcast, music, game),
  from which its subtype (read, watch, listen, play) follows. `media:` and `later:` filter by
  them. A saved link gets its medium from the site's address (YouTube: video, Goodreads: book,
  Spotify by its path ...) and, failing that, from the model's reading of the page; the user's
  choice in the editor or over MCP (`edit_meta` `fields`) wins.
- `edit_meta` can set `media_type` and `subtype`. A field edit is a metadata revision like a
  kind or tag edit, so `revert` undoes it. Migration 15 adds `page_meta_rev.fields_was` (the
  values a field had before), because a revert of a changed field needs them; `fields_added`
  alone could only say a field was new.
- `due:` takes a time ahead as `after:` takes one back: `due:<=7d`, `due:>=2w`.
- Search hits carry `tags`, for `group:tag`.

## Consequences

The client sends the group in force with the query and draws the sections it is given. A new
group is a key function in `grouping.py` and a section list in `groups.ts`, which must agree
(the tests assert the same order for both). Revisions made before migration 15 have an empty
`fields_was`, which is correct: they never changed a field.
