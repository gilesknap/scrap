# Import a Thoth vault

`scrap import DIR` reads a Thoth vault (Obsidian-style Markdown pages with YAML front matter, as
its `SCHEMA.md` describes) and saves each content page as a scrap page, with its images. The
command itself calls no model; what Claude does with the pages afterwards is under
{ref}`import-claude`.

The commands below assume `scrap` is on your `PATH`, as in a development checkout. Against a
deployed scrap, see {ref}`import-container`. `--data-dir` defaults to `$SCRAP_DATA_DIR`, then
`./data`; a real import creates the data folder if it is missing and migrates its database (`--dry-run` creates nothing).

## Steps

1. Work from a copy of the vault, so nothing can change it underneath you:

   ```sh
   cp -a /path/to/vault ~/vault-copy
   ```

2. Look before you write. `--dry-run` writes nothing. It prints the pages it would import as
   counts (by kind and by folder), then each kind of problem it found with a count and, under
   it, one line per file:

   ```sh
   scrap import --dry-run --data-dir ./data ~/vault-copy
   ```

   A real import prints only the counts, not the lines, so use `--dry-run` to see which files a
   problem is about. A `DIR` that does not exist fails with `no folder DIR`.

3. Import. Stop scrap first: slugs are worked out before anything is written, so a page
   captured meanwhile can take one and stop the import (running it again carries on).

   ```sh
   scrap import --data-dir ./data ~/vault-copy
   ```

   It prints the same summary, then `imported N pages into DIR`.

   Running it again imports only pages it has not imported before (a page is known by its path in
   the vault, so the summary says `(0 new)` for a vault already imported); a page already there is
   left as it is, even if the vault's copy has changed: there is no update. To pick up changes,
   import afresh into an empty data folder. Moving or renaming a file in the vault makes it a new
   path, so a re-run imports it again as a second page. A page you imported and then trashed in
   scrap is not brought back by a re-run.

4. Optionally, `--ingest` also queues every imported image for Claude, as a photo capture would
   be. Off by default: Thoth pages already describe their images. The queue is run by the
   service, which needs `SCRAP_INGEST=on` and `ANTHROPIC_API_KEY`. Each queued image is a paid
   call, counted against `SCRAP_BUDGET_DAY_USD` (the queue pauses when it is spent). Only the
   images the PWA can preview are queued, not PDFs, SVGs or other attached files. The settings are
   in the [API reference](../reference/api.md). Claude's first reading of a page's first image
   adds its tags to the page's imported ones, so the vault's tags no longer stand alone.

(import-container)=
## In a container

The documented deployments run scrap from the image, whose entrypoint is `scrap` and whose data
folder is `/data` (`SCRAP_DATA_DIR`), as uid 10001. To import into a single-server install, stop
the service, run `import` in a throwaway container with the vault mounted read-only, and start
the service again. As in the restore recipe of [](deploy-single-server.md), load the settings
file first so `SCRAP_DATA` and `SCRAP_IMAGE` are yours; the vault must be readable by that uid
(with the `--userns` option below, by the user who runs podman):

```sh
systemctl --user stop scrap
set -a; . ~/.config/scrap/env; set +a
podman run --rm --userns=keep-id:uid=10001,gid=10001 \
    -v "$SCRAP_DATA:/data:z" -v ~/vault-copy:/vault:ro,z -e SCRAP_DATA_DIR=/data \
    "$SCRAP_IMAGE" import --dry-run /vault
```

Before the real import, take a backup, since an import cannot be undone from within scrap. With
scrap stopped (so nothing is captured after it), run `systemctl --user start scrap-backup`; the
command returns when the backup is done. If the import goes wrong, `scrap restore --force` of
that backup puts the database back, as in {ref}`scrap-backup-restore`; any page captured after
the backup is lost with it. The files the import stored stay on disk, unused, until `scrap gc`
removes them (see {ref}`scrap-gc`).

Then run the import command again without `--dry-run`, and `systemctl --user start scrap`. The
import does not take the lock that `scrap-backup` and `scrap-gc` share, but nothing needs
coordinating with the timers: scrap is stopped, and a `gc` that runs meanwhile does not delete
the files of pages already saved.

On Kubernetes the chart has no import recipe. The nearest is the one-off pod that
[](deploy-kubernetes.md) uses for `scrap restore`: the same image and data claim with scrap
stopped, run with `import` arguments, and the vault on a second volume mounted read-only.

