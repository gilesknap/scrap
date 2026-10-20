# HTTP API and CLI

Milestone 1: quick capture end to end, with no LLM. Requests and responses are JSON unless noted.
Responses of text (JSON, the PWA's scripts, styles and pages) over 1 kB are gzipped for a client
that sends `Accept-Encoding: gzip`; stored files, previews, downloads, fonts and range requests
never are.
The service binds `127.0.0.1` and has no login; put Tailscale Serve (or an authenticating proxy)
in front. The author of a capture or edit is the `Tailscale-User-Login` header, else `tagged`.

## HTTP

| Method and path | Does |
| --- | --- |
| `GET /healthz` | Liveness: `{"status": "ok", "version": ..., "max_upload_bytes": ...}`; the PWA checks a capture's size against the limit before saving it. `503` (`"status": "ingest worker stopped"`) if ingest is on and its thread has died |
| `POST /api/captures` | Save a capture as a new page. JSON `{id, text?, url?, hint?, source?, created_at?}`, or `multipart/form-data` with the same fields plus one or more `file` parts. `id` is a ULID minted by the client: `201` the first time, `200` with the same reply on a retry. `hint` is `todo` or `consume` and fixes the page kind. A bare URL sent as `text` is treated as `url`. Returns `{capture_id, page_id, slug}`. `413` over the upload limit. Files are stored as sent (HEIC too) |
| `GET /api/pages?limit=50` | Pages, most recently changed first; the trash is left out. `thumb` is the SHA-256 of the page's first image, or `null` |
| `GET /api/pages/{id or slug}` | A page with `rev` (its current revision), `tags`, and its captures and their files. Each file of a photo has `ingest`: `null` if it was never queued, else `{state, failures, error, text, description, image_kind, drawing}` (`drawing`: `null`, or the current version's `{id, version, producer, width, height}`), `state` being `queued`, `processing`, `done`, `failed` or `paused` (see [](../explanations/ingest.md)) |
| `PATCH /api/pages/{id or slug}` | `{base_rev, title?, body?}`: writes a new revision; `409` with the current `rev` if `base_rev` is stale. A `title` equal to the title at `base_rev` counts as unchanged, so it never undoes a title Claude set meanwhile |
| `POST /api/captures/{id}/reprocess` | `{photo?, replace_human?}`: send a photo capture's images (or the one with SHA-256 `photo`) to Claude again; also the *Retry* of a failed one. A new drawing replaces one the user drew only with `replace_human: true` (otherwise it is kept in the drawing's history only); the confirmation also reaches a photo already queued or running. Returns `{queued, already}`: how many were added, and how many were queued or running already |
| `GET /api/captures/{id}/photos/{sha256}/drawing` | The photo's current drawing: `{id, version, producer, author, run_id, created_at, current, format, restored_from, data}`. `data` is `{format, width, height, elements}`: `format` `skeleton` (Claude's, Excalidraw element skeletons the PWA expands) or `scene` (a saved edit: full Excalidraw elements, and `appState.viewBackgroundColor`). `width` and `height` are the frame the coordinates are in: the pixels of the JPEG sent to Claude, so the PWA lines the drawing up with the photo. `404` if there is none |
| `GET /api/captures/{id}/photos/{sha256}/drawing/versions` | Every version, newest first, as above without `data`. `producer` is the model, or `human` with its `author`; a restored version has `restored_from` |
| `PUT /api/captures/{id}/photos/{sha256}/drawing` | `{base_version, scene: {elements, appState?, width?, height?, files?}}`: save an edit as a new current `human` version, its text elements indexed for search. `base_version` is the version it was edited from (`null` if there was none): `409` with the current `version` if that is no longer current. The scene is checked (see [](../explanations/ingest.md)): only rectangle, ellipse, diamond, text, arrow, line and freedraw elements; finite numbers; Excalidraw's colours; `http(s)` links only; nesting at most 32 levels deep; valid Unicode (no lone surrogates); `files` dropped; at most 5 MB as compact JSON, else `422` and nothing is saved. `413` if the request is over 8 MB |
| `POST /api/captures/{id}/photos/{sha256}/drawing/restore` | `{version, base_version}`: make an old version current again as a new copy (versions never change). `base_version` is the current version as the client last saw it: `409` with the current `version` if it has changed, so a stale history view cannot restore over a newer edit. `404` if there is no such version; `422` unless both are integers from 1 |
| `GET /api/ingest` | The ingest queue: `{enabled, paused, reason, paused_until, jobs, spent_today_usd}` (`paused_until` is `null` while paused until *Resume*) |
| `POST /api/ingest/resume` | End a pause; returns the queue as `GET /api/ingest` |
| `DELETE /api/pages/{id or slug}` | Move a page to the trash (`204`). Its captures and files are kept |
| `POST /api/pages/{id or slug}/undelete` | Bring a page back from the trash |
| `GET /api/search?q=...&limit=20` | Full-text search of titles, bodies and what Claude read from photos (their text and descriptions): every word must match somewhere in the page (the last as a prefix); one hit per page. Only the first 16 distinct words with a letter or digit are used; others (`&`, `-`, `?`) are ignored. Each hit has an HTML-escaped `snippet` with matches in `<mark>` |
| `GET /api/pages/{id or slug}/download` | The page to keep: `<slug>.md` (front matter, then the body), or if it has files `<slug>.zip` holding the `.md` and `files/` with the originals, linked relatively so it reads offline. Each photo is followed by Claude's description (a quote) and the text it read (a fenced block), and its drawing is beside it as `<photo name>.excalidraw` (Claude's skeleton converted approximately on the server: Excalidraw re-measures the text when it opens it) |
| `GET /api/blobs/{sha256}` | An original file, byte for byte, with its stored content type. `?download=1` adds a `Content-Disposition` with the name it was uploaded under |
| `GET /api/blobs/{sha256}/preview?size=2048` | A JPEG of a photo (HEIC too), turned upright and without its EXIF, at most `size` (`480` or `2048`) pixels a side. Made on first request and kept in `cache/previews/` under the data folder, which is never backed up and can be deleted at any time. Made one at a time, shrunk as it is decoded, within a memory budget that fits a 1 GB container: `422` if the file is not an image Pillow can read or would need more memory than that to decode (roughly over 50 megapixels for HEIC, 80 for PNG; JPEG is decoded shrunk and fits at any size), `503` with `Retry-After` if the decoder stays busy for 20 s. The colour profile is kept |
| `POST /share` | The PWA's share target, for when its service worker did not take the share (which it normally queues itself): saves the multipart `title`, `text`, `url` and `files` as a capture with a server-minted id, then `303` to `/` |
| `GET /`, `/recent`, `/search`, `/p/{slug}` | The PWA (`index.html`); its other files are served from the root too. `503` with build instructions if it was not built; see [](../how-to/use-the-pwa.md) |

