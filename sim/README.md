# The design sim

The sim is the real PWA (`web/`), built with its own Vite config and run against a
fake scrap server inside the page, `sim.js`. It is published as a claude.ai artifact
so a design can be tried on a phone before any code ships:
<https://claude.ai/artifact/PePhDjfGXhyk7jUAsXhbH5>.

Nothing here is part of scrap: not the package, the image or the app build, and the
repo's linters, type checks and tests leave `sim/` alone.

## What it is and isn't

- **The app is real; the server is not.** `sim.js` patches `fetch` (and
  `XMLHttpRequest` for capture uploads) and answers the API from an in-memory copy of
  the sample pages. Search, facets, tags, topics, edits, todos, trash, drawings and
  captures all work, to the extent `sim.js` imitates them. Nothing is saved: a reload
  starts again from the seed. There is no Claude: enrich, reprocess and ingest give
  canned answers.
- **Routes live in the hash** (`#/p/scrap-design-notes`, `#/search?q=tag:person`), so the
  host page's address never changes. The build rewrites the app's `location.pathname`
  and `location.search` to `__sim.loc`'s, and `sim.js` turns `pushState` URLs into hashes.
- **Dates move with today.** The sample data was made on 21 Oct 2026 (`SEED_DAY` in
  `sim.js`); every date is shifted by the days since, so "due tomorrow" stays so.
- **The artifact host limits it.** No service worker (`build.sh` removes `sw.js`), no
  manifest, no CSP meta. File pickers and the camera do not open inside the artifact
  viewer (they do when served locally). `confirm()` is blocked there, so `sim.js` treats
  an unseen confirm as yes. The phone's Back gesture closes the artifact, so `sim.js`
  adds a `‹ Back` button. The host refuses U+FFFD in files and wraps the page in its own
  document, so `build.sh` escapes the one and strips the doctype and the html, head and
  body tags.