## What is imported

| Vault | scrap |
| --- | --- |
| Pages in `notes/`, `entities/`, `memories/`, `actions/`, `media/` and at the top | One page each, with `kind_fixed` set |
| `type`: `note`, `entity`, `memory`, `action`, `media` (no type: the folder's) | kind `note`, `reference`, `memory`, `todo`, `consume` |
| `title` (else the first `# heading`, else the file name) | Title; a first heading equal to it is dropped from the body |
| File name | Slug: the name without `.md`, lower-cased to ASCII letters and digits (accents are removed, other non-ASCII characters dropped) with runs of anything else as one `-`, cut to 60 characters (`page` if nothing is left). A slug already in use gets `-2`, `-3`... (see `slug collision`) |
| `created`, `updated` | `created_at` and `updated_at`. No `created`: `memory_date`, else `updated`, else the file's time. No `updated`: the same as `created`, and never earlier than it. A date alone is taken as noon UTC, so it is the same day in any time zone |
| (none) | Revision 1 of the page, stamped with `updated_at`, by author `import` |
| `tags` | Tags: a leading `#` removed, spaces collapsed, lower-cased, cut to 64 characters, duplicates removed. A single `tags: x` is one tag. The PWA's limit of 64 tags per page is not applied |
| `status` (`todo` becomes `open`), `due_date` or `due` (as `due`), `priority`, `snoozed_until`, `media_type`, `url` or `source_url` (as `source`), `memory_date`, `summary`, `personal` | `fields`, over the kind's defaults. `status`, `priority` and `media_type` are lower-cased. A todo's `due`, `snoozed_until` and `priority` become the todo's own due day, snooze day and priority instead, if they are a date or a priority (`high`, `medium`, `low`; Thoth's `urgent` becomes `high`); otherwise they stay in `fields`. `snoozed_until` is what `scrap export` writes, so an export imports back |
| Defaults | A todo has `status` `open`. A consume page has `subtype` `read` and `status` `open`, and its `media_type` sets `subtype`: `book` and `article` give `read`; `film`, `tv` and `video` give `watch`; `podcast` and `music` give `listen`. Any other `media_type` leaves `read` |
| `[Label](folder/page.md)`, `[[page]]`, `[[page\|label]]` to an imported page | `[[slug\|label]]`, a link to it in the PWA. A heading anchor (`[[page#sec]]`, `page.md#h`) is dropped, so the link goes to the page. A path is tried from the linking page's folder, then from the top; a wiki link with a folder (`[[memories/x]]`) is tried as a path first, from the top, then from the linking page's folder, then by name; case is ignored in the folders and name (an exact-case match wins, several that differ only by case are reported as ambiguous), and a leading `/` is dropped. A wiki link in a table cell, its pipe escaped with a backslash, works too. A wiki name found in several places prefers an imported page, then the linking page's folder, and never `raw/` or `inbox/` over a content folder |
| `![](../raw/assets/x.png)` and `![[x.png]]` | The image, stored with the page (a photo capture) and shown where it was, not again among the page's files. An image the PWA cannot preview (SVG) is attached as a file instead, and its place in the text becomes `*alt text (attached)*` (the file name if there is no alt text) |
| A link (not an embed) to an image the PWA can preview | The image is attached to the page as a photo, and the link becomes the text `*label (attached)*` |
| A PDF embedded or linked | Attached to the page as a file; the link or embed becomes `*label (attached)*` (the file name if there is no label) |
| A drawing, or a file that cannot be attached (a CSV, a file over the size limit or one that cannot be read), embedded or linked | Not imported; replaced by the text `*name (not imported)*` |
| The page file as it is | Kept as its capture's text (capture source `import`) |

Symbolic links are never followed, and nothing outside `DIR` is read. Search ignores the addresses
of links and images (it indexes their labels and alt text), for every page: a link's domain is
not a word to find, even in a note you wrote by hand. That is the intended trade-off. Links are
found by parsing the page as Markdown, so one in code (fenced, indented or `inline`) is left as
it is.

Not imported: the top-level folders `raw/`, `inbox/` and any starting `_` (except the images and
PDFs pages use; the same names deeper in the tree are ordinary folders, and their pages are
imported), the top `index.md`, `log.md` and `SCHEMA.md`, pages of any other `type` (such as
`summary`), Excalidraw drawings, and every file that is not Markdown. Files and folders whose
name starts with `.`, at any depth (such as `.obsidian/`), are ignored without a line in the
report. Other front matter fields are dropped, Thoth's `source` among them (the original stays in
the capture's text).

