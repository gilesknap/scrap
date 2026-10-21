# 18. Single-server installs listen on a Unix socket, reached only through Tailscale Serve

Date: 2026-10-21

## Status

Accepted. Narrows the local-access consequence of
[](0007-tailscale-serve-for-access-and-identity.md) for single-server installs.

## Context

[](0007-tailscale-serve-for-access-and-identity.md) makes the tailnet ACL the gate and the
`Tailscale-User-Login` header the author, with no login code. Its weak spot is the server
itself: scrap listened on `127.0.0.1`, so every local account and process could read and change
everything and send any `Tailscale-User-Login` it liked. That rules out a shared machine, such as
a work workstation with other users on it, which is where scrap is now wanted. Tailscale Serve can
proxy to a Unix socket (`unix:/path`) as well as to a TCP port, and a socket is guarded by file
permissions, which a loopback port is not.

## Decision

- `scrap serve --uds PATH` listens only on a Unix socket. scrap binds it itself: mode 600, in a
  folder that must belong to the same user and be closed to others (made mode 700 if missing). A
  socket left by an earlier run (connecting is refused) is replaced; anything else at the path is
  refused, as is a socket that accepts or is too busy to answer. A lock file beside the socket
  keeps two starts from replacing it at once. `--uds` with `--host` or `--port` is a usage error, so
  there is never a TCP listener by accident.
- The single-server units (`deploy/`) use it by default: `SCRAP_LISTEN=socket` in
  `~/.config/scrap/env` bind-mounts the unit's runtime folder (`$XDG_RUNTIME_DIR/scrap`, mode 700,
  removed on stop) into the container and publishes no port. Tailscale Serve, which runs as root,
  proxies `https://<host>:<port>` to `unix:$XDG_RUNTIME_DIR/scrap/scrap.sock`. Workstations and
  phones reach scrap only that way, under the tailnet ACL
  ([](../../how-to/deploy-single-server.md)).
- `SCRAP_LISTEN=tcp` keeps the old loopback port, as an explicit opt-in. An env file without
  `SCRAP_LISTEN` (one written before this decision) means `tcp`: re-running `install.sh` does not
  move an existing install, which could cut off whatever reaches it on the port today, but it
  prints how to switch. New env files say `socket`.
- An SSH tunnel to the socket (`ssh -N -L 8790:/path/to/scrap.sock`) is a documented fallback
  for a machine without Tailscale, not a supported path: it needs sshd to allow forwarding to a
  Unix socket (`AllowStreamLocalForwarding`), and it gives no identity header.
- Loopback TCP stays the default for development, plain containers and the Helm chart; the
  image's default command does not change. In a pod the network is the pod's own, and the
  chart's NetworkPolicy and the Tailscale operator are the controls there.

## Consequences

- Other local users on the server can no longer connect to scrap or forge its author header:
  they cannot enter the socket's folder, and could not open the socket if they did.
- What still gets in: root (and so anyone with `sudo`), Tailscale itself (a compromise of
  `tailscaled` or of the tailnet's admin is a compromise of scrap), and anything running as the
  scrap user, which can open the socket and send any `Tailscale-User-Login`. Run scrap as its
  own user with no `sudo`, and do not run other workloads as that user.
- The PWA does not care that the server is unreachable for a while (a restart, a laptop asleep,
  the tailnet down): captures wait in its offline queue
  ([](0005-capture-never-waits.md)).
- Nothing local can reach scrap over TCP, so the smoke test and tools on the server use
  `curl --unix-socket`. scrap no longer sees a client address at all, so its access log shows
  none (behind pasta it showed the host's own address anyway).
- `/mcp` keeps its Host and Origin checks: behind Serve, `SCRAP_PUBLIC_URL` must still be set to
  the Serve address.
