(export-format)=
# Export format

What `scrap export DIR` writes, and what Settings, **Export everything** (`GET
/api/store/download`) puts in its zip: the same files either way. How to make one is in
[](../how-to/export-your-pages.md).

## Layout

| Path | Holds |
| --- | --- |
| `<slug>.md` | One per page not in the trash: front matter, then the page's text |
| `files/<sha256><extension>` | The originals of every page's files, each once, named by content: the SHA-256 in hex and the usual extension for its type (none if there is none). Not the name it was uploaded under |
| `files/<sha256>-<capture id>.excalidraw` | A photo's drawing (a drawing belongs to a capture, so one photo on two pages can have two) |
| `_claude/<slug>.md` | What a model wrote about the page, for a page that has any |

The file name is the page's slug, the last part of its address (`/p/<slug>`), so a `[[slug]]` or
`[[slug|label]]` link in a page's text names the file it points to, with nothing rewritten.

## A page's file

The front matter is YAML between `---` lines, and holds only what the page's owner gave it. Every
value is JSON (which YAML reads), except `created` and `updated`, which are bare so that tools
such as Obsidian read them as dates.

| Key | Value |
| --- | --- |
| `title` | The page's title |
| `aliases` | A list holding the title, so Obsidian finds the page by it |
| `id` | The page's id (a ULID); it stays the same when the title or slug changes |
| `kind` | `note`, `todo`, `consume` (a Later page), `whiteboard` or `document` |
| `tags` | The tags you gave it, as stored (lower case, `/` for nesting, spaces kept); left out if none. Tags Claude added are in `_claude/` instead |
| `created`, `updated` | ISO 8601 times in UTC: when the page was made and last edited |
| `due`, `priority` | A todo's due date (`YYYY-MM-DD`) and priority (`high`, `medium`, `low`), if it has them |
| any field | Each of the page's fields as a key of its own, such as `status`, `subtype` or `summary` |
| `fields` | Only a field whose name is one of the keys above, under its name |
| `made_by` | `claude` (written over MCP), `topic` (a Claude topic page) or `gc` (`scrap gc`'s review page); left out for a page you made |
| `attachments` | The files the page has but its text does not show or link to, each `"[[files/<name>]]"` |

Then comes a blank line and the page's text exactly as stored, but with each address of a file of
scrap's (`/api/blobs/<sha256>...`) made a relative `files/<name>`. Image alt text and link text
are kept as typed. A todo's task boxes stay in its text; their count is not in the front matter.

Nothing a model wrote is in a page's file: not a summary, a tag Claude added, a write-up, a
photo's description, the text read from a photo or a drawing.

## Claude's notes: `_claude/<slug>.md`

Front matter `generated_by: "claude"` and `page:` (the page's slug), a line saying a model wrote
it, and a link to the page. Then a section headed *Claude's notes (written by a model, may be
wrong)* with whichever the page has: the summary, the tags Claude added, a board's write-up or a
topic's synthesis, related pages, and for each photo the description (a quote), the text read from
it (a fenced block) and a link to its drawing. Its links to pages are relative
(`[label](../<slug>.md)`), so they do not find another `_claude/` file of the same name.

## Examples

A note with tags and links, `notes-on-ibek.md`:

```markdown
---
title: "Notes on ibek"
aliases: ["Notes on ibek"]
id: "01M64CHHHWJE5BARWPH83NZW7T"
kind: "note"
tags: ["epics/ibek", "lab meeting"]
created: 2026-10-29T17:50:21.755Z
updated: 2026-10-29T17:50:21.755Z
---

Notes on ibek
See [[rtems-iocs]] and [[rtems-iocs|the RTEMS page]].
```

A todo with a photo, `fix-the-broken-fence-panel.md`:

```markdown
---
title: "Fix the broken fence panel"
aliases: ["Fix the broken fence panel"]
id: "01M64CGYA7MZNKGWCYG8XCCA1K"
kind: "todo"
tags: ["home", "garden"]
created: 2026-10-29T17:50:02.054Z
updated: 2026-10-29T17:50:02.054Z
due: "2026-10-24"
priority: "medium"
status: "open"
---

Fix the broken fence panel
- [ ] measure the gap
- [ ] buy a panel

![](files/5bbacd0b…9d.jpg)
```

A whiteboard photo with a PDF its text does not show, `sprint-board.md` (file names shortened
here: each is the full 64-digit SHA-256):

```markdown
---
title: "Sprint board"
aliases: ["Sprint board"]
id: "01M64CGYGY8K291Q2C11G4EG3F"
kind: "whiteboard"
tags: ["scrap"]
created: 2026-10-29T17:50:02.269Z
updated: 2026-10-29T17:50:02.286Z
attachments: ["[[files/5a838678…f5.pdf]]"]
---

Sprint board

![](files/81fdcce0…15.jpg)

My typed notes from the meeting.
```

and its `_claude/sprint-board.md`:

````markdown
---
generated_by: "claude"
page: "sprint-board"
---

*Written by a model, may be wrong. Not part of the page: an import never reads this folder.*

About [Sprint board](../sprint-board.md).

## Claude's notes (written by a model, may be wrong)

**Summary**

> The scrap architecture board.

**Tags Claude added:** architecture

**Write-up**

> The board shows the PWA talking to FastAPI, which keeps SQLite.

### Photo [whiteboard.jpg](../files/81fdcce0…15.jpg)

> A whiteboard with four boxes joined by arrows.

```text
PWA -> FastAPI -> SQLite
Ingest
```

[Drawing of whiteboard.jpg](../files/81fdcce0…15-01M63YSFGWQ1NXW1RNJ47E65GH.excalidraw)
````

## What is left out

Pages in the trash, revisions, the text scrap read from PDFs and text files, the pages that link
to a page (each page's own links say it), and Claude's call records. A file whose embed was deleted from a page's text, which the page no longer shows, is left out too.
