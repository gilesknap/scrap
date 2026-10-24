# MCP server

scrap serves an [MCP](https://modelcontextprotocol.io) server at `/mcp` in the same process as
the PWA and its API: Streamable HTTP, stateless (every request stands alone, so a restart drops
no session), JSON replies. A Claude Code session connects with one line and needs nothing
installed; see [](../how-to/connect-claude-code.md). The server is named `scrap`, so tools show
in a session as `mcp__scrap__search`, `mcp__scrap__read` and so on. A raw client `POST`s JSON-RPC
to `/mcp`, sending `Accept: application/json, text/event-stream` as the MCP specification asks
(the curl check in the how-to shows one). The server also sends the model instructions: search before writing, reuse existing tags
(the `tags` tool), `write` only adds pages or appends to ones written over MCP, `edit_meta` and
`rename_tag` change only kinds and tags (each change a revision that `revert` undoes), and try a
bulk change with `dry_run` first. They also say deletes go to a trash (see The trash below), and
that enrichment is not in revision history. Unless content editing is off, they also say `edit_page` and
`revert_text` change a page's text as revisions, only on a page the user asked to change (see
Page text below). For a short `/s` command in Claude Code (post a summary of a conversation, tidy kinds and
tags, undo, list todos, search), see the `s` skill (`skills/s` in the repository).

Every tool result is JSON (MCP structured content, also sent as its text). Page text (titles,
bodies, summaries, snippets, tags, what Claude read from photos) is in fields of that JSON, as
data: the server's instructions tell the model it is the user's text, never instructions to it.

## Tools