## Limits

- Pages are not size-capped on import, unlike a page saved through the API (1 MB). Only images and
  PDFs are checked, against `SCRAP_MAX_UPLOAD_MB` (50 MB).
- If a file changes between the check and the write, the import stops with `changed since it was
  checked: run again`. Run it again: it carries on with the pages not yet imported. The files
  of the page it stopped on were already stored, but the page was not saved, so nothing uses
  them. On the single server the nightly `scrap gc` removes them once they are over 24 hours
  old; to remove them by hand, run `scrap gc --delete` after a backup (see {ref}`scrap-gc`).
- A page you import and then trash in scrap keeps its images: `gc` counts the text of trashed
  pages as in use, so that the page can be brought back.
- The vault must be readable by the user (or container uid) that runs `scrap import`.

(import-claude)=
## What Claude does with imported pages

Importing queues no Claude work for text, but a deployment with Claude enrichment on
(`SCRAP_INGEST=on`, `ANTHROPIC_API_KEY` set, `SCRAP_ENRICH` not `off`) still picks up the pages:

- The nightly related-pages pass (`scrap enrich --related`, run by `scrap-enrich-related.timer`
  on the single server) treats a page with no related pages picked yet as stale, so it makes a
  paid call for every imported page, oldest first, within `SCRAP_BUDGET_DAY_USD`, even if you did
  not use `--ingest`.
- `scrap enrich --backfill` queues every page with no tags that Claude has not read yet.

To hold this back, set `SCRAP_ENRICH=off` (or leave ingest off) until you want it. With
enrichment on, `scrap enrich --related --dry-run` says how many pages the pass would do; with it
off the command only says that enrichment is off.

## The report

| Line | Means |
| --- | --- |
| `N pages (M new): ...` | The pages found, how many are not imported yet, and the count of each kind |
| `by folder:` | Pages by top-level folder; pages at the top of the vault show as `./` |
| `N images shown inline and M other files attached; K tags` | What the pages bring with them: N counts the previewable images attached as photos (a linked one is attached but not shown inline), M the PDFs and SVGs |
| `broken link` | A link to a page that is not in the vault: left as its label |
| `link to dropped page` | A link into `raw/`, `inbox/`, an index or a skipped page: left as its label |
| `link found by name` | A link whose path was wrong, matched to a page by its file name or title |
| `missing file` | An embedded image or file that is not in the vault |
| `links kept as typed` | A block of text (paragraph, list item, table row) whose links could not be found back in the text as typed: its links are left as they were, not rewritten |
| `file not imported` | A drawing or other file a page embeds or links: replaced by `*name (not imported)*` |
| `unreferenced image` | An image in `raw/` no imported page uses: not imported |
| `slug collision` | A slug already in use, by an earlier page in the vault (the later, in path order, gets the suffix; `My Note.md` and `my-note.md` collide) or by any page already in the data folder, the trash included |
| `tag changed` | A tag that was changed (lower-cased, cut, `#` removed or spaces collapsed) |
| `unmapped field` | A front matter field scrap has no field for, or a mapped one whose value is a list or a map: dropped |
| `unknown status` | A status other than `open`, `in_progress`, `done` or `cancelled`: kept as it is |
| `no front matter` | Imported anyway, with its folder's kind and the file's time |
| `bad front matter` | Front matter that is not valid YAML (an impossible date such as `2024-13-45`, or more than 64 aliases): the page is imported as if it had none |
| `invalid date` | A `created`, `updated` or `memory_date` that is not a date: the next one is used, else the file's time |
| `ambiguous link` | A wiki name that matches several files, and the one chosen |
| `field cut`, `field dropped` | A field value over 200 characters, cut to 200 (ending `…`; the whole of it stays in the capture's text), and fields past 32, as a PWA edit allows |
| `tag dropped` | A tag that is not text or a number (null, a list, a map, true or false). An empty tag is dropped without a line |
| `symlink skipped`, `unreadable`, `too large` | Files left out: symbolic links, files that cannot be read, and images or PDFs over `SCRAP_MAX_UPLOAD_MB` (50 MB) |
| `skipped`, `dropped folder` | Files left out, and why. `dropped folder` counts the files under the top-level `raw/`, `inbox/` and `_*` folders |
