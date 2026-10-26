# 23. Bearer token on /mcp and an identity-header setting

Date: 2026-10-23

## Status

Accepted. Supersedes the "bearer token on `/mcp` deferred" item in the security options note,
and adds to [](0013-mcp-server-inside-the-app.md).

## Context

scrap has no login. On a tailnet the network is the gate; behind Cloudflare Access (or any
proxy that has to leave `/mcp` open to Claude Code) the proxy's service token is the only gate
on `/mcp`, and whatever gets past it can read and change every page. The author of a change was
read from `Tailscale-User-Login` only, which says nothing useful behind another proxy.

## Decision

- **Optional bearer token on `/mcp` only.** `SCRAP_MCP_TOKEN` (comma separated) and
  `SCRAP_MCP_TOKEN_FILE` (one per line; `#` comments and blank lines skipped) give the accepted
  tokens. Unset: no check, so loopback and tailnet installs are unchanged. Set: a request to
  `/mcp` without a matching `Authorization: Bearer` gets `401` and `WWW-Authenticate: Bearer`.
- It is ASGI middleware outside the app's other middleware, so it runs before the `Host` and
  `Origin` checks and before any tool or body is read. The PWA, the JSON API and `/healthz`
  are not touched (probes need `/healthz`; the PWA and API stay behind the proxy).
- Comparison uses `hmac.compare_digest` against every token, so timing does not say which
  matched. Tokens are never logged or echoed.
- Several tokens allow rotation without a gap and a token per client, revoked by removing it.
- A set but empty value, or a missing or token-less file, stops scrap starting. Failing open
  would turn a mistyped secret mount into an unauthenticated `/mcp`.
- **Static tokens only.** No token-issuing command and no tokens stored hashed in the database;
  that needs a migration and a UI for what is a handful of clients. Revisit if clients multiply.
- **No rate limiting or lock-out.** Tokens are long random values, and the proxy in front
  (Cloudflare) is the place to throttle.
- **`SCRAP_IDENTITY_HEADER`** (default `Tailscale-User-Login`; blank counts as unset) names the
  one header read as the author, else `tagged`. A proxy that sets another header (oauth2-proxy's
  `X-Auth-Request-User`) is named there, and a forged copy of the default is then ignored. Proxies
  that do not strip client headers mean the proxy and NetworkPolicy must be the only way in; a
  forged value only changes the recorded author. A `SCRAP_ALLOWED_USER` check is left for later.
- **Helm.** `mcp.tokenSecret.{name,key}` names an existing Secret and key, wired to
  `SCRAP_MCP_TOKEN` by `secretKeyRef`; `identityHeader` sets the header. The chart never takes
  a token as a value (the schema rejects it), and its tests check no secret renders as a value.

## Consequences

- `/mcp` has a second layer behind the proxy's. Claude Code sends the token in a `headers`
  entry (it expands `${VAR}` there, so the token can stay in the environment).
- A token is shared by whoever holds it, and every MCP change is still author `claude`.
- Claude.ai connectors, which cannot send a custom header, cannot reach a token-guarded `/mcp`
  (an accepted limitation; no OAuth).
- Tokens are read at start: changing them means a restart.
