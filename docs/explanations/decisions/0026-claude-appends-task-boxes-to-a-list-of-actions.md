# 26. Claude appends task boxes to a list of actions

Date: 2026-10-24 (#191, #193)

## Status

Accepted. Amends [](0020-text-enrichment.md), which said enrichment never edits a page's text,
and applies [](0022-page-text-editable-over-mcp-with-revisions.md) (Claude-authored text
revisions) to scrap's own photo ingest ([](0009-claude-ingest-via-messages-api.md)) and enrich.

## Context

scrap already turns an unfixed note with task boxes into a todo, but only the user could write
the boxes. A photo of a sticky headed "CURRENT ACTIONS" was ingested as a whiteboard with its
transcription in a derived row, and a typed "call the dentist / book MOT / pay invoice" stayed a
note: neither could be ticked.

## Decision

- Photo ingest and enrich both return `intent` (`list-of-actions`, `reference`, `other`),
  `confidence` and `items` from one shared prompt section and schema fragment, and use one
  writer (`src/scrap/actions.py`).
- With high confidence, and only on a `note` with `kind_fixed` 0 (or a whiteboard ingest chose)
  that has no task boxes and has not been edited since Claude read it, the writer appends
  `- [ ] item` lines as one text revision by `claude`, which never folds into another. The
  existing task-box rule makes the page a todo. `revert_text` undoes it.
- **Appended, not converted.** Even when the user's lines are already plain bullets, the boxes
  are added below and the original text is left exactly as it was. Converting in place would
  rewrite the user's words, and the cost of appending (the list shown twice) is small and one
  revert away. A photo's transcription is not copied into the body: its boxes come from the
  extracted items, and the image stays above them.
- Items are untrusted: plain single-line text, at most 30 of at most 200 characters, with list
  marks, links (and URL schemes and `www.`, so nothing autolinks), code, tags, emphasis marks,
  backslashes and character references removed. They are never read as instructions.
- Never a fixed kind, a saved link, or a page with boxes, so a second reading (Reprocess, Ask
  Claude, a save) adds nothing. Priority and due dates read from the sticky are not parsed.

## Consequences

- Text sent to Claude is unchanged; its output now can change a page's text, visibly, in one
  revertible revision (`is:claude-edited` finds it). A wrong high-confidence reading is one
  revert away, and the prompt tells the model to answer `reference` or `other` when unsure.
- A saved text page queues one further enrich job after the revision (a save), which adds no
  boxes: one more cheap call per converted note.
- A `revert_text` that takes the boxes away from a todo that Claude's own boxes made returns it
  to the kind it was filed as before: the kind photo ingest chose for a photo page (whiteboard
  or document), else a note. The kind is derived, not part of the revision, so `Store._unbox`
  does this only for an unfixed todo with its default `open` status whose previous text had
  boxes and where no revision by anyone but Claude ever had a box, so the boxes can only be
  Claude's (no marker is stored; it is derived from the history, so it holds when a quick MCP
  `edit_page` folds the revision that added them). A todo the user filed or edited with boxes,
  an import, or a page whose own text had boxes stays a todo. The `status: open` field the todo
  kind added is left on the page.
- Intent gating for Slack-style prose, standing directives and relative due dates stay out of
  scope.
