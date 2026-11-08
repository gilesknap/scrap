# Install scrap at DLS

You get scrap in your own namespace on the DLS argus cluster, behind your DLS login, with Claude
Code connected and your public pages on `pages-<fedid>.diamond.ac.uk`.

## 1. Load argus

```
module load argus
```

This puts `kubectl` and `helm` on your path and selects your namespace (your fedid).

## 2. Run the installer

```
curl -fsSL https://raw.githubusercontent.com/gilesknap/scrap/main/deploy/install-dls.sh | sh
```

It asks for your Claude API key (optional; Enter skips) and shows your `/mcp` bearer token once:
keep it in a password manager.

Check: it prints `scrap <version> is running in namespace <fedid>.`, and `kubectl get pods` shows
the `scrap-…` pod READY `3/3` and `scrap-public-…` `Running`.

## 3. Ask for the DNS names

Raise a request at <https://jira.diamond.ac.uk/servicedesk/customer/portal/2/create/156> for
`scrap-<fedid>.diamond.ac.uk` and `pages-<fedid>.diamond.ac.uk` on the argus ingress for your
namespace. The installer lists the names that do not resolve yet; step 4 waits for them.

Check: `getent hosts scrap-<fedid>.diamond.ac.uk` prints an address.

## 4. Open it

On a DLS machine, open `https://scrap-<fedid>.diamond.ac.uk/` and log in with your DLS account.
On your phone, join the DLS VPN first, open the same address, log in and install the app.

Check: `claude mcp list` shows `scrap-dls` as connected. Ask Claude to search your pages. For the
`sc` commands and skills, see [](../how-to/connect-claude-code.md).

## Details

### What the installer does

- Makes the Secret `scrap-secrets`: your API key, a generated `/mcp` bearer token and an upload
  token for your public pages.
- Installs the latest scrap release with Helm, with Ingresses for `scrap-<fedid>` and
  `pages-<fedid>` on argus's `nginx` ingress (HTTPS, `*.diamond.ac.uk` certificate).
- Puts the web app behind the DLS login (Keycloak), letting in only your fedid. Another DLS user
  gets `401`, and so does a pod that calls scrap's Service directly. `/mcp` takes your bearer
  token. Your public pages are open to anyone on the DLS network.
- Keeps the database on the pod's own disk, with Litestream copying each change to your NFS
  volume within about a second ({ref}`k8s-litestream`). A normal restart or upgrade loses
  nothing; if the node dies, the last moments of writes are lost. If a pod stays in `Init`, it is
  refusing to start without your data: `kubectl logs deploy/scrap -c db-init` says why.
- Connects Claude Code ({ref}`install-dls-claude`).

### Re-running and settings

Re-running is safe: it upgrades to the latest release and never overwrites the Secret. Settings
go after the pipe (`curl ... | SCRAP_VERSION=1.7.0 sh`):