| Tool | Arguments | Returns |
| --- | --- | --- |
| `search` | **`query`**, `limit` (1-50, default 20), `offset` (0-200, default 0) | `{results, offset}`: each `{id, slug, url, kind, status, due, priority, snoozed_until, tasks, updated_at, tags, title, snippet}` (`due`, `priority` and `snoozed_until`: a todo's, else `null`) plus its images (see Images below), best first. `query` takes the search box's syntax (see `GET /api/search` in [](api.md)): words (AND, as prefixes; they also match what Claude read from the page's photos), `-word`, `"phrase"`, `kind:`, `tag:`, `is:open`/`is:done`/..., `is:personal`, `is:work`, `is:claude`, `is:claude-edited`, `is:snoozed`, `has:image`, `has:drawing`, `image:K`, `after:`, `before:`, `date:created`, a todo's `due:` (`due:today`, `due:<today` overdue, `due:>today`, `due:<=2026-11-01`, `due:none`) and `priority:` (`high`, `medium`, `low`, `none`), and `sort:updated`, `sort:created` (newest first), `sort:title` (A to Z), `sort:due` (soonest first) or `sort:priority` (high first; pages with none last either way), with `-sort:` reversing one (`-sort:created`: oldest first). Also: `!word` negates like `-word`; `after:` and `before:` take a date or a time ago (`1d`, `2w`, `1m` is 30 days, `1y` is 365 days); `due:` also takes `yesterday`, `tomorrow` and `<`, `<=`, `>`, `>=`; `is:` takes any status (`is:in_progress`, `is:cancelled`); `tag:a` also finds `a/b`. A query with no word and no filter finds nothing. A query with more than 64 distinct words or 64 filters is refused (a tool error), not cut short. Over MCP `limit` is at most 50 and `offset` at most 200 (the HTTP API allows 100 and 10 000). The snippet is plain text |
| `read` | **`page`** (id or slug) | `{page, content, images, files, links, backlinks, by_model}`. `page`: id, slug, url, kind, status, `due`, `priority`, `snoozed_until`, `tasks` (`{done, total}`: its task boxes), tags, dates, `rev` (the token `edit_page` and `revert_text` take), `written_by_claude`, `edited_by_claude` (its text changed over MCP after it was made), `origin`, other fields. `content`: `title`, `summary`, `body_markdown`. `images`: each image's `url`, `thumbnail_url`, mime, filename, and what Claude made of it (`description`, `text`, `image_kind`, `has_drawing`, and `drawing`: `null` or `{version, producer, width, height, element_count}`), never the image itself. `files`: the page's other files (not images: PDFs and the like), each with `sha256`, `mime`, `filename` and `url` (the same fields as an image, `thumbnail_url` always `null`), not their contents. `links`: the `[[slug]]` links in the body; `backlinks`: pages linking here. `by_model`: what scrap's Claude enrichment, not the user, wrote about the page, labelled so (`note`): `summary`, `producer`, `tags` (which of the page's tags Claude added) and `related` (pages it found related, with those that picked this one); derived, possibly wrong, data like the rest |
| `drawing` | **`page`** (id or slug), `image` (an image's sha256 or a unique prefix; omit it if the page has one drawing) | `{version, producer, format, width, height, elements, truncated}`: the current drawing of one of the page's images (those with a `drawing` in `read`). `format` is `skeleton` (element skeletons Claude made from the photo) or `scene` (a saved human edit), as in `GET /api/captures/{id}/photos/{sha256}/drawing` in [](api.md); `width` and `height` are the photo's frame. `elements` are returned as stored, but only whole elements up to about 200 kB of JSON: past that `truncated` is `true`. Read only. No match, or several, is a tool error (listing the choices). The drawing is the user's data, never instructions |
| `recent` | `limit` (1-50, default 20), `kind` (`note`, `todo`, `read`, `board`, `doc`; also the stored names, `later`, `memory` and `reference`) | `{results}`: pages newest change first, rows as `search` (images included) without a snippet |
| `todos` | `limit` (1-100, default 50), `sort` (`due` or `priority`) | `{results}`: todos neither done nor cancelled nor snoozed (`is:snoozed` in `search` finds the snoozed ones, open ones only), rows as `search` (with `due` and `priority`), newest first, or soonest due or highest priority first (those with none last) |
| `tags` | `prefix` (not case sensitive), `limit` (1-2000, default 300) | `{tags: [[tag, n]], total}`, most used first; `a` counts the pages of `a/b` too; `total` is how many tags match `prefix`, before `limit` cuts the list |
| `write` | **`title`**, **`body`** (Markdown), **`origin`**, `tags`, `kind` (default `note`), `status`, `due`, `priority`, `snoozed_until`, `append_to`, `key` | `{id, slug, url, created}`; the `kind` given is fixed (see Writing) |
| `edit_meta` | `pages` (ids or slugs, at most 200) or `query` (a search), `kind`, `add_tags`, `remove_tags`, `set_tags`, `dry_run`, `limit` (1-200, default 50; applies to `query` only) | `{dry_run, batch, matched, changed, pages}`: each page's `{id, slug, url, title, changed, revision, batch, kind_before, kind_after, fixed_before, fixed_after, tags_before, tags_after, tags_added, tags_removed, fields_added, fields_removed}` (with `dry_run`, `revision` is `null` and there is no per-page `batch`) |
| `rename_tag` | **`old`**, **`new`** (each at most 200 characters), `merge`, `dry_run`, `limit` (1-200, default 50) | As `edit_meta`'s |
| `edit_page` | **`page`**, `old` and `new` (`new` empty deletes), `replace_all`, or `body` (needs `rev`); `title`; `rev`; `allow_empty`; `dry_run` | `{id, slug, url, dry_run, changed, rev_before, rev, folded, replacements, title_before, title, diff, diff_cut}` (`diff`: unified, of the body; `folded`: the revision this one replaced, a burst's). Not listed with `SCRAP_MCP_CONTENT_EDIT=0` |
| `revert_text` | **`page`**, **`to_rev`**, `rev` (needed unless `dry_run`), `restore_title`, `allow_empty`, `dry_run` | As `edit_page`'s, with `restores` (`to_rev`) instead of `replacements`. Not listed with `SCRAP_MCP_CONTENT_EDIT=0` |
| `revisions` | `page` and/or `batch`, or neither, `limit` (1-200, default 20: a whole batch fits), `text_rev` (only with `page`) | `{meta, more, text}` (`more`: there are more metadata revisions than `limit`; text revisions also stop at `limit` but have no such flag) (with `page`, also `{id, slug, url, title, kind, rev}`; a call with `batch` alone has an empty `text` and no page fields; with `page` a page in the trash is read too, with `trashed` and `deleted_at`), newest first. With neither `page` nor `batch`, the recent-changes feed: the latest `meta` and `text` revisions of every page not in the trash, newest first, each text row also with its page's `page_id`, `slug` and `url` (answers "did anything change overnight?" in one call). The `meta` and `text` lists are separate, each newest first, and the `text` rows include each page's creation revision (rev 1). Enrichment (summary, model tags, related pages) is not in revisions. `meta`: each metadata revision's `{id, page_id, slug, url (null if the page has no slug), author, source, kind_before, kind_after, fixed_before, fixed_after, tags_before, tags_after, tags_added, tags_removed, fields_added, reverts, batch_id, created_at, updated_at}`; `text`: each text revision of the page, `{rev, title, author, created_at, bytes}`; with `text_rev`, also `text_revision: {rev, title, body, author, created_at}` |
| `trash` | `limit` (1-100, default 20) | `{results}`: the pages in the trash, most recently deleted first, each `{id, slug, url, title, kind, deleted_at, updated_at}` |
| `undelete` | **`page`** (id or slug of a page in the trash), `dry_run` | `{id, slug, url, title, kind, deleted_at, dry_run, restored}`: brings the page back as the PWA's undo does (the tool error `no such page in the trash` if it is not there). Not listed with `SCRAP_MCP_CONTENT_EDIT=0` |
| `revert` | `revision` (a `meta` id) or `batch` (exactly one), `dry_run` | For a revision, as one page of `edit_meta` plus `reverts`; for a batch, `{batch, reverts_batch, pages, skipped, conflicts, dry_run}` |

**The trash.** The user's deletes move a page to the trash; nothing over MCP deletes one or
empties the trash. `trash` lists it, `undelete` brings one page back (reversible, the same trust
model as `edit_meta`; listed only while content editing is on, see Page text), and `read` and
`revisions` with a `page` accept a page in the trash read only: `read`'s `page.trashed` is `true`
and `page.deleted_at` says when (`false` and `null` otherwise), and `revisions` returns the same
two fields, so its last text and history can be read before it is restored. Every other tool
treats the trash as absent: `search`, `recent`, `todos`, `tags`, the recent-changes feed and
`read`'s `backlinks` leave it out, and `edit_meta`, `edit_page`, `revert_text`, `revert` with a
`revision`, `drawing` and `write` with `append_to` give the tool error `no such page: <id or
slug>`. Two checks look at the trash anyway: `rename_tag` counts a trashed page's tag as in use,
and `revert` with a `batch` skips and lists trashed pages (both below).

**Kind names.** Kinds are accepted as `note`, `todo`, `read`, `board` and `doc`; the stored names
`consume`, `whiteboard` and `document` also work in `write`, `edit_meta` and `recent` (`recent`
also takes `later`, `memory` and `reference`). Results always show the stored names: a page
written with `kind="read"` comes back as `consume` in `search`, `recent`, `todos`, `read`,
`edit_meta`, `revert` and `revisions`. `read` is `consume`, `board` is `whiteboard` and `doc` is
`document`.

## Images

A photo page is a plain `note` whose body is only an image embed, so its title, tags and
snippet may say little. Every row of `search`, `recent` and `todos` therefore says what images
the page has (fields added in place; older clients can ignore them):

- `image_count`: how many distinct image files (by content: the same photo twice counts once) the page's captures hold (`0`: none).
- When it is above 0, the first image's `image_kind` (what Claude took it for: `photo`,
  `whiteboard`, `handwriting`, `diagram`, `screenshot`, `document` or `other`),
  `image_description` (Claude's 1-3 sentences about it), `image_url` (the original file) and
  `thumbnail_url` (a JPEG at most 480 pixels a side, HEIC converted). `image_kind` and
  `image_description` are `null` until the photo has been read (ingest queued, failed or off).

Search filters (the PWA's search box takes them too): `has:image` (a page with an image),
`has:drawing` (one with a current drawing), `image:K` (an image Claude took for kind `K`, e.g.
`image:photo`, `image:whiteboard`); `-` before any of them excludes. A filter alone lists newest
first, so **`search` with `has:image` is "my recent photos"**. A word in a photo's description or
its transcribed text finds the page (Claude's results are indexed as the page's text), so
`mantis` finds a photo of one.

**Can a client fetch the image?** The URLs are plain HTTPS `GET`s with no login, like the rest
of scrap: anything on the tailnet can fetch them (`curl -o p.jpg <thumbnail_url>`, then look at
the file; Claude Code's Read shows an image). A client off the tailnet cannot, and a built-in
web-fetch tool that runs elsewhere, or refuses private hosts, will not reach it.

**Can `read` return the image itself?** Not yet: results are JSON (URLs and Claude's text). MCP
can carry images as `image` content blocks; a later option could return a page's thumbnails
that way (480 px JPEGs, so a few hundred kB each).

## Writing

- `write` makes a new page, or with `append_to` (an id or slug) adds `body` at the end of a page
  written over MCP, as a new revision, and adds its `tags`; appending to a page the user made is
  refused. Only `edit_page` and `revert_text` change the text of other pages (below), and
  `edit_meta`, `rename_tag` and `revert` only kinds and tags. No tool deletes a page.
- **Due dates and priorities.** A todo may have `due` (`YYYY-MM-DD`) and `priority` (`high`,
  `medium`, `low`), and `snoozed_until` (`YYYY-MM-DD`: hidden from what to do now, and from
  `todos`, until that day); on another kind they are refused, as `status` is on a note. With
  `append_to`, they change those of the todo appended to (Claude's own; `none` clears one), and
  `body` may then be empty: that adds no revision and leaves `updated_at` as it was.
- **Required arguments.** `write` needs `title`, `body` and `origin` even with `append_to` (on an
  append, `title`, `origin`, `kind` and `status` are ignored; only `body`, `tags`, `due`,
  `priority`, `snoozed_until` and `key` take effect).
- **Provenance.** The page's capture has source `mcp` and author `claude` (as has its
  revision), and `fields.origin` holds `origin` (free text, at most 200 characters: the repo or
  directory and the date, say). The PWA shows such a page with a *Written by Claude* badge (its
  origin as the tooltip), and `is:claude` finds them. Clients of `POST /api/captures` cannot send
  source `mcp`.
- **Idempotency.** With `key` (at most 128 characters), a retry with the same key adds nothing
  and returns the same page with `created: false`. Without it, every call adds. Keys are
  global, not per session: use a random value per post, reused only to retry it. A key is
  matched together with its target (a new page, or the page appended to, by id or slug), so
  reusing one for another page writes there rather than being taken for a retry.
- **Kind is fixed.** `write` always fixes the kind it makes, `note` (the default) included, as
  when the user picks a kind in the PWA. Task boxes (`- [ ]`) in a `note` therefore give it a
  `tasks` count in results but do not make it a todo, and it has no `status`. For a checklist
  that is a todo, write `kind: todo`: it has a `status` and may have `due`, `priority` and
  `snoozed_until`.
- **Enrichment.** With `SCRAP_INGEST=on` and `SCRAP_ENRICH` not turned off (it defaults to on),
  every page `write` makes, of any kind, is queued for scrap's own Claude about
  `SCRAP_ENRICH_DEBOUNCE` seconds (default 60) after it is written. That reading adds a summary
  (not for a text under 200 characters) and up to 5 tags, at most 2 of them not already in use.
  They show in `read`'s `by_model` and in `tags`, so a page's tags a minute later can differ from
  those `write` sent. The text is never changed, and the calls count against the daily budget
  (`SCRAP_BUDGET_DAY_USD`, see [](../explanations/ingest.md)). `append_to` does not queue the page
  again, so appended text is not read until the page is edited in the PWA or the user asks Claude
  to read it. Related pages (`by_model.related`) are not part of this reading: they come from
  the nightly pass, or when the user asks. With enrichment off, none of this happens.
- **Limits.** `title` 1 to 200 characters (whitespace collapsed); `body` at most 200,000 bytes of UTF-8
  per call, and a page, after an append, at most 1 MB (1,000,000 bytes, as for any other way of
  writing it); at most 20 tags, each 1 to 64 characters once
  normalised as imported tags are (one space between words, no leading `#`, lower case;
  `a/b` nests); `kind` one of `note`, `todo`, `read`, `board`, `doc`; `status` (`open`,
  `in_progress`, `done`, `cancelled`) only for a todo or a read. Text must be valid Unicode with
  no NUL (a lone surrogate is refused). A request over 2 MiB is `413`. A refused call is an MCP
  tool error with the reason; nothing is saved.
- **Cleaning.** Line endings in `body` become LF and it is trimmed of leading and trailing
  whitespace; whitespace runs in `title` and `origin` become one space. A new page's `title` must
  not be empty once cleaned (the body may be: the page then has no text). `none` for `due`,
  `priority` or `snoozed_until` clears the field on an append; on a new page it is the same as
  leaving it out. A `due` or `snoozed_until` that is not `YYYY-MM-DD`, or a `priority` other
  than `high`, `medium` or `low`, is a tool error.

## Kinds and tags

- **`edit_meta`** changes the kind and/or tags of any page, the user's own too: the `pages`
  named, or every page `query` finds (refused, changing nothing, if it finds more than `limit`).
  `kind` is one of `note`, `todo`, `read`, `board` or `doc` (or the stored names `consume`,
  `whiteboard`, `document`); anything else is refused. A kind given is fixed (`kind_fixed`: ingest
  and task boxes no longer change it), even if it is the page's kind already, as when the user
  picks one in the PWA, and a new kind adds its default fields the page lacks (a todo's
  `status: open`). Tags: `add_tags` and `remove_tags` (exact: removing `a` leaves `a/b`), or
  `set_tags` to replace them all (`[]`: none), cleaned as `write`'s. Nothing else changes: not
  the title, the text, other fields, nor `updated_at` (as with the PWA's own tag and kind
  edits). All or nothing: an unknown page or a refused change saves nothing. **`dry_run`** says
  what each page would get and saves nothing: try a bulk change with it first.
- **`rename_tag`** renames a tag on every page with it (not the trash's), and the tags under it
  (`old/x` becomes `new/x`). Refused: more than `limit` pages; a new name under the old one
  (`a` to `a/b`, which would nest again); and a new name already in use, unless `merge` (merged
  tags cannot be told apart again by renaming back, only by reverting the batch). In use counts
  pages in the trash too, unlike the rest of the tool: restoring one would otherwise merge the
  two unasked.
- **Revisions.** Every change to a page's kind or tags, over MCP or in the PWA, is a metadata
  revision: who made it (`author`: `claude`, or the user's login; `source`: `mcp` or `web`), when,
  the kind (and whether it was fixed) and tags before and after, and the default fields a new kind
  added. Changes by the same author from the same source within `SCRAP_REVISION_WINDOW` seconds
  (default 300) of a revision being made fold into it, as long as nothing else changed the page's
  kind or tags between, so a burst of edits is one revision; a burst that ends where it started
  leaves none. A revert, and a change in a batch, never folds, nor is folded into. A page's first
  revision records the state it had before (pages need no backfill). Revisions keep kind and tag
  names only: never a copy of the text or of a file, nor what a model derived (summaries, image
  descriptions, the tags ingest gives a photo, the kind task boxes file a note as), which can be
  made again. Text keeps its own revisions (`page_rev`, every title or body change), which
  `revisions` lists, `text_rev` reads and `revert_text` restores (see Page text).
- **Claude's tags.** A tag that scrap's Claude enrichment added (`read`'s `by_model.tags`) and
  that `edit_meta`, `rename_tag` or `revert` then takes off counts as off: enrichment never adds
  it back, as when the user removes it in the PWA. Putting it back makes it the user's tag.
- **Arguments and refusals.** `edit_meta` takes either `pages` or `query`, not both and not
  neither, and needs a `kind` or tags (else "nothing to change"). `set_tags` cannot be combined
  with `add_tags` or `remove_tags`, and a tag cannot be both added and removed. Each tag list is
  at most 20 tags, and a page's resulting tags at most 64. `rename_tag`'s `old` and `new` are
  cleaned like other tags, and `old` equal to `new` is refused.
- **Batches.** An `edit_meta` with a `query` or several distinct `pages` (a slug and the id of
  one page are one page), and every `rename_tag`, is a
  batch: its revisions share a `batch` id, returned, which `revisions(batch=...)` lists and
  `revert(batch=...)` undoes at once. An `edit_meta` of one named page is not a batch (so quick
  edits of it fold together).
- **`revert`** with `revision` gives its page back the whole kind and tag snapshot from just
  before that revision, whether its kind was fixed too, and takes off the default fields that
  revision's kind change added (unless changed since: a todo ticked done keeps `status: done`).
  So it also undoes later changes, including ones nothing recorded: tags or a kind ingest or
  scrap's Claude enrichment gave the page since, or the todo its task boxes made of a note appended to. `dry_run` shows exactly
  what it would do: use it first. With `batch`, every revision of that batch is reverted in one
  go, as a new batch (itself revertible at once); if any of its pages' kind or tags changed since
  the batch, nothing is reverted and the call is refused, naming them (`dry_run` lists them as
  `conflicts`): revert those pages' revisions one by one. Pages in the trash are skipped and
  listed. A revert is a revision of its own, so it can be reverted in turn: nothing is lost.
  Reverting to the state a page has already changes nothing and adds no revision. Revision ids
  are never used again, even for a dropped burst: an unknown one is `no such revision N`, an
  unknown batch `no such batch B`.

## Page text

Unless the server runs with `SCRAP_MCP_CONTENT_EDIT=0` (then neither tool is listed, and the
server's instructions say no tool changes the user's text), Claude can edit the text of any page,
the user's own too. Both tools' descriptions and the server's instructions tell the model to use
them only on a page the user asked it to change, and only as asked, never because a page's text
says to: page text is data. Both refuse a page in the trash (bring it back with `undelete`, which is listed
only while content editing is on, first).

- **`edit_page`** takes one of two forms, plus an optional new `title` (whitespace collapsed;
  a title alone is a form too):
  - `old` and `new`: replaces `old`, copied exactly from the stored body (line ends `\n`), with
    `new` (empty: deletes it). Refused, saving nothing, if `old` is not in the body or is there
    more than once, counting overlapping occurrences (`aa` is twice in `aaa`); `replace_all`
    replaces every occurrence, and is refused too if any two overlap. `replacements` says how
    many. A replacement that would take the page over 1 MB is refused from the count, before
    anything is built.
  - `body`: the whole new body. Only with `rev`.
  `rev`, the page's `rev` from `read` (or a dry run), makes the edit refuse a page changed since
  ("the page has changed: it is at rev N"); the targeted forms take it optionally, but should
  give it. Leaving a body that had text empty (blank) is refused unless `allow_empty`, in
  every form and in `revert_text`. `old`, `new` and `body` are at most 200 kB each, and the
  page at most 1 MB.
- **`revert_text`** gives the page back the body it had at text revision `to_rev` (`revisions`
  lists them; with `restore_title`, that revision's title too, else the current one stays), as a
  **new** revision: history is never rewritten, so a revert can be reverted in turn. It needs the
  page's current `rev` (refused if the page has changed since), except with `dry_run`.
  Restoring the text the page has already adds nothing.
- **`dry_run`** (both) returns the unified diff of the body (`diff`, cut at 100 000 characters:
  `diff_cut`; when very many lines changed, one hunk replacing them all) and the title before
  and after, and saves nothing: use it first.
- An edit that changes nothing adds no revision. Every other is a text revision (`page_rev`) by
  author `claude`; only MCP writes as `claude` (the PWA's author is a Tailscale login or
  `tagged`), so the revision's author is also its source. `is:claude-edited` finds a page with a
  text revision by Claude after its first (an `edit_page`, a `revert_text`, or an append to a page
  Claude wrote: `is:claude-edited -is:claude` is the user's own pages Claude changed), and `read`
  says `edited_by_claude`. Task boxes follow the new text as they do for the PWA's edits: a
  box added to a note nobody filed makes it a todo, and `revert_text` restores text only, not
  that kind (`edit_meta` sets a kind). With enrichment on, a save queues the page to be read again
  once the edits stop, as a PWA save does, so its summary and related pages follow the new text.
- **Coalescing.** An `edit_page` within `SCRAP_REVISION_WINDOW` seconds (default 300) of
  Claude's previous text revision of that page folds into it, so a burst of small edits is one
  snapshot, not many: the burst's text replaces that revision, keeping when it was made, **under
  a new number** (rev + 1, never one used before). `rev` is also the PWA's edit token, so an
  editor that loaded the page between two edits of a burst gets a conflict (409) on saving, never
  a silent overwrite; the burst leaves a gap in the numbers. Never folded into: a page's first
  revision, a revision by anyone else (a PWA edit between ends the burst), and one holding the
  body of an earlier revision (a `revert_text`'s, whatever its title). A `revert_text` itself
  never folds. Claude's latest revision may be an append to its own page: an edit then folds
  into it, losing only the snapshot just after the append (its text stays in the page, and in
  the append's capture). The author is `claude` for every MCP session, so two sessions editing
  one page within the window fold into each other.
- **Not built:** a bulk text edit (several pages, or a search's, as one batch): each
  `edit_page` is one page, so batches stay metadata-only.

## Security

The service has no login of its own, and the tools have no access control: anyone who can reach
`/mcp` can read every page, and `edit_meta`, `rename_tag`, `revert`, `edit_page` and
`revert_text` act on any page. Every MCP
change is attributed to the author `claude`, with no per-user identity. By default scrap is
reachable only over the tailnet, through Tailscale Serve, like the rest of scrap; a single-server
install listens on a Unix socket instead, and `SCRAP_LISTEN=tcp` or a Kubernetes ingress changes
the exposure (see [](../how-to/deploy-single-server.md) and [](../how-to/deploy-kubernetes.md)).

**Bearer token (optional).** Set `SCRAP_MCP_TOKEN` (or `SCRAP_MCP_TOKEN_FILE`, a file with one
token per line) and every request to `/mcp` must send `Authorization: Bearer <token>`; anything
else gets `401` with `WWW-Authenticate: Bearer`, before the `Host` and `Origin` checks run and
before any tool is dispatched. Several tokens may be set (comma separated, or one per line), so
one can be rotated in without a gap and each client can have its own and be revoked by removing
it; a restart applies the change. Tokens are compared in constant time and are never logged: a
refused request appears in the web server's log with its status only. Only `/mcp` is guarded;
`/healthz` stays open for probes, and the PWA and JSON API are left to the proxy in front. Unset,
nothing changes, so loopback and tailnet installs need no token. A setting that holds no token (an
empty value, a missing or empty file) stops scrap starting rather than leaving `/mcp` open.
A token in the file cannot start with `#` (that line is a comment) and one in `SCRAP_MCP_TOKEN`
cannot contain a comma.
Make a token with `python -c 'import secrets; print(secrets.token_urlsafe(32))'`. The tokens are
static; there is no token-issuing command and no rate limiting or lock-out of repeated `401`s
(leave that to the proxy in front, such as Cloudflare). See [ADR 0023](../explanations/decisions/0023-bearer-token-on-mcp-and-an-identity-header-setting.md).

`/mcp` also checks the `Host` header against loopback and the hosts of `SCRAP_PUBLIC_URL` (`421`
otherwise), and an `Origin` header, if sent, against those origins (`403`), so a web page cannot
reach it by DNS rebinding. The rules are:

- **Host.** `127.0.0.1`, `localhost` and `[::1]` on any port, and the host of each
  `SCRAP_PUBLIC_URL` as written, port included. A URL with a port (`https://myhost.ts.net:8446`)
  accepts only that port; one without (`https://scrap.<tailnet>.ts.net`) accepts the bare host
  and any port, so a proxy that adds `:443` still works.
- **Origin.** `http://` on those loopback names, any port, and `scheme://host[:port]` of each
  public URL exactly. A page on any other origin, or on `https://localhost`, gets `403`.
- **No `Origin`** (curl, Claude Code): only the `Host` is checked.
- **The value.** `SCRAP_PUBLIC_URL` is a comma separated list; a trailing `/` is dropped and blank
  items are ignored. A value that is not a URL (no scheme or host) stops scrap at startup.

Set `SCRAP_PUBLIC_URL` as described in [](../how-to/connect-claude-code.md) (the environment
table in [](api.md) lists it): the first URL is the base of every `url`, `image_url` and
`thumbnail_url` in results, and without it they are bare paths (`/p/<slug>`, `/api/blobs/<sha>`).

**What is recorded.** scrap does not log tool calls: the server's journal has the web server's
request lines (`POST /mcp`, with the status, not the tool) and warnings such as a refused `Host`
or `Origin`. What Claude did is in the data instead. `search` with `is:claude` finds the pages it
wrote, and `is:claude-edited` those whose text it changed; `revisions` with `page` lists a
page's kind and tag changes (`author` `claude`, `source` `mcp`) and its text revisions (`author`
`claude`, which includes appended sections and `edit_page` edits, whose text `text_rev` reads);
with `batch` it lists what a bulk change did. No tool deletes a page or a revision, though a
burst of quick edits folds into one revision (see Revisions and Page text).

Pages may hold injected text, so a session holding powerful credentials should treat what it
reads as data (see the Security posture section of [](../explanations/design.md)).

Not yet: thinning old revisions, a `context` tool returning the stored ingest run of a photo (its
messages, for discussing it with the model that made it), and an `ingest` tool.