## CLI

| Command | Does |
| --- | --- |
| `scrap serve [--host 127.0.0.1] [--port 8000]` | Run the service, migrating the database first |
| `scrap backup DIR` | Consistent snapshot of the database (SQLite online backup) plus `files/`; safe while serving |
| `scrap restore DIR [--force]` | Restore a backup into an empty data folder, after checking its integrity and that its schema is not newer than this scrap. `DIR` may be read-only: only a copy of its database, made in the data folder, is opened. `--force` replaces the whole database (pages added since the backup are lost; files are kept); stop scrap first, or a running server goes on writing to the replaced database and those writes are lost |
| `scrap ingest-once IMAGE [--save FILE]` | Send one image file to Claude as ingest would, without a database, and print the outcome in numbers only (tokens, cost, seconds, counts of lines, elements and warnings); `--save FILE` also writes the full result, including all the text Claude read from the image, to a new file with mode 600 (an existing file is refused), created before the paid call. Needs `ANTHROPIC_API_KEY` |
| `scrap import DIR [--dry-run] [--ingest]` | Import a Thoth vault: each content page with its kind, fields, tags, dates, links (as `[[slug\|label]]`) and images; see [](../how-to/import-a-vault.md). `--dry-run` writes nothing and lists the pages and every problem (broken links, unreferenced images, unmapped fields...). A second run imports only pages not imported before. `--ingest` also queues the images for Claude |
| `scrap export DIR` | One Markdown file per page, front matter and links to its originals copied into `DIR/files/`, with each photo's description, text and `.excalidraw` drawing as in the page download. Export only: never read back |

Every command takes `--data-dir` (default `$SCRAP_DATA_DIR`, else `./data`), which holds
`scrap.db` and `files/` (originals by SHA-256).

## Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `SCRAP_DATA_DIR` | `./data` | The data folder |
| `SCRAP_WEB_DIR` | the packaged PWA | Serve the PWA from this folder instead: a new build there shows without a restart |
| `SCRAP_MAX_UPLOAD_MB` | `50` | Largest request body (a capture's files together), enforced as it arrives: `413` |
| `SCRAP_INGEST` | `off` | `on` starts the worker that sends photos to Claude (photos are queued either way) |
| `ANTHROPIC_API_KEY` | | The key for the Claude API; keep it in the service user's mode-600 env file |
| `SCRAP_VISION_MODEL` | `claude-opus-5-5` | The model photos are sent to |
| `SCRAP_BUDGET_DAY_USD` | `3` | Daily spend, from recorded usage, after which the queue pauses until UTC midnight |
| `SCRAP_NOTIFY_URL` | unset | If set, the first pause of an episode POSTs one fixed line naming its reason here (an ntfy topic works) |
