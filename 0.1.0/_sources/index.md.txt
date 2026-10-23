---
html_theme.sidebar_secondary.remove: true
---

# scrap

scrap is a tiny personal knowledge store: a "second brain" you feed from your phone and query
through Claude. Snap a whiteboard, jot a note or share a link; scrap keeps the original at once and
can later read, summarise, redraw and index it in the background. Claude reaches it over MCP to
search, read and add pages; a small PWA is where you capture and look at things, because chat is
poor at showing images.

What            | Where
:---:           | :---:
Source          | <https://github.com/gilesknap/scrap>
Container image | `ghcr.io/gilesknap/scrap` (arm64 and amd64)
Releases        | <https://github.com/gilesknap/scrap/releases>

## What works today

- **Capture, with no LLM.** Notes, links, photos and files become pages you can list, edit, search,
  trash, back up and export, from a phone-first PWA with an offline queue and an Android share
  target. Saving never waits on Claude.
- **Claude reading, opt-in.** With `SCRAP_INGEST=on` and an `ANTHROPIC_API_KEY`, a background
  worker sends photos to the Claude Messages API for their text, a description, a kind, tags and an
  Excalidraw redrawing, and tags, summarises and links text pages. It is off by default, it costs
  money, and a daily budget (`SCRAP_BUDGET_DAY_USD`, default 3) pauses the queue when it is spent.
  See [](explanations/ingest.md) and the [settings](reference/api.md).
- **Claude over MCP.** A Claude Code session can search, read, write and retag pages, and undo
  metadata changes: see [](how-to/connect-claude-code.md) and [](reference/mcp.md).
- **Your data stays yours.** The store is one SQLite database and a folder of files. `scrap backup`
  and `scrap restore` copy it, `scrap export` writes Markdown, `scrap import` brings in a Thoth
  vault and `scrap gc` finds files nothing uses.

Search is full-text only (SQLite FTS5); semantic search was deferred, see
[](explanations/decisions/0008-search-fts5-only-for-now.md). There is no login: access and identity
come from Tailscale Serve, so never expose the service on a public address.

## Try it

scrap is not published on PyPI (the `scrap` package there is an unrelated project), so run it from
the container image or from a checkout, which needs Python 3.11 or newer and
[uv](https://docs.astral.sh/uv/):

```
git clone https://github.com/gilesknap/scrap && cd scrap
uv sync
npm --prefix web ci && npm --prefix web run build   # the PWA (Node 22); the image has it built in
uv run scrap serve --data-dir ./data --host 127.0.0.1 --port 8000
```

Then open <http://127.0.0.1:8000/> for the PWA; `GET /healthz` reports the version and upload limit.
To run the container, see [](how-to/run-container.md). For a lasting install on a server, with
rootless podman, systemd and Tailscale, follow [](tutorials/installation.md); for a cluster, see
[](how-to/deploy-kubernetes.md).

## Where next

- [](how-to/use-the-pwa.md): capture from your phone.
- [](how-to/connect-claude-code.md) and [](reference/mcp.md): let Claude search and write.
- [](reference/api.md): the HTTP API, the CLI and every setting (`SCRAP_DATA_DIR`,
  `SCRAP_INGEST`, `SCRAP_PUBLIC_URL`, `SCRAP_MAX_UPLOAD_MB`, ...).
- [](how-to/deploy-single-server.md): updates, backup and restore, `scrap gc`, troubleshooting.
- [](how-to/import-a-vault.md): bring in a Thoth vault.
- [](explanations/design.md): principles, data model, capture flow and what is deferred.
- [](how-to/contribute.md): development setup.


How the documentation is structured
-----------------------------------

Documentation is split into [four categories](https://diataxis.fr), also accessible from links in the top bar.

<!-- https://sphinx-design.readthedocs.io/en/latest/grids.html -->

::::{grid} 2
:gutter: 4

:::{grid-item-card} {material-regular}`directions_walk;2em`
```{toctree}
:maxdepth: 2
tutorials
```
+++
A tutorial for installing scrap on a server. New users start here.
:::

:::{grid-item-card} {material-regular}`directions;2em`
```{toctree}
:maxdepth: 2
how-to
```
+++
Practical step-by-step guides for the more experienced user.
:::

:::{grid-item-card} {material-regular}`info;2em`
```{toctree}
:maxdepth: 2
explanations
```
+++
Explanations of how it works and why it works that way.
:::

:::{grid-item-card} {material-regular}`menu_book;2em`
```{toctree}
:maxdepth: 2
reference
```
+++
Technical reference material: the HTTP API, CLI and settings, the MCP tools, and release notes.
:::

::::