- `SCRAP_VERSION`: a particular release (with that version's script).
- `SCRAP_BACKUP_DIR`: where the backups go (empty keeps them on a volume in the cluster).
- `SCRAP_USER`: your fedid, for a namespace not named after it.
- `SCRAP_CLAUDE=off`: leave Claude Code alone.

The header of the script lists every setting. To see your bearer token again:

```
kubectl get secret scrap-secrets -o jsonpath='{.data.SCRAP_MCP_TOKEN}' | base64 -d; echo
```

(install-dls-claude)=
### Claude Code

The installer:

1. puts the token in `~/.config/terminal-config/.env` (mode 600) as `SCRAP_DLS_MCP_TOKEN=...`,
   replacing that line and keeping the others (a token set by hand must be only letters, digits
   and `._+/=-`);
2. writes the helper `~/.claude/scrap-dls-headers.sh` (mode 700):

   ```sh
   #!/bin/sh
   # Headers for scrap's /mcp at DLS: the bearer token, from the .env on the host, or where
   # claude-sandbox mounts it. Only the token's line is read: the .env is never run as shell.
   # It may start with `export `, end in a CR, or have its value in "" or ''.
   token=
   for f in "$HOME/.config/terminal-config/.env" /user-terminal-config/.env; do
       [ -r "$f" ] && token=$(tr -d '\r' <"$f" |
           sed -n 's/^export  *//; s/^SCRAP_DLS_MCP_TOKEN=//p' | tail -n 1)
       case $token in \"*\" | \'*\') token=${token#?}; token=${token%?} ;; esac
       [ -z "$token" ] || break
   done
   if [ -z "$token" ]; then
       echo "SCRAP_DLS_MCP_TOKEN not found in ~/.config/terminal-config/.env or /user-terminal-config/.env" >&2
       exit 1
   fi
   printf '{"Authorization":"Bearer %s"}\n' "$token"
   ```

3. adds the server `scrap-dls` for all your projects (with your `SCRAP_HOST`, if you set one):

   ```sh
   claude mcp add-json --scope user scrap-dls \
     "{\"type\":\"http\",\"url\":\"https://scrap-$USER.diamond.ac.uk/mcp\",\"headersHelper\":\"$HOME/.claude/scrap-dls-headers.sh\"}"
   ```

If `claude` is not on your path, or this fails, the installer still succeeds and prints the
command to run. Only Claude Code on the DLS network can reach `/mcp`; claude.ai's connectors and
cloud sessions cannot.

**An old `scrap` server.** A server named `scrap` for another scrap is left alone, and the `sc`
commands use `scrap` if it is there, else `scrap-dls`. If your `scrap` server points at this DLS
scrap (from an earlier version of this page), remove it, or every tool appears twice:
`claude mcp remove --scope user scrap`, and delete `~/.claude/scrap-headers.sh`.

### Claude Code in claude-sandbox

The installer does not reach claude-sandbox's own `~/.claude`. Run the installer on the host, so
the token is in the .env that claude-sandbox mounts at `/user-terminal-config/.env`. Inside the
container, save the same helper as `~/.claude/scrap-dls-headers.sh` (mode 700), then add the
server with your fedid (or `SCRAP_HOST`; and the container's home, if not `/root`):

```sh
claude mcp add-json --scope user scrap-dls \
  '{"type":"http","url":"https://scrap-<fedid>.diamond.ac.uk/mcp","headersHelper":"/root/.claude/scrap-dls-headers.sh"}'
```

### Before the DNS names exist

`kubectl port-forward svc/scrap 8000:80`, then <http://127.0.0.1:8000/healthz> shows
`"status":"ok"`. The web app needs your login's token, which comes through the Ingress, so it
waits for the names.

### Logging in

You stay logged in as long as your DLS Keycloak session lasts; when it ends, the web app and the
phone app take you to the DLS login again. If logging in fails with an invalid redirect error, ask
a scrap admin to add `https://scrap-<fedid>.diamond.ac.uk/oauth2/callback` to the Keycloak client
(admins: [](../how-to/run-the-dls-login-proxy.md)).

(install-dls-no-login)=
### Without a login, for testing

```{warning}
With the login off, **anyone on the DLS network, and any pod in the cluster, can read and change
every page**. Your bearer token still guards `/mcp`. Test data only.
```

```
curl -fsSL https://raw.githubusercontent.com/gilesknap/scrap/main/deploy/install-dls.sh | SCRAP_LOGIN=off sh
```

Everything else is as normal. Only exactly `off` does this; anything but `on` or `off` stops the
installer before it touches anything. To turn the login on, re-run without it: your Secret and
data are kept, and until that run succeeds the web app still has no login.

### Backups

Every night at 03:30 (UTC) to `/dls/science/users/<fedid>/scrap`, one folder per run (like
`20261104T033000Z`). It keeps the last 7, plus a copy on the 1st of each month in `monthly/`,
keeping the last 12. The folder is yours (mode 700 when the installer makes it) and the pods run as
you, so the backups are your files. `SCRAP_BACKUP_DIR` moves them.

### Publish pages

In the app, a page's **Share** menu, **Make public…** copies it to
`https://pages-<fedid>.diamond.ac.uk/`, readable by anyone on the DLS network without a login;
**Make private** takes it down. See [](../how-to/publish-pages.md).

(install-dls-restore)=
### Restore

Follow the restore steps in [](../how-to/deploy-kubernetes.md) (they restore with
`--stage --force`), with your uid and gid from `id` in the pod's `securityContext`, and leave out
`-n scrap` (argus selects your namespace). Your backups are in a hostPath, so also make the
changes for {ref}`backups in a hostPath <k8s-restore-hostpath>`, with the path
`/dls/science/users/<fedid>/scrap` (or your `SCRAP_BACKUP_DIR`). If you set `SCRAP_BACKUP_DIR`
empty, the backups are on a claim in the cluster instead: keep the how-to's `scrap-backups`
claim. argus accepts the pod as it is: it fills in the container's `privileged: false`, user and
resources itself.

For everything else the chart can do, see [](../how-to/deploy-kubernetes.md).
