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
[](explanations/decisions/0008-search-fts5-only-for-now.md). scrap has no login code of its own:
access is the network (Tailscale) or an authenticating proxy (Cloudflare Access), with an optional
bearer token on `/mcp` ([](explanations/decisions/0023-bearer-token-on-mcp-and-an-identity-header-setting.md)).
Never expose it on a public address without one of them.

## Choose your install

scrap is not published on PyPI (the `scrap` package there is an unrelated project); you run the
container image. Each tutorial is one short path from nothing to a running scrap.

::::{grid} 1 1 3 3
:gutter: 3

:::{grid-item-card} Try it on your LAN
:link: tutorials/install-lan
:link-type: doc
One container on a laptop, Pi or home PC, reached from your phone over the LAN or Tailscale. No
login, no systemd. The quickest way to try it.
:::

:::{grid-item-card} One server with Tailscale
:link: tutorials/install-server
:link-type: doc
A hardened single VPS or home server: dedicated user, Unix socket, systemd and Tailscale Serve
for HTTPS. Claude Code on the same box.
:::

:::{grid-item-card} Kubernetes with Cloudflare
:link: tutorials/install-kubernetes
:link-type: doc
The Helm chart behind a cloudflared tunnel and Cloudflare Access, with a bearer token on `/mcp`.
:::

::::

To read photos with a Claude subscription instead of an API key, add
[](tutorials/ingest-with-claude-seat.md) to any of them.

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
Three install tutorials, from a quick LAN try-out to Kubernetes, and one for ingest on a Claude seat. New users start here.
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
