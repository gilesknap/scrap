# HTTP API and CLI

Milestone 1: quick capture end to end, with no LLM. Requests and responses are JSON unless noted.
The service binds `127.0.0.1` and has no login; put Tailscale Serve (or an authenticating proxy)
in front. The author of a capture or edit is the `Tailscale-User-Login` header, else `tagged`.

## HTTP

| Method and path | Does |
| --- | --- |
| `GET /healthz` | Liveness: `{"status": "ok", "version": ...}` |
| `POST /api/captures` | Save a capture as a new page. JSON `{id, text?, url?, hint?, source?, created_at?}`, or `multipart/form-data` with the same fields plus one or more `file` parts. `id` is a ULID minted by the client: `201` the first time, `200` with the same reply on a retry. `hint` is `todo` or `consume` and fixes the page kind. A bare URL sent as `text` is treated as `url`. Returns `{capture_id, page_id, slug}`. `413` over the upload limit. Files are stored as sent (HEIC too); no thumbnails yet |
| `GET /api/pages?limit=50` | Pages, most recently changed first; the trash is left out. `thumb` is the SHA-256 of the page's first image, or `null` |
| `GET /api/pages/{id or slug}` | A page with `rev` (its current revision) and its captures and their files |
| `PATCH /api/pages/{id or slug}` | `{base_rev, title?, body?}`: writes a new revision; `409` with the current `rev` if `base_rev` is stale |
| `DELETE /api/pages/{id or slug}` | Move a page to the trash (`204`). Its captures and files are kept |
| `POST /api/pages/{id or slug}/undelete` | Bring a page back from the trash |
| `GET /api/search?q=...&limit=20` | Full-text search of titles and bodies, every word must match (the last as a prefix). Each hit has an HTML-escaped `snippet` with matches in `<mark>` |
| `GET /api/blobs/{sha256}` | An original file, byte for byte, with its stored content type |
| `POST /share` | The PWA's share target, for when its service worker did not take the share (which it normally queues itself): saves the multipart `title`, `text`, `url` and `files` as a capture with a server-minted id, then `303` to `/` |
| `GET /`, `/recent`, `/search`, `/p/{slug}` | The PWA (`index.html`); its other files are served from the root too. `503` with build instructions if it was not built; see [](../how-to/use-the-pwa.md) |

## CLI

| Command | Does |
| --- | --- |
| `scrap serve [--host 127.0.0.1] [--port 8000]` | Run the service, migrating the database first |
| `scrap backup DIR` | Consistent snapshot of the database (SQLite online backup) plus `files/`; safe while serving |
| `scrap restore DIR [--force]` | Restore a backup into an empty data folder, after checking its integrity and that its schema is not newer than this scrap. `--force` replaces the whole database (pages added since the backup are lost; files are kept); stop scrap first, or a running server goes on writing to the replaced database and those writes are lost |
| `scrap export DIR` | One Markdown file per page, front matter and links to its originals copied into `DIR/files/`. Export only: never read back |

Every command takes `--data-dir` (default `$SCRAP_DATA_DIR`, else `./data`), which holds
`scrap.db` and `files/` (originals by SHA-256).

## Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `SCRAP_DATA_DIR` | `./data` | The data folder |
| `SCRAP_MAX_UPLOAD_MB` | `50` | Largest request body (a capture's files together), enforced as it arrives: `413` |
