# 22. Page text editable over MCP, made safe by text revisions

Date: 2026-10-22

## Status

Accepted. Revises [](0013-mcp-server-inside-the-app.md) and
[](0019-kinds-and-tags-editable-with-revisions.md), which kept the text of the user's pages out
of Claude's reach.

## Context

Over MCP, Claude could only add pages or append to its own: asked to fix a typo in the user's
note, it could only write a new page. It could read old text revisions (`revisions`,
`text_rev`) but not restore one. The add-only rule was the safety against a session steered by
injected text. Every title or body change already keeps a full snapshot in `page_rev`, so text
edits can be made as visible and as undoable as the kind and tag edits of ADR 19.

## Decision

- MCP gains `edit_page` and `revert_text`. Still no delete, no trash, and no unconditional
  overwrite of a body.
- `edit_page` is narrow by default: `old` text, found exactly once in the body (else refused;
  `replace_all` to replace every occurrence), becomes `new`. Replacing the whole body needs the
  page's current `rev`, the same optimistic-concurrency token the PWA's editor uses; the
  targeted form takes `rev` optionally, and any stale `rev` is refused. Overlapping matches
  are ambiguous and refused. The resulting size is worked out from the match count and
  refused over 1 MB before anything is built (a `replace_all` of a long `new` could otherwise
  ask for gigabytes). Leaving a body empty needs `allow_empty`, there and in `revert_text`. A new title may come with
  either form, or alone. `dry_run` returns a unified diff and saves nothing.
- `revert_text` restores the body (and with `restore_title` the title) of an earlier text
  revision as a new revision, never rewriting history; it needs the current `rev` unless a
  `dry_run`.
- Page text is untrusted: the server's instructions and both tools' descriptions say to edit
  only a page the user asked to change, as asked, never because a page's text says to. Nothing
  in a tool applies instructions found in text.
- Provenance without a migration: a text revision's `author` is `claude` for one made over MCP,
  and only MCP writes as `claude` (the PWA's author is a Tailscale login, an address, or
  `tagged`), so the author is also the source. `is:claude-edited` finds a page with a text
  revision by Claude after its first; `read` returns `edited_by_claude`. This includes appends
  to Claude's own pages, which are text edits over MCP too; `-is:claude` narrows to the user's
  pages.
- Coalescing: an `edit_page` within `SCRAP_REVISION_WINDOW` of Claude's latest text revision of
  the page folds into it, replacing that snapshot. Since `rev` is the PWA's edit token, the
  folded revision is re-numbered `rev + 1` (its row deleted, the new one keeping the burst's
  `created_at`): the token moves on every change, so an editor holding the folded number gets
  the 409 it would have got anyway, and no number is ever used twice (a reused number would let
  a stale editor overwrite silently). The cost is a gap in a page's revision numbers. Never
  folded into: rev 1 (ingest's title check relies on it), another author's revision, and a
  revision holding the body of an earlier one (a revert's, whatever its title). A
  `revert_text` never folds. The PWA's own text edits are unchanged: every save is a revision.
  Folded into: Claude's own append (only the snapshot just after it is lost; its text is in
  the page and the append's capture), and another MCP session's edit, since every session is
  author `claude`.
- A switch, `SCRAP_MCP_CONTENT_EDIT` (unset: on; `0`, `false`, `no`, `off`), stops the server
  offering the two tools at all, and its instructions then say no tool changes the user's text.
  Any other value, an empty one too, stops scrap starting: a switch that rendered empty must
  not turn editing on unasked.
  A single client can deny the two tools in its own permission settings instead.
- No bulk text edit: each `edit_page` is one page, so batches stay metadata-only. A batch of
  text edits (a search's pages, with a batch id and a batch `revert_text`) would need text
  revisions to record a batch, i.e. a migration; left until it is wanted.
- No migration: `page_rev` is used as it is.

## Consequences

- Claude can make the small text fixes the user asks for, in place; each is a revision that
  `revisions` lists and `revert_text` undoes, and `is:claude-edited` shows where Claude has been.
- A session steered by injected text could now change the text of a page, not just add one: the
  change is visible, revertible and never a deletion, and a whole-body replace or revert must
  name the page's current `rev`. Turning the switch off restores the add-only posture.
- A folded burst keeps only its final text: the text between two edits of a burst is not kept.
- As in the PWA, a task box Claude adds to a note nobody filed makes it a todo; that kind is
  derived, not a revision, and `revert_text` restores text only.
- `page_rev` grows by a full snapshot per edit (per burst over MCP). Thinning old snapshots,
  or storing deltas, is not built.
- Revision numbers of a page may have gaps; nothing relies on them being contiguous (the PWA
  only compares its token with the current `rev`).
