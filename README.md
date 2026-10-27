[![CI](https://github.com/gilesknap/scrap/actions/workflows/ci.yml/badge.svg)](https://github.com/gilesknap/scrap/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/gilesknap/scrap/branch/main/graph/badge.svg)](https://codecov.io/gh/gilesknap/scrap)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)

<!-- docs include start: everything from here to the end marker is also the docs front page -->

# scrap

scrap is a memory system for Claude Code: a self-hosted store that Claude searches, reads and writes over MCP (and the `/sc-*` commands). Capture from your phone in seconds, never waiting on an LLM, then see it all in a PWA: photos, Excalidraw diagrams and rendered markdown. It follows the [LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) pattern, and **your words and Claude's never mix**: page text is yours, and everything Claude adds is stored apart, labelled and regenerable.

**Status:** in daily use, and deployed on Kubernetes.

## Goals

- Simple: one service, one process, one SQLite file.
- Off-the-shelf parts wherever they exist: Claude for chat and reasoning, SQLite for storage and
  search, Tailscale for access and identity, Excalidraw for drawings.
- Quick capture from a phone that never waits on an LLM.
- Originals are always kept; what is derived from them can be regenerated (a saved link's article
  only while its source is online).
- Human and model content kept apart: model output is derived, labelled and regenerable, and
  write-ups are refreshed when you choose.

## What Claude adds

Snap a whiteboard, jot a note or share a link; scrap keeps the original at once, and Claude adds:

- a reading of each photo: a description, the text on it, and a drawing;
- a write-up of each whiteboard and diagram;
- tags and a summary;
- related pages;
- topic pages that draw your pages together.

Store health checks then find orphans, dangling links and outdated write-ups.

Claude searches, reads and adds pages over MCP; the PWA is for capturing and looking. See
[what Claude is asked, per page](https://gilesknap.github.io/scrap/main/explanations/llm-calls.html).

## Try it

```
printf 'Anthropic API key (Enter to skip): '; read -rs ANTHROPIC_API_KEY; export ANTHROPIC_API_KEY
podman run --network=host -v scrap-data:/data -e SCRAP_INGEST=${ANTHROPIC_API_KEY:+on} -e ANTHROPIC_API_KEY ghcr.io/gilesknap/scrap:latest serve
```

The key is optional: it lets Claude read your photos and tag your notes.

Open <http://localhost:8000/>. Then add scrap to Claude Code and install the `sc` commands and skill:

```
claude mcp add --transport http --scope user scrap http://localhost:8000/mcp
curl -fsSL https://github.com/gilesknap/scrap/releases/latest/download/install.sh | sh
```

Start a new Claude Code session, save a note in the browser, then try 

```
/sc-find <word>
``` 

or 

```
search scrap for ...
```

Connect your phone for quick capture. See [use scrap on your phone over Tailscale](https://gilesknap.github.io/scrap/main/how-to/use-scrap-on-your-phone.html).

Claude Code in a sandbox? See [connecting Claude Code in claude-sandbox](https://gilesknap.github.io/scrap/main/how-to/connect-claude-sandbox.html).

More: [connect Claude Code and the `sc` commands](https://gilesknap.github.io/scrap/main/how-to/connect-claude-code.html), [MCP reference](https://gilesknap.github.io/scrap/main/reference/mcp.html).

<!-- docs include end: the rest is README only -->

## Install

- [Use it from other devices on your LAN](https://gilesknap.github.io/scrap/main/tutorials/install-lan.html): the same container, reachable from your phone or another machine.
- [Install on a server](https://gilesknap.github.io/scrap/main/tutorials/install-server.html): rootless podman, systemd and Tailscale Serve.
- [Install on Kubernetes](https://gilesknap.github.io/scrap/main/tutorials/install-kubernetes.html): Helm, Cloudflare tunnel and Access.

Full documentation: <https://gilesknap.github.io/scrap>

## Licence

Apache-2.0, see [LICENSE](LICENSE).
