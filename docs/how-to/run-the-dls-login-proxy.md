# Run the DLS login proxy

This is for the scrap admins at DLS. Every DLS user's scrap (installed with
[](../tutorials/install-dls.md)) logs in through one central
[oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/) against DLS Keycloak. This page
sets it up and keeps it running.

## How it fits together

- The proxy runs in its own namespace, `scrap` by default. Only that namespace holds the
  Keycloak client secret and the proxy's cookie secret; users never see them.
- Each user's scrap has two Ingresses on `scrap-<fedid>.diamond.ac.uk`. The main one sends every
  request to the proxy first (ingress-nginx's `auth-url`), which needs a DLS login; scrap then
  lets in only that user's fedid, from the token the proxy passes on. The other has no login and carries `/mcp` (scrap's bearer token guards it) and
  `/oauth2`, which reaches the proxy through an `ExternalName` Service in the user's namespace.
- The proxy has no fixed callback address and no cookie domain, so each user's login and cookie
  belong to that user's host alone. That is why Keycloak needs one exact redirect URI per user.
- Any DLS login passes the proxy, on any user's host: the `auth-url` carries no
  `allowed_emails`, because DLS's ingress-nginx refuses an `@` or `%` in it. Each user's scrap
  admits only its owner, by the fedid in the access token (`preferred_username`): another DLS
  user who logs in there gets scrap's `401`. DLS Keycloak does not verify emails, so the proxy
  runs with `insecure_oidc_allow_unverified_email`; the email is not what lets anyone in.
- The proxy passes the user's Keycloak access token on (`pass_access_token`), and scrap checks
  it on every request ([](../explanations/decisions/0045-scrap-verifies-the-login-proxys-keycloak-token.md)).
  argus users cannot make NetworkPolicies, so a pod in the cluster can reach a user's scrap
  Service directly, but without a valid Keycloak token for that user it gets `401`; `/mcp` needs
  its bearer token. The proxy refreshes the session every minute, inside the access token's
  5 minutes. Without `offline_access`, a user stays logged in only as long as their DLS
  Keycloak session; when it ends, the next refresh fails and they log in again.
- The sessions are kept in a small Redis beside the proxy (`oauth2-proxy-redis`, one pod, part
  of the same release); the browser's cookie only names its session. DLS Keycloak's tokens make
  a session too big for one cookie, and a session split across cookies broke when requests
  overlapped a refresh. Redis saves nothing to disk, so restarting it (or a node drain moving
  it) logs everyone out once; restarting only the proxy pods does not. Its password is in the
  Secret `oauth2-proxy-redis`, since any pod in the cluster can reach its Service.

The chart side is `authProxy` ({ref}`k8s-auth-proxy`). The proxy is the upstream oauth2-proxy
chart, pinned in `deploy/dls/auth-proxy/install.sh`, with `deploy/dls/auth-proxy/values.yaml`.

## 1. Request the Keycloak client

Ask the DLS Keycloak team for one client in the `dls` realm
(`https://identity.diamond.ac.uk/realms/dls`):

- **Confidential** (client authentication on), **standard flow** only, with **PKCE** method
  `S256`.
- Client scopes `openid`, `email` and `profile` only (no `offline_access`).
- An **audience mapper** that adds the client's own ID to the access token's audience: oauth2-proxy
  checks it.
- **Valid redirect URIs**: one exact entry per user, `https://scrap-<fedid>.diamond.ac.uk/oauth2/callback`.
  No wildcards. Start with your own.
- **Access tokens that carry `preferred_username`** (the fedid): scrap reads it from the access
  token, not the ID token. Keycloak's default `profile` client scope maps it into the access
  token; check it has not been changed to the ID token only. The tokens also carry `email`,
  which the proxy checks against `email_domains`; it need not be verified.
- Confirmation that users **cannot change their username** in the `dls` realm: "Edit username"
  off, and not "Email as username" with emails users can edit. And that the access token's
  `preferred_username` comes from Keycloak's built-in username mapper, not from an attribute
  users can edit. scrap trusts it to name the owner.

Keep the client ID and secret for the next step. The user installer (`deploy/install-dls.sh`)
expects the client ID `scrap-central-proxy`; with a different one, each user sets
`SCRAP_OIDC_CLIENT_ID`.

Also ask the argus admins to confirm that user namespaces may have `ExternalName` Services, and
that their ingress-nginx allows the `auth-url` and `auth-signin` annotations (its
`annotations-risk-level` setting can block them).

## 2. Install the proxy

You need the namespace (`scrap`, or another that only the admins use) and the right to make
Secrets and Deployments in it. On a DLS machine:

```sh
module load argus
git clone https://github.com/gilesknap/scrap.git
cd scrap
sh deploy/dls/auth-proxy/install.sh
```

The first run asks for the client ID and secret (the secret is not shown as you type). It makes
the Secret `oauth2-proxy-keycloak` with the keys `client-id`, `client-secret` and a generated
`cookie-secret`, and the Secret `oauth2-proxy-redis` with a generated Redis password. Then it
installs the chart as the release `oauth2-proxy`: two proxy pods, a disruption budget, one Redis
pod, and no Ingress. The proxy answers inside the cluster at
`oauth2-proxy.scrap.svc.cluster.local`, where every user's installer points by default.

Re-run the script after changing `values.yaml` or the pinned chart version. It keeps the
Secrets. A run that makes either Secret (the first, or after you deleted one) also restarts Redis
and the proxy, since their pods read the Secrets only when they start; that logs everyone out
once. The first run after the move to Redis sessions makes the Redis Secret, so it logs everyone
out once too.
With a namespace other than `scrap`, users must set `SCRAP_AUTH_NAMESPACE` to it when they
run their installer.

## 3. Add users

After installing, each user asks you to add their login address,
`https://scrap-<fedid>.diamond.ac.uk/oauth2/callback`. Collect them and send them to the Keycloak
team in batches, to add to the client's valid redirect URIs. Until a user's address is added, their
login fails with Keycloak's "Invalid parameter: redirect_uri".

## Rotate the client secret

Ask the Keycloak team for a new client secret, then put it in the Secret from a private file and
restart the proxy:

```sh
tmp=$(mktemp -d)
chmod 700 "$tmp"
printf 'New client secret: '; stty -echo; read -r s; stty echo; echo
printf '{"data":{"client-secret":"%s"}}' "$(printf %s "$s" | base64 | tr -d '\n')" >"$tmp/patch.json"
unset s
kubectl -n scrap patch secret oauth2-proxy-keycloak --type merge --patch-file "$tmp/patch.json"
rm -rf "$tmp"
kubectl -n scrap rollout restart deploy/oauth2-proxy
```

To sign everyone out, restart Redis (`kubectl -n scrap rollout restart deploy/oauth2-proxy-redis`),
or replace `cookie-secret` the same way, with 32 random bytes in URL-safe
base64 (`head -c 32 /dev/urandom | base64 | tr -- '+/' '-_'`).

## Check it

```sh
kubectl -n scrap get pods,svc,pdb
kubectl -n scrap logs deploy/oauth2-proxy
kubectl -n scrap logs deploy/oauth2-proxy-redis
curl -sI https://scrap-<fedid>.diamond.ac.uk/ | head -n 3
```

The pods are ready, and the `curl` answers `302` to `/oauth2/start` on the same host. Opened in a
browser, the address goes to the DLS login and then back to scrap. A `500` from the user's host
usually means the proxy is down or the user's Ingress names the wrong Service: check the
`authProxy.service` in their release (`helm -n <fedid> get values scrap`).
