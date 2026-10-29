(import-your-pages)=
# Import your pages

An import reads Markdown pages with YAML front matter and makes each one a scrap page, with its
files. It reads an export from scrap ([](export-your-pages.md)) back exactly as it was written,
and it reads an [Obsidian](https://obsidian.md) vault, or any folder of Markdown notes, the same
way. An import only adds pages: a page that is here already is skipped, and nothing in the store
is changed or overwritten.

## From the app

For a zip of up to the upload limit (`SCRAP_MAX_UPLOAD_MB`, 50 MB by default):

1. Open **Settings** (the cog).
2. Under **Store**, tap **Import Markdown…** and pick the zip.
3. Settings shows how many pages and photos the zip holds, and two choices, both off:
   - **Enrich text pages with Claude**: Claude tags and summarises each new note, todo and read,
     and picks its related pages.
   - **Read photos with Claude**: Claude reads each new page's photos for their text, a
     description and a drawing. This uses the vision model, the dearer one.

   Beside each is roughly what it would cost, from the counts in the zip and the models' prices.
   It is an estimate: each call's cost depends on the page or photo. On a server without Claude
   (`SCRAP_INGEST` off) both are off and cannot be ticked.
4. Tap **Import**.

Settings then says how many pages were imported, how many were here already, the tag they were
given and what was queued for Claude. The fold below it lists what could not be done as
written, such as a link to a page that is not in the zip.

## From the command line

For a zip over the upload limit, or a folder, run it on the machine that holds the data:

```sh
scrap import --data-dir /path/to/data --dry-run ~/notes.zip   # what would happen; writes nothing
scrap import --data-dir /path/to/data ~/notes.zip
```

`--dry-run` lists every page, every problem found and roughly what Claude would cost. `--enrich`
and `--photos` are the two choices above, off unless given. The server picks up what was queued
within a minute. Where scrap runs in a container, see [](deploy-kubernetes.md) or
[](deploy-single-server.md) for running a `scrap` command against its data.

## What each page gets

- **Its text** as written. A link to another page in the import becomes `[[slug|label]]`; a link
  that already names its page's slug, as every link in a scrap export does, is kept exactly. A link
  to a page or file that is not in the import is kept as typed, and listed in the notes.
- **Its files.** An image the text shows (`![](photo.jpg)` or Obsidian's `![[photo.jpg]]`) is
  stored and shown in place. Another file it links to or embeds (a PDF, a text file) is stored and
  linked; PDFs and text files are read for search, which is free. The files in a scrap export's
  `attachments` are added to the page too.
- **Its title**: `title`, else the first `# heading`, else the file name.
- **Its kind** from `kind` (`note`, `todo`, `consume`, `whiteboard` or `document`), else a note.
- **Its tags** from `tags` (a list, or a string of tags split at commas and spaces), as scrap keeps
  tags (lower case, no `#`), plus `import/YYYY-MM-DD`, the UTC date of the import, so you can
  find, review or trash what one import brought in.
- **Its dates** from `created` and `updated` (or `created_at`, `date`, `updated_at`,
  `modified`), else the file's time.
- **Its fields**: a todo's `due` and `priority`, and every other single value in the front matter
  (such as `status` or `source`), up to 32. A list or a map is left out, and listed.
- **Its id**: a scrap export's `id` is kept, so the page has the same id as in the store it came
  from.

The front matter is read as plain YAML data only, and a file whose front matter cannot be read is
imported with its whole text as the page's text, so nothing is lost.

## What is left out

- Folders whose name starts with `.` or `_`: Obsidian's `.obsidian/`, and a scrap export's
  `_claude/`, which holds what Claude wrote. Claude's text never becomes your page's text.
- A Claude topic page (`made_by: topic`) and `scrap gc`'s review page: Claude makes topics again.
- `pinned.md` when this store has a Pinned page already.
- A page over 1 MB, and a file over the upload limit.
- Any file outside the zip: a zip with a name that would reach outside it (`../`), or with more
  files or bytes than it may hold, is refused whole.

## Importing again

A page is known by its `id` if it has one, else by its path and its bytes. Importing the same zip
twice adds nothing the second time, and importing an export into the store it came from adds
nothing. A file edited since the last import comes in as a new page beside the old one (its slug
gets `-2`), never over it. A page in the trash counts as here until it is purged: restore it
instead, or wait for the purge (30 days by default) to import it again.