- **Feedback.** A `Feedback` tab on every screen saves a note (screen, text, width,
  theme) to the artifact's shared database, collection `feedback`, when the artifact has
  the `db` capability. Read them with the ArtifactData tool (`list`, collection
  `feedback`, the sim's url). Screenshot scripts hide the tab (`.sim-fb`).

## Files

| File | What it is |
| --- | --- |
| `build.sh` | Builds the sim from this checkout into `sim/out/` (gitignored). |
| `serve.sh` | Serves `sim/out/` locally, under a sub-path, as the artifact host does. |
| `vite.sim.config.ts` | The sim's Vite config: the app's own, minus the service worker step, with relative paths, stable file names (so a republish replaces files instead of piling up hashed ones), the hash-route rewrite and `sim-seed.js` and `sim.js` loaded ahead of the app. |
| `sim.js` | The fake server (see [Keeping sim.js in step](#keeping-simjs-in-step)). |
| `mock.py` | Writes `out/sim-seed.js`: the fixtures plus the mock pages each design needed. |
| `fixtures/dump.json` | The frozen sample pages and the whiteboard's drawing. |
| `fixtures/blobs/` | The four sample photos: each original (`<sha>`) and its previews (`<sha>-480.jpg`, `<sha>-2048.jpg`). |
| `seed.py`, `dump.py` | How the fixtures were made, to make them again. |
| `files.py` | Writes the files map for publishing `sim/out` to the artifact. |
| `shots/` | Playwright helpers against the served sim: screenshots, a type-size audit and a measuring tool. |

## Build, serve and look

Needs Node 22 with `npm --prefix web ci` done, and `python3`. Works from any checkout,
a git worktree included.

```sh
sim/build.sh        # about 9.5 MB, 260 files, into sim/out/
sim/serve.sh        # http://127.0.0.1:9100/art/x1/index.html (PORT=... to change)
```

`serve.sh` starts a detached `python3 -m http.server` (log in `sim/.host/http.log`) and
leaves it running; it reuses one already answering on the port. In a Claude Code session,
a detached process may be stopped a few minutes after the reply: rerun `serve.sh` when the
screenshots fail to connect.

The helpers in `shots/` load Playwright from `web/node_modules` and need its Chromium
(`npx playwright install chromium` from `web/`, unless `PLAYWRIGHT_BROWSERS_PATH`
already has one):

```sh
# The search screen and a page, at 390 px, 100% and 130% text, dark: PNGs in sim/out-shots/
node sim/shots/shot.mjs --width 390 --text 100,130 --scheme dark "/search?q=scrap" /p/embedded-items-test
# Narrow phones, both schemes, the whole page
node sim/shots/shot.mjs --width 308,320,390 --scheme light,dark --full /todos
# The type-size audit: editing chips and fields against --t-sm, at 100% and 130%
node sim/shots/sizes.mjs
# Where things sit: top, height, middle, width and font-size of each match
node sim/shots/measure.mjs --click Edit --click Tags /p/book-the-mot ".editor .facet.on" ".editor .facet.on svg"
```

130% text is the app's setting, which makes the root font-size 22.1px; the scripts set
that directly. Each script's options are in its header comment.

## Publish to the artifact

Use the Artifact tool. After every build that is to be published, publish everything:
a partial publish (only the files that changed) broke the sim when Vite re-split its
chunks, because a chunk file's name stayed the same while its contents and imports moved.

1. Build, then write the files map, giving it the previous publish's map so files the
   build no longer has are removed (`null`):

   ```sh
   sim/build.sh
   python3 sim/files.py /path/to/previous-files.json > /path/to/files.json
   ```

   Keep `files.json` as the previous map for next time (outside the repo, for example in
   the session's scratchpad). Without one, nothing is removed, which is harmless except
   for stale files on the artifact. To get the artifact's current list instead, use the
   Artifact tool's `list` with `scope: "files"` on the sim's url.

2. Publish: `action: "publish"`, `url: "https://claude.ai/artifact/PePhDjfGXhyk7jUAsXhbH5"`,
   `file_path: "<repo>/sim/out/index.html"`, `root: "<repo>/sim/out"`, and
   `files`: the map. Leave out `capabilities`, so the artifact keeps its `db`
   capability (for Feedback); the Artifact tool's description has the rules.

The map leaves out `index.html` (it is the `file_path`) and `blobs/` and `excalidraw/`
(the drawing fonts). Those two folders do not change between builds (unless the
fixtures or the Excalidraw version do), are already on the artifact, and a publish keeps
the files it leaves out. They also keep one publish under the tool's limit of 255 files:
the whole build is about 260. For a new artifact, or after a fixture or Excalidraw
change, publish them as well, as a second publish to the same url:

```sh
python3 sim/files.py --static > /path/to/static-files.json
```

A first publish of a new artifact also needs an `icon` and, for Feedback, the `db`
capability (load the `artifact-capabilities` skill first).

## Mock data for a new design

The sample pages are `fixtures/dump.json`, frozen. A design that needs more (many tags,
people, a topic, a page in some state) adds pages in `mock.py`: a block headed
`# ---- <design> mock`, built with its `page()` helper, appended to `d["pages"]`. Ids
are a hash of the title, so they stay put from build to build. Times are hours before
the seed time and move with today, as the fixtures' do.

- What ingest made of a photo goes in `ingest` (by page title or slug), a topic's text
  and sources in `TOPICS`.
- Something `sim.js` needs to know about a page that the API would work out (a page's
  `made_by`, an MCP source) is set in `sim.js`, where the store is loaded.
- Files a page embeds that are not in the fixtures (PDFs, a `.md`) are made by `sim.js`
  as object URLs (see "files in a page's text").

Then build, serve, take screenshots at 308, 320 and 390 px, at 100% and 130%, light and
dark, and look at them before publishing.

To make the fixtures again, from a scratch server (it needs Pillow, which the project's
environment has):

```sh
uv run scrap serve --port 8765 --data-dir /tmp/sim-data &   # an empty data folder
uv run python sim/seed.py http://127.0.0.1:8765
uv run python sim/dump.py http://127.0.0.1:8765             # rewrites sim/fixtures/
```

This is rarely worth it. New fixtures have new ids, times and photo-page slugs (a photo
page with no title gets a slug from the time it was made, such as `2026-10-21-13-52`,
which `mock.py`'s topics refer to), and the API's page shape has moved on since the
fixtures were made (it now has `writeup`, `topics`, `related`, `made_by` and more, which
`sim.js` adds itself). Check `mock.py` and `sim.js` against the new dump, and update
`SEED_DAY` in `sim.js` and `SEED` in `mock.py`.

## Keeping sim.js in step

When the server's API changes in a way the app relies on, change `sim.js` in the same
branch, or the sim shows the old behaviour (or a `the sim has no ...` error, its 404).
It fakes these, in its `api()` dispatcher:

| Endpoint | Notes |
| --- | --- |
| `GET /healthz`, `GET /api/health` | Fixed answers. |
| `GET /api/pages` | `limit`, `kind`. |
| `GET`, `PATCH`, `DELETE /api/pages/{key}` | `PATCH` as JSON, or multipart with `edit` and `file` parts (an edit with files); `base_rev` is checked (409). |
| `POST /api/pages/{key}/undelete`, `GET /api/trash` | The trash. |
| `GET /api/pages/{key}/download` | The page as a Markdown file. |
| `POST /api/pages/{key}/enrich` | Queued, processing, then done with a canned summary, over four seconds. |
| `GET /api/pinned` | The page with slug `pinned`, or null. |
| `POST /api/captures` | JSON or multipart, by `fetch` or by `XMLHttpRequest` (upload progress). |
| `GET /api/search`, `GET /api/search/facets`, `GET /api/tags`, `GET /api/topics` | Its own, simpler, query parser: words, phrases, `-` and the `kind:`, `tag:`, `is:`, `has:`, `image:`, `after:`, `before:`, `date:`, `due:`, `priority:`, `sort:`, `group:`, `media:` and `later:` filters. |
| `GET /api/ingest`, `POST /api/ingest/resume` | Ingest on, not paused. |
| `GET /api/captures/{cid}/files/{sha}/text`, `POST /api/captures/{cid}/reprocess` | A file's text; a canned redo. |
| `GET`, `PUT /api/captures/{cid}/photos/{sha}/drawing`, `GET .../versions`, `POST .../restore` | Drawings, with versions. |
| `GET /api/blobs/{sha}/uses` | How many pages show a file. |
| `GET /api/blobs/{sha}[/preview?size=]` | Served from `blobs/` next to the page (also for `img` `src` and `srcset`, which are rewritten before the browser asks). |

A tap on a link to `/api/...` or `/share` is fetched through the fake and opened as an
object URL. Not faked, so they answer 404: `POST /api/pinned`,
`POST /api/pages/{key}/captures`, the topic sources endpoints
(`/api/pages/{key}/topic/sources...`), `POST /api/pages/{key}/writeup` and
`PUT /api/pages/{key}/writeup/guidance`, and the `/share` form post. Add one when a
design needs it. The search and facets code is a sketch of the server's, not a copy, so
a design that depends on exact search behaviour should be checked against a real
`scrap serve` too.
