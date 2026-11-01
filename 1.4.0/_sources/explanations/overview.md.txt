# Scope and stack

What scrap sets out not to be, and what it is built from. The [design](design.md) describes the
principles and how it works; the [decision records](decisions.md) give the reasons.

## Non-goals

- No Obsidian vault and no git sync: the database and a folder of files are the store. An export
  of every page as Markdown (`scrap export`, or Settings, **Export everything**) opens as an
  Obsidian vault, but nothing is kept in step with it.
- No login code of its own and no user management. Access is the network: Tailscale (Serve
  supplies the identity header) or an authenticating proxy such as Cloudflare Access, with an
  optional bearer token on `/mcp` only
  ([](decisions/0007-tailscale-serve-for-access-and-identity.md),
  [](decisions/0023-bearer-token-on-mcp-and-an-identity-header-setting.md)).
- No collection of microservices or paid-API integration layers.
- Not multi-user: one store for one person, or a few people who trust each other.

## Stack

| Part | Choice |
| --- | --- |
| Service | One Python process: FastAPI serving the PWA, a JSON API and an MCP server ([](decisions/0013-mcp-server-inside-the-app.md)) |
| Storage | SQLite, plus a folder of content-addressed files |
| Search | SQLite FTS5 (BM25, prefix matching) with a filter syntax shared by the PWA and MCP; embeddings deferred ([](decisions/0008-search-fts5-only-for-now.md)) |
| Frontend | TypeScript PWA with the Excalidraw component |
| Access | No login. Bind loopback or a Unix socket and publish with Tailscale Serve ([](decisions/0007-tailscale-serve-for-access-and-identity.md), [](decisions/0018-unix-socket-for-single-server-installs.md)), or put an authenticating proxy in front on Kubernetes, with an optional `SCRAP_MCP_TOKEN` on `/mcp` ([](decisions/0023-bearer-token-on-mcp-and-an-identity-header-setting.md)) |
| Deployment | Multi-arch (amd64, arm64) container image: a plain container to try it, rootless podman and systemd on one server, or the Helm chart on Kubernetes ([](decisions/0016-deployment-single-server-and-helm.md)) |
