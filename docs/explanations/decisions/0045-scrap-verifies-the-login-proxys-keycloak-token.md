# 45. scrap verifies the login proxy's Keycloak token

Date: 2026-11-04

## Status

Accepted. Takes up the `SCRAP_ALLOWED_USER` check that
[](0023-bearer-token-on-mcp-and-an-identity-header-setting.md) left for later.

Amended 2026-11-06: the owner is checked by Keycloak username (the DLS fedid), not by email,
since DLS Keycloak does not verify emails. See [](#amendment-the-owner-is-the-fedid) at the
end.

## Context

At DLS each user's scrap sits behind one central oauth2-proxy, through ingress-nginx's external
auth (`authProxy` in the chart, [](../../how-to/run-the-dls-login-proxy.md)). That guards the
Ingress only. argus users cannot make NetworkPolicies, so any pod in the cluster can call a
user's scrap Service directly, and send its own `X-Auth-Request-Email`: scrap had no login of its
own and trusted that header as sent.

## Decision

- **scrap checks a Keycloak access token on every request**, when `SCRAP_OIDC_ISSUER` is set.
  Unset, nothing changes. The check is `src/scrap/oidc.py`: ASGI middleware outside all the
  others, so nothing (not the Host check, not a body read) runs before it.
- **Where the token comes from.** oauth2-proxy runs with `pass_access_token`, so its
  `/oauth2/auth` answer carries `X-Auth-Request-Access-Token`; the chart adds that header to
  ingress-nginx's `auth-response-headers`, which sets it on the request to scrap over any copy
  the client sent. A pod calling the Service has no such token for the owner, and cannot make
  one.
- **What is checked**, with PyJWT: the signature, against the keys at the `jwks_uri` of the
  issuer's discovery document (whose `issuer` must match); only RS256 and ES256, and only the
  algorithm the key is for, never `none` or a shared secret; `typ` `Bearer` (an access token,
  not an ID token; compared ignoring case); `iss` exactly
  `SCRAP_OIDC_ISSUER`; issued to our client (`azp` is `SCRAP_OIDC_CLIENT_ID`, or it is in `aud`,
  since Keycloak's access tokens have `aud: account` unless a mapper adds the client); `exp`,
  `nbf` and `iat` with 30 s of leeway; and `preferred_username` (the Keycloak username, at
  DLS the fedid; lower-cased) in `SCRAP_ALLOWED_USERS`. A token without it, or with one that
  is not a string, gets `401`. This allow-list is the only owner check: the token alone says only
  that someone at DLS logged in, and the Ingress's `auth-url` carries no `allowed_emails`
  (DLS's ingress-nginx refuses an `@` or `%` in it), so any DLS login passes the proxy, and
  another user gets scrap's `401`.
- **Exempt:** `/healthz` (the kubelet's probes carry no token) and `/mcp`, `/mcp/...`, which
  keep their own bearer token (ADR 23) on the Ingress without the login. So the issuer without
  an `/mcp` token (`SCRAP_MCP_TOKEN` or `SCRAP_MCP_TOKEN_FILE`) stops scrap starting: `/mcp`
  would be open to any pod.
- **Fail closed.** No token, or one that fails a check: `401` (JSON under `/api`, plain text
  elsewhere), no redirect (the Ingress does the login). Keys that cannot be fetched: `503`. Any
  other error: `401`. An issuer without a client ID or an allow-list, or one that is not https
  (loopback aside), stops scrap starting.
- **Keys.** Discovery runs on the first request, not at start, so a Keycloak outage is a `503`
  rather than a crash loop. Its `jwks_uri` must be https (http only on loopback, as for the
  issuer). scrap refreshes the key set after an hour, with its own back-off rather than
  `PyJWKClient`'s (whose cooldown starts only after a fetch that worked, so during an outage
  every request would fetch): one fetch at a time, never holding up other requests (one the
  cached keys cannot answer meanwhile gets `503`); after a failed fetch none for 10 s
  (`503`); and an unknown key ID refetches the set at most once per 30 s (`401` meanwhile).
  So, whatever tokens a pod sends, scrap makes at most one fetch per 10 s while Keycloak is
  down and one per 30 s for unknown key IDs, and a rotated key is picked up within 30 s. A
  key set that is not JSON, not an object, or has no usable signing key (only `use: sig` or
  unmarked keys count) is a failed fetch (`503`).
- **A stale key set.** While the hourly refresh is in flight the old set still answers, so
  the refresh costs nobody a `503`. If that refresh fails, the expired set is dropped and
  the web app answers `503` until a fetch works. Keeping it through an outage would also
  verify (signatures still check, and `exp` bounds each token), but a key Keycloak has
  removed may have been removed because it leaked, and scrap could not tell; an outage
  long enough to matter also stops logins and the proxy's refreshes, so little is lost by
  failing closed. A failed refetch for an unknown key ID before the hour is up keeps the set.
- **Fetching.** The standard library: http(s) only, no redirects, 5 s per socket operation,
  and the body read a piece at a time, given up past 10 s from the start or past 1 MiB
  (`503`). The request and headers are bounded per operation only, but a slow fetch holds
  no lock and blocks no other request.
- **Freshness.** Keycloak's access tokens last 5 minutes by default, so the proxy refreshes its
  session every minute (`cookie_refresh`) with its refresh token. Its scopes are `openid email
  profile` only: no `offline_access`, so a login lasts as long as the user's Keycloak session, and then
  the refresh fails and they log in again.
- **The author** of a change is the token's username (the fedid), the identity the check
  admitted, and no identity header is read (`SCRAP_IDENTITY_HEADER` is ignored while the
  check is on). `/mcp` changes stay Claude's.
- **Helm.** `authProxy.oidc.issuer` and `.clientId` are required with `authProxy.enabled`; the
  Deployment gets `SCRAP_OIDC_ISSUER`, `SCRAP_OIDC_CLIENT_ID` and `SCRAP_ALLOWED_USERS`
  (the lower-cased `allowedUsers`). The CronJobs serve no HTTP and do not.

## Consequences

- A pod that reaches the Service gets `401` on everything but `/healthz` and `/mcp`, and `/mcp`
  needs the bearer token. `/healthz` still answers anyone, as before.
- Keycloak's access tokens must carry `preferred_username` (its default `profile` scope maps
  it into the access token) and name the client in `azp`. Whether the email is verified does
  not matter.
- A token taken from the owner's browser is good for its few remaining minutes, as the login
  cookie is for longer: the check stops forgery, not theft.
- `kubectl port-forward` to the Service reaches `/healthz` and `/mcp` only; the web app needs
  the Ingress.
- The web app is unusable while Keycloak's keys cannot be had (after the cached hour), which is
  also when nobody can log in.

## Amendment: the owner is the fedid

The first version checked `email_verified` true and `email` in `SCRAP_ALLOWED_EMAILS`. DLS
Keycloak does not verify emails: real staff accounts' tokens carry `email_verified: false`.
The first login on argus failed in oauth2-proxy, which refuses an unverified email
(`email in id_token (giles.knap@diamond.ac.uk) isn't verified`, a `500`), and loosening the
proxy alone would only have moved the failure to scrap's `401`.

So the owner is the Keycloak username, `preferred_username`. At DLS that is the fedid, the
same identity that names the user's argus namespace (namespace `abc12345` is fedid
`abc12345`), so the installer takes it from the namespace. The `profile` scope carries it
into the access token. The proxy sets `insecure_oidc_allow_unverified_email`: it admits any
DLS login, as before, and each scrap admits only its owner. `SCRAP_ALLOWED_EMAILS` and
`authProxy.allowedEmails` are gone, not kept as aliases: they shipped in 1.6.0 a day earlier
and had no users but the owner, whose login never worked.

The proxy keeps `email_domains = ["diamond.ac.uk"]`: an unverified email is still one DLS
Keycloak holds for the account, and the domain check costs nothing. The author of a change
is now the username too: it is the identity the check admitted, while the email is not
checked at all.
