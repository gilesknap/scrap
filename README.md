# scrap

scrap is a tiny personal knowledge store: a "second brain" you feed from your phone and query
through Claude. Snap a whiteboard, jot a note or share a link; scrap keeps the original at once and
later reads, summarises, redraws and indexes it in the background. Claude reaches it over MCP to
search, read and add pages; a small PWA is where you capture and look at things, because chat is
poor at showing images.

**Status: design stage.** There is no code yet. See [docs/design.md](docs/design.md).

## Goals

- Tiny: one service, a few thousand lines at most, readable in an afternoon.
- Off-the-shelf parts wherever they exist: Claude for chat and reasoning, SQLite for storage and
  search, a local embedding model, Tailscale for access and identity, Excalidraw for drawings.
- Quick capture from a phone that never waits on an LLM.
- Originals are always kept; everything derived from them can be regenerated.

## Non-goals

- No Obsidian vault and no git sync: the database and a folder of files are the store. A Markdown
  export may come later, one-way only.
- No login code, no user management, no public endpoint in v0.
- No collection of microservices or paid-API integration layers.
- Not multi-user.

## v0 stack

| Part | Choice |
| --- | --- |
| Service | One Python process: FastAPI serving the PWA, a JSON API and an MCP server |
| Storage | SQLite, plus a folder of content-addressed files |
| Search | SQLite FTS5 and sqlite-vec, merged by reciprocal rank fusion |
| Embeddings | Local, via fastembed (bge-small or nomic-embed-text) |
| Frontend | TypeScript PWA with the Excalidraw component |
| Access | Tailscale Serve only; identity from its request headers |
| Deployment | Multi-arch (arm64, amd64) container image on a home k3s cluster |

## Docs

- [Design](docs/design.md): principles, data model, capture flow, MCP tools, security, what is
  deferred and what is still open.

## Licence

Apache-2.0, see [LICENSE](LICENSE).
