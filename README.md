[![CI](https://github.com/gilesknap/scrap/actions/workflows/ci.yml/badge.svg)](https://github.com/gilesknap/scrap/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/gilesknap/scrap/branch/main/graph/badge.svg)](https://codecov.io/gh/gilesknap/scrap)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)

# scrap

scrap is a tiny personal knowledge store: a "second brain" you feed from your phone and query
through Claude. Snap a whiteboard, jot a note or share a link; scrap keeps the original at once and
later reads, summarises, redraws and indexes it in the background. Claude reaches it over MCP to
search, read and add pages; a small PWA is where you capture and look at things, because chat is
poor at showing images.

**Status: milestone 1.** Quick capture works end to end with no LLM: notes, links, photos and
files become pages you can list, edit, search, trash, back up and export, from a phone-first PWA
with an offline queue and an Android share target (see the
[API and CLI reference](https://github.com/gilesknap/scrap/blob/main/docs/reference/api.md)). See the
[design](https://github.com/gilesknap/scrap/blob/main/docs/explanations/design.md): principles,
data model, capture flow, MCP tools, security, what is deferred and what is still open.

What            | Where
:---:           | :---:
Source          | <https://github.com/gilesknap/scrap>
Container       | `docker run -p 8000:8000 ghcr.io/gilesknap/scrap:latest serve --host 0.0.0.0 --port 8000`
Documentation   | <https://gilesknap.github.io/scrap>
Releases        | <https://github.com/gilesknap/scrap/releases>

## Goals

- Tiny: one service, a few thousand lines at most, readable in an afternoon.
- Off-the-shelf parts wherever they exist: Claude for chat and reasoning, SQLite for storage and
  search, a local embedding model, Tailscale for access and identity, Excalidraw for drawings.
- Quick capture from a phone that never waits on an LLM.
- Originals are always kept; what is derived from them can be regenerated (a saved link's article
  only while its source is online).

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

## Running it

```
scrap serve --data-dir ./data --host 127.0.0.1 --port 8000
curl http://127.0.0.1:8000/healthz
curl -X POST http://127.0.0.1:8000/api/captures -H 'Content-Type: application/json' \
  -d '{"id": "01JABCDEFGHJKMNPQRSTVWXYZ0", "text": "First note"}'
```

Then open <http://127.0.0.1:8000/> for the PWA. From a checkout, build it first with
`npm --prefix web ci && npm --prefix web run build` (Node 22); the container image has it built in.
See [capture from your phone](https://github.com/gilesknap/scrap/blob/main/docs/how-to/use-the-pwa.md).

To deploy it, see [deploy on a single server](https://github.com/gilesknap/scrap/blob/main/docs/how-to/deploy-single-server.md)
(rootless podman and systemd) or [deploy on Kubernetes](https://github.com/gilesknap/scrap/blob/main/docs/how-to/deploy-kubernetes.md)
(the Helm chart in `charts/scrap`).

<!-- README only content. Anything below this line won't be included in index.md -->

See <https://gilesknap.github.io/scrap> for the full documentation.

## Licence

Apache-2.0, see [LICENSE](LICENSE).
