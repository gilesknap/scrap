# 7. Tailscale Serve is the only way in; no login code

Date: 2026-10-19

## Status

Accepted

Update 2026-10-21: single-server installs now listen on a Unix socket that other local users
cannot open, so the "any local process" point below holds only for TCP installs, development and
Kubernetes. See [](0018-unix-socket-for-single-server-installs.md).

## Context

scrap is single-user and holds personal notes. Writing and maintaining authentication would be the
largest and riskiest part of a tiny service, and Tailscale already provides network reachability and
a per-device identity.

## Decision

- The service binds to `127.0.0.1`; Tailscale Serve (HTTPS, tailnet only, **Funnel off**) is the only
  route in. No login code and no user management.
- **The ACL is the gate; identity is attribution.** `author` is the `Tailscale-User-Login` header
  that Serve sets. Tagged devices send none and are recorded as `tagged`. The tailnet policy must
  deny tagged (e.g. internet-facing) servers access to scrap.
- Any local process can reach the loopback port and can forge the header, so v0 assumes a
  single-purpose host or VM with no untrusted local users. The docs say so for both deployments.
- Ingested content is untrusted data. The service holds no cluster or git credentials and no shell
  tools; sessions with powerful credentials should not mount the scrap MCP server (reading is not
  acting).
- A Cloudflare tunnel with Access for a work browser, and a work sandbox, are deferred designs.

## Consequences

- Zero auth code, but also no defence against another local workload on the same host.
- The MCP endpoint is protected exactly like the rest: by the tailnet.
- Under Kubernetes the Tailscale operator's ingress must pass identity headers through (documented
  as the recommended route).
