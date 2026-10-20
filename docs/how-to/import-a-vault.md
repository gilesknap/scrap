# Import a Thoth vault

`scrap import DIR` reads a Thoth vault (Obsidian-style Markdown pages with YAML front matter, as
its `SCHEMA.md` describes) and saves each content page as a scrap page, with its images. It calls
no model unless you ask it to.

## Steps

1. Work from a copy of the vault, so nothing can change it underneath you:

   ```sh
   cp -a /path/to/vault ~/vault-copy
   ```

2. Look before you write. `--dry-run` writes nothing and lists every page it would import and
   every problem it found, one per line, under a count:

   ```sh
   scrap import --dry-run --data-dir ./data ~/vault-copy
   ```

3. Import. Stopping scrap first is safest, though it is not required: each page is one
   transaction, as a capture is.

   ```sh
   scrap import --data-dir ./data ~/vault-copy
   ```

   Running it again imports only pages it has not imported before (a page is known by its path in
   the vault); a page already there is left as it is, even if the vault's copy has changed. To
   import everything afresh, import into an empty data folder.

4. Optionally, `--ingest` also queues every imported image for Claude, as a photo capture would
   be (they run once `SCRAP_INGEST=on`). Off by default: Thoth pages already describe their images.

## What is imported

| Vault | scrap |
| --- | --- |
| Pages in `notes/`, `entities/`, `memories/`, `actions/`, `media/` and at the top | One page each, with `kind_fixed` set |
| `type`: `note`, `entity`, `memory`, `action`, `media` (no type: the folder's) | kind `note`, `reference`, `memory`, `todo`, `consume` |
| `title` (else the first `# heading`, else the file name) | Title; a first heading equal to it is dropped from the body |
| File name | Slug (made unique with `-2`, `-3`... in path order) |
| `created`, `updated` (no `created`: `memory_date`, else the file's time) | `created_at`, `updated_at` and the time of revision 1 |
| `tags` | Tags, lower-cased and cut to 64 characters |
| `status` (`todo` becomes `open`), `due_date` or `due` (as `due`), `priority` (lower-cased), `media_type`, `url` or `source_url` (as `source`), `memory_date`, `summary`, `personal` | `fields`, over the kind's defaults (a todo's `status` is `open`); a consume page also gets `subtype` (`read`, `watch` or `listen`) from `media_type` |
| `[Label](folder/page.md)`, `[[page]]`, `[[page\|label]]` to an imported page | `[[slug\|label]]`, a link to it in the PWA |
| `![](../raw/assets/x.png)` and `![[x.png]]` | The image, stored with the page (a photo capture) and shown where it was |
| A PDF embedded or linked | Attached to the page as a file |
| The page file as it is | Kept as its capture's text |

Not imported: `raw/` and `inbox/` (except the images and PDFs pages use), every folder starting
`.` or `_`, the top `index.md`, `log.md` and `SCHEMA.md`, pages of any other `type` (such as
`summary`), Excalidraw drawings, and every file that is not Markdown. Other front matter fields
are dropped (the original stays in the capture's text).

## The report

| Line | Means |
| --- | --- |
| `broken link` | A link to a page that is not in the vault: left as its label |
| `link to dropped page` | A link into `raw/`, `inbox/`, an index or a skipped page: left as its label |
| `link found by name` | A link whose path was wrong, matched to a page by its file name or title |
| `missing file` | An embedded image or file that is not in the vault |
| `file not imported` | A drawing or other file a page embeds: replaced by its name |
| `unreferenced image` | An image in `raw/` no imported page uses: not imported |
| `slug collision` | Two pages with the same file name: the later (in path order) gets a suffix |
| `tag changed` | A tag that was lower-cased or cut |
| `unmapped field` | A front matter field scrap has no field for: dropped |
| `unknown status` | A status other than `open`, `in_progress`, `done` or `cancelled`: kept as it is |
| `no front matter` | Imported anyway, with its folder's kind and the file's time |
| `skipped`, `dropped folder` | Files left out, and why |
