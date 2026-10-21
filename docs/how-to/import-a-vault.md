# Import a Thoth vault

`scrap import DIR` reads a Thoth vault (Obsidian-style Markdown pages with YAML front matter, as
its `SCHEMA.md` describes) and saves each content page as a scrap page, with its images. It calls
no model unless you ask it to.

## Steps

1. Work from a copy of the vault, so nothing can change it underneath you:

   ```sh
   cp -a /path/to/vault ~/vault-copy
   ```

2. Look before you write. `--dry-run` writes nothing. It prints the pages it would import as
   counts (by kind and by folder), then every problem it found, one per line, under a count:

   ```sh
   scrap import --dry-run --data-dir ./data ~/vault-copy
   ```

3. Import. Stop scrap first: slugs are worked out before anything is written, so a page
   captured meanwhile can take one and stop the import (running it again carries on).

   ```sh
   scrap import --data-dir ./data ~/vault-copy
   ```

   Running it again imports only pages it has not imported before (a page is known by its path in
   the vault); a page already there is left as it is, even if the vault's copy has changed: there
   is no update. To pick up changes, import afresh into an empty data folder.

4. Optionally, `--ingest` also queues every imported image for Claude, as a photo capture would
   be (they run once `SCRAP_INGEST=on`). Off by default: Thoth pages already describe their images.
   Claude's first reading of a page's first image adds its tags (up to 10) to the page's imported
   ones, so the vault's tags no longer stand alone.

## What is imported

| Vault | scrap |
| --- | --- |
| Pages in `notes/`, `entities/`, `memories/`, `actions/`, `media/` and at the top | One page each, with `kind_fixed` set |
| `type`: `note`, `entity`, `memory`, `action`, `media` (no type: the folder's) | kind `note`, `reference`, `memory`, `todo`, `consume` |
| `title` (else the first `# heading`, else the file name) | Title; a first heading equal to it is dropped from the body |
| File name | Slug (made unique with `-2`, `-3`... in path order) |
| `created`, `updated` (no `created`: `memory_date`, else the file's time) | `created_at`, `updated_at` and the time of revision 1; a date alone is taken as noon UTC, so it is the same day in any time zone |
| `tags` | Tags, lower-cased and cut to 64 characters |
| `status` (`todo` becomes `open`), `due_date` or `due` (as `due`), `priority` (lower-cased), `media_type`, `url` or `source_url` (as `source`), `memory_date`, `summary`, `personal` | `fields`, over the kind's defaults (a todo's `status` is `open`); a consume page also gets `subtype` (`read`, `watch` or `listen`) from `media_type` |
| `[Label](folder/page.md)`, `[[page]]`, `[[page\|label]]` to an imported page | `[[slug\|label]]`, a link to it in the PWA. A path is tried from the linking page's folder, then from the top; a wiki link with a folder (`[[memories/x]]`) is tried as a path first, from the top. A wiki link in a table cell, its pipe escaped with a backslash, works too. A wiki name found in several places prefers an imported page, then the linking page's folder, and never `raw/` or `inbox/` over a content folder |
| `![](../raw/assets/x.png)` and `![[x.png]]` | The image, stored with the page (a photo capture) and shown where it was, not again among the page's files. An image the PWA cannot preview (SVG) is attached as a file instead |
| A PDF embedded or linked | Attached to the page as a file |
| The page file as it is | Kept as its capture's text |

Symbolic links are never followed, and nothing outside `DIR` is read. Search ignores the addresses
of links and images (it indexes their labels and alt text), for every page: a link's domain is
not a word to find, even in a note you wrote by hand. That is the intended trade-off. Links are
found by parsing the page as Markdown, so one in code (fenced, indented or `inline`) is left as
it is.

Not imported: `raw/` and `inbox/` (except the images and PDFs pages use), every folder starting
`.` or `_`, the top `index.md`, `log.md` and `SCHEMA.md`, pages of any other `type` (such as
`summary`), Excalidraw drawings, and every file that is not Markdown. Other front matter fields
are dropped, Thoth's `source` among them (the original stays in the capture's text).

## The report

| Line | Means |
| --- | --- |
| `broken link` | A link to a page that is not in the vault: left as its label |
| `link to dropped page` | A link into `raw/`, `inbox/`, an index or a skipped page: left as its label |
| `link found by name` | A link whose path was wrong, matched to a page by its file name or title |
| `missing file` | An embedded image or file that is not in the vault |
| `links kept as typed` | A block of text (paragraph, list item, table row) whose links could not be found back in the text as typed: its links are left as they were, not rewritten |
| `file not imported` | A drawing or other file a page embeds: replaced by its name |
| `unreferenced image` | An image in `raw/` no imported page uses: not imported |
| `slug collision` | Two pages with the same file name: the later (in path order) gets a suffix |
| `tag changed` | A tag that was lower-cased or cut |
| `unmapped field` | A front matter field scrap has no field for: dropped |
| `unknown status` | A status other than `open`, `in_progress`, `done` or `cancelled`: kept as it is |
| `no front matter` | Imported anyway, with its folder's kind and the file's time |
| `bad front matter` | Front matter that is not valid YAML (an impossible date such as `2024-13-45`, or more than 64 aliases): the page is imported as if it had none |
| `invalid date` | A `created`, `updated` or `memory_date` that is not a date: the next one is used, else the file's time |
| `ambiguous link` | A wiki name that matches several files, and the one chosen |
| `field cut`, `field dropped` | A field value over 200 characters, cut to 200 (ending `…`; the whole of it stays in the capture's text), and fields past 32, as a PWA edit allows |
| `tag dropped` | A tag that is not text or a number (empty, a list) |
| `symlink skipped`, `unreadable`, `too large` | Files left out: symbolic links, files that cannot be read, and images or PDFs over `SCRAP_MAX_UPLOAD_MB` (50 MB) |
| `skipped`, `dropped folder` | Files left out, and why |
