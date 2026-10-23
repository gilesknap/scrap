[![CI](https://github.com/gilesknap/scrap/actions/workflows/ci.yml/badge.svg)](https://github.com/gilesknap/scrap/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/gilesknap/scrap/branch/main/graph/badge.svg)](https://codecov.io/gh/gilesknap/scrap)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)

# scrap

scrap is a tiny personal knowledge store: a "second brain" you feed from your phone and query
through Claude. Snap a whiteboard, jot a note or share a link; scrap keeps the original at once and
later reads, summarises, redraws and indexes it in the background. Claude reaches it over MCP to
search, read and add pages; a small PWA is where you capture and look at things, because chat is
poor at showing images.

**Status: alpha, single user, in daily use.** Notes, links, photos and files become pages you can
list, edit, search, trash, back up and export, from a phone-first PWA with an offline queue and an
Android share target. Pages have kinds, tags and todo fields, drawings are Excalidraw, edits keep
revisions (kind and tag changes can be reverted over MCP), and a Thoth vault can be imported.
Claude can search, read, write and retag pages over MCP (see the
[MCP reference](https://github.com/gilesknap/scrap/blob/main/docs/reference/mcp.md)). Capture never
waits on an LLM: reading photos and tagging, summarising and linking text pages are opt-in background work that stay
off until `SCRAP_INGEST=on` and `ANTHROPIC_API_KEY` are set. See the
[API and CLI reference](https://github.com/gilesknap/scrap/blob/main/docs/reference/api.md) and the
[design](https://github.com/gilesknap/scrap/blob/main/docs/explanations/design.md) (the original plan: principles, data model, capture flow, MCP
tools, security). Where they differ, the [decision records](https://github.com/gilesknap/scrap/blob/main/docs/explanations/decisions.md) are the
as-built record.

What            | Where
:---:           | :---:
Source          | <https://github.com/gilesknap/scrap>
Container       | `docker run -p 127.0.0.1:8000:8000 -v scrap-data:/data ghcr.io/gilesknap/scrap:latest serve --host 0.0.0.0 --port 8000`
Documentation   | <https://gilesknap.github.io/scrap>
Releases        | <https://github.com/gilesknap/scrap/releases>

## Goals

- Tiny: one service, one process, one SQLite file; small enough to read.
- Off-the-shelf parts wherever they exist: Claude for chat and reasoning, SQLite for storage and
  search, Tailscale for access and identity, Excalidraw for drawings.
- Quick capture from a phone that never waits on an LLM.
- Originals are always kept; what is derived from them can be regenerated (a saved link's article
  only while its source is online).

## Non-goals

- No Obsidian vault and no git sync: the database and a folder of files are the store. A Markdown
  export may come later, one-way only.
- No login code, no user management, no public endpoint in v0: scrap binds loopback or a Unix
  socket and relies on Tailscale Serve.
- No collection of microservices or paid-API integration layers.
- Not multi-user.

## v0 stack

| Part | Choice |
| --- | --- |
| Service | One Python process: FastAPI serving the PWA, a JSON API and an MCP server |
| Storage | SQLite, plus a folder of content-addressed files |
| Search | SQLite FTS5 (BM25, prefix matching) with a filter syntax shared by the PWA and MCP; embeddings deferred ([ADR 0008](https://github.com/gilesknap/scrap/blob/main/docs/explanations/decisions/0008-search-fts5-only-for-now.md)) |
| Frontend | TypeScript PWA with the Excalidraw component |
| Access | No login: bind loopback or a Unix socket and publish with Tailscale Serve, which supplies identity in request headers ([ADR 0007](https://github.com/gilesknap/scrap/blob/main/docs/explanations/decisions/0007-tailscale-serve-for-access-and-identity.md), [0018](https://github.com/gilesknap/scrap/blob/main/docs/explanations/decisions/0018-unix-socket-for-single-server-installs.md)) |
| Deployment | Multi-arch (amd64, arm64) container image: rootless podman and systemd on one server, or the Helm chart on Kubernetes |

## Running it

From a checkout you need Python 3.11 or newer and [uv](https://docs.astral.sh/uv/):

```
uv sync
uv run scrap serve --data-dir ./data --host 127.0.0.1 --port 8000
curl http://127.0.0.1:8000/healthz
curl -X POST http://127.0.0.1:8000/api/captures -H 'Content-Type: application/json' \
  -d '{"id": "01JABCDEFGHJKMNPQRSTVWXYZ0", "text": "First note"}'
```

`id` is a ULID the client makes; sending the same id again is a safe retry (it returns 200, the
first call 201). Data lives in `--data-dir` (default `$SCRAP_DATA_DIR`, else `./data`). There is no
login, so keep the default loopback address.

Then open <http://127.0.0.1:8000/> for the PWA. It is optional for API-only use, and a checkout has
to build it first with `npm --prefix web ci && npm --prefix web run build` (Node 22); the container
image has it built in. See [capture from your phone](https://github.com/gilesknap/scrap/blob/main/docs/how-to/use-the-pwa.md).

Other commands: `backup`, `restore`, `export`, `import` (a Thoth vault, see
[import a vault](https://github.com/gilesknap/scrap/blob/main/docs/how-to/import-a-vault.md)), `gc`, `enrich` and `ingest-once`; see the
[CLI reference](https://github.com/gilesknap/scrap/blob/main/docs/reference/api.md).

## Using it with Claude

The MCP server runs in the same process at `/mcp`. To add it to Claude Code:

```
claude mcp add --transport http --scope user scrap https://<your-scrap-address>/mcp
```

`/mcp` answers only loopback hosts and the address in `SCRAP_PUBLIC_URL`. See
[connect Claude Code](https://github.com/gilesknap/scrap/blob/main/docs/how-to/connect-claude-code.md) and the [MCP reference](https://github.com/gilesknap/scrap/blob/main/docs/reference/mcp.md).

## Deploying it

To try the container, see [run in a container](https://github.com/gilesknap/scrap/blob/main/docs/how-to/run-container.md). To deploy, see
[install on a server](https://github.com/gilesknap/scrap/blob/main/docs/tutorials/installation.md) (a walk-through),
[deploy on a single server](https://github.com/gilesknap/scrap/blob/main/docs/how-to/deploy-single-server.md) (rootless podman and systemd, with
backup, retention and enrichment timers) or [deploy on Kubernetes](https://github.com/gilesknap/scrap/blob/main/docs/how-to/deploy-kubernetes.md)
(the Helm chart in `charts/scrap`, with CronJobs for backup, gc and related pages). Diamond colleagues can
[try it on a DLS workstation](https://github.com/gilesknap/scrap/blob/main/docs/tutorials/dls-workstation.md) without `sudo`. To work on scrap, see
[contribute](https://github.com/gilesknap/scrap/blob/main/docs/how-to/contribute.md).

<!-- README only content. Anything below this line won't be included in index.md -->

See <https://gilesknap.github.io/scrap> for the full documentation.

## Licence

Apache-2.0, see [LICENSE](LICENSE).
