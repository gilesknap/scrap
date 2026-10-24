[![CI](https://github.com/gilesknap/scrap/actions/workflows/ci.yml/badge.svg)](https://github.com/gilesknap/scrap/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/gilesknap/scrap/branch/main/graph/badge.svg)](https://codecov.io/gh/gilesknap/scrap)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)

# scrap

scrap is a personal knowledge store: a "second brain" you feed from your phone and query
through Claude. Snap a whiteboard, jot a note or share a link; scrap keeps the original at once and
reads, summarises and indexes it in the background. Claude searches, reads and adds pages over MCP,
and a small PWA is where you capture and look at things.

**Status:** in daily use, and deployed on Kubernetes.

## Goals

- Simple: one service, one process, one SQLite file.
- Off-the-shelf parts wherever they exist: Claude for chat and reasoning, SQLite for storage and
  search, Tailscale for access and identity, Excalidraw for drawings.
- Quick capture from a phone that never waits on an LLM.
- Originals are always kept; what is derived from them can be regenerated (a saved link's article
  only while its source is online).

## Try it

```
podman run --network=host -v scrap-data:/data ghcr.io/gilesknap/scrap:0.5.0 serve
```

Open <http://localhost:8000/>. Then add scrap to Claude Code and install the `sc` commands:

```
claude mcp add --transport http --scope user scrap http://localhost:8000/mcp
curl -fsSL https://raw.githubusercontent.com/gilesknap/scrap/main/commands/install.sh | sh
```

Start a new Claude Code session, save a note in the browser, then try `/sc-find <word>` or "search scrap for ...".

On your phone, over your tailnet? See [use scrap on your phone over Tailscale](https://gilesknap.github.io/scrap/main/how-to/use-scrap-on-your-phone.html).

Claude Code in a sandbox? See [connecting Claude Code in claude-sandbox](https://gilesknap.github.io/scrap/main/how-to/connect-claude-sandbox.html).

More: [connect Claude Code and the `sc` commands](https://gilesknap.github.io/scrap/main/how-to/connect-claude-code.html), [MCP reference](https://gilesknap.github.io/scrap/main/reference/mcp.html).

## Install

- [Try it on your LAN](https://gilesknap.github.io/scrap/tutorials/install-lan.html): a container on a laptop, Pi or home PC.
- [Install on a server](https://gilesknap.github.io/scrap/tutorials/install-server.html): rootless podman, systemd and Tailscale Serve.
- [Install on Kubernetes](https://gilesknap.github.io/scrap/tutorials/install-kubernetes.html): Helm, Cloudflare tunnel and Access.

Full documentation: <https://gilesknap.github.io/scrap>

## Licence

Apache-2.0, see [LICENSE](LICENSE).
