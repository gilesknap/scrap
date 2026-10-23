[![CI](https://github.com/gilesknap/scrap/actions/workflows/ci.yml/badge.svg)](https://github.com/gilesknap/scrap/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/gilesknap/scrap/branch/main/graph/badge.svg)](https://codecov.io/gh/gilesknap/scrap)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)

# scrap

scrap is a tiny personal knowledge store: a "second brain" you feed from your phone and query
through Claude. Snap a whiteboard, jot a note or share a link; scrap keeps the original at once and
reads, summarises and indexes it in the background. Claude searches, reads and adds pages over MCP,
and a small PWA is where you capture and look at things.

**Status:** in daily use, and deployed on Kubernetes.

## Goals

- Tiny: one service, one process, one SQLite file; small enough to read.
- Off-the-shelf parts wherever they exist: Claude for chat and reasoning, SQLite for storage and
  search, Tailscale for access and identity, Excalidraw for drawings.
- Quick capture from a phone that never waits on an LLM.
- Originals are always kept; what is derived from them can be regenerated (a saved link's article
  only while its source is online).

## Try it

```
docker run -p 127.0.0.1:8000:8000 -v scrap-data:/data ghcr.io/gilesknap/scrap:0.2.2 serve --host 0.0.0.0 --port 8000
```

Then open <http://127.0.0.1:8000/>. There is no login, so keep it on loopback unless you follow an
install tutorial.

## Install

- [Try it on your LAN](https://gilesknap.github.io/scrap/tutorials/install-lan.html): a container on a laptop, Pi or home PC.
- [Install on a server](https://gilesknap.github.io/scrap/tutorials/install-server.html): rootless podman, systemd and Tailscale Serve.
- [Install on Kubernetes](https://gilesknap.github.io/scrap/tutorials/install-kubernetes.html): Helm, Cloudflare tunnel and Access.

Full documentation: <https://gilesknap.github.io/scrap>

## Licence

Apache-2.0, see [LICENSE](LICENSE).
