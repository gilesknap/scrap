# Install scrap at DLS

In this tutorial you run scrap in your own namespace on the DLS argus Kubernetes cluster, with one
script. At the end the web app answers on `scrap-<fedid>.diamond.ac.uk`, your public pages on
`pages-<fedid>.diamond.ac.uk`, and Claude Code is connected to scrap.

Who can get in:

- **The web app**: only your own DLS login. Another DLS user who logs in gets `401`.
- **`/mcp`** (Claude Code): whoever has your bearer token, which the installer makes.
- **Your public pages**: anyone on the DLS network. Only the pages you make public are there.

You need a DLS account. Your namespace is named after your fedid, which is also your Linux
username. A Claude API key is optional: scrap uses it to read photos and tag pages.

## 1. Load argus

```
module load argus
```

This puts `kubectl` and `helm` on your path and selects your own namespace.

## 2. Run the installer

```
curl -fsSL https://raw.githubusercontent.com/gilesknap/scrap/main/deploy/install-dls.sh | sh
```

It asks for your Claude API key (input hidden; Enter skips it), installs scrap, connects Claude
Code, and shows your `/mcp` bearer token once. Keep the token in a password manager.

## 3. Ask for the DNS names

Raise a request at <https://jira.diamond.ac.uk/servicedesk/customer/portal/2/create/156> asking for
`scrap-<fedid>.diamond.ac.uk` and `pages-<fedid>.diamond.ac.uk` to be set up on the argus ingress
for your namespace. The installer lists only the names that do not resolve yet.

## 4. Open it

- **Phone:** add the phone to the DLS VPN first (follow DLS IT's VPN instructions). Then, on the
  VPN, open `https://scrap-<fedid>.diamond.ac.uk/`, log in with your DLS account (the login page
  shows the first time), and install the app.
- **Browser:** on a DLS machine, open `https://scrap-<fedid>.diamond.ac.uk/` and log in.

Claude Code is connected (once the DNS names exist; `claude mcp list` shows `scrap-dls`), if
`claude` was on your PATH when you ran the installer, else run the command it printed. Ask Claude
to search your pages. To add the `sc` commands and skills, see [](../how-to/connect-claude-code.md).

That is all. The rest of this page is details.

## Details

### What the installer does

1. It asks for your Claude API key. Without one, photos queue and nothing more happens.
2. It creates a Secret `scrap-secrets` holding the key, a generated `/mcp` bearer token and a
   generated upload token for your public pages.
3. It installs the latest scrap release with Helm, with Ingresses for `scrap-<fedid>` and
   `pages-<fedid>` on argus's `nginx` ingress, served over HTTPS by its `*.diamond.ac.uk`
   certificate.
4. It puts the web app behind the DLS login (Keycloak), letting in only your fedid, which is
   your namespace's name (in lower case). Pods in the cluster can reach scrap's Service directly,
   but scrap checks the login's token itself, so without your login they get `401`. You stay
   logged in as long as your DLS Keycloak session lasts; when it ends, the web app and the phone
   app take you to the DLS login again.
5. It makes `/dls/science/users/<fedid>/scrap` (mode 700, if it is new) for the nightly backups.
   scrap's pods run as you, so the backups are your files.
6. It puts scrap's database on the pod's own disk, not on your NFS volume, where SQLite is not
   safe, with Litestream copying each change to that volume ({ref}`k8s-litestream`).
7. It connects Claude Code (below).
8. It prints the Service IP, your bearer token (once), and what to do next.

**What can be lost.** While it is working, the copy follows each write by about a second, so if the
node dies, the last moments of writes are lost. A normal restart or upgrade loses nothing: the new
pod restores the database first. If the copy stops working (scrap notices by itself within about
20 minutes), scrap leaves the network until it works again, so the app shows it as unreachable;
writes in those minutes are at risk, and a later restart refuses to start without someone looking.
An install from before this moves over by itself when you re-run the installer, leaving the old
`/data/scrap.db` in place. If a pod ever stays in `Init`, it is refusing to start without your
data rather than starting empty: `kubectl logs deploy/scrap -c db-init` says why.

### Re-running and settings

It is safe to re-run: a re-run upgrades to the latest release and never overwrites the Secret. A
Secret made by an older installer gets only the upload token added. Settings go in the
environment, after the pipe (`curl ... | SCRAP_VERSION=1.7.0 sh`):

- `SCRAP_VERSION` installs a particular release. The script and chart go together, so an older
  release needs that version's script.
- `SCRAP_BACKUP_DIR` moves the backups (empty keeps them on a volume in the cluster).
- `SCRAP_USER` is your fedid, for a namespace not named after it.
- `SCRAP_CLAUDE=off` leaves Claude Code alone.

The header of the script lists every setting. To see your bearer token again:

```
kubectl get secret scrap-secrets -o jsonpath='{.data.SCRAP_MCP_TOKEN}' | base64 -d; echo
```

(install-dls-claude)=
### Claude Code

Claude Code reaches scrap at `/mcp` with your bearer token. It runs a small helper script each
time it connects, and the helper reads the token from a private file. The installer:

1. puts the token in `~/.config/terminal-config/.env` (mode 600, private before the token goes
   in), as `SCRAP_DLS_MCP_TOKEN=...`, replacing a line already there and keeping the others;
2. writes the helper `~/.claude/scrap-dls-headers.sh` (mode 700):

   ```sh
   #!/bin/sh
   # Headers for scrap's /mcp at DLS: the bearer token, from the .env on the host, or where
   # claude-sandbox mounts it.
   for f in "$HOME/.config/terminal-config/.env" /user-terminal-config/.env; do
       if [ -r "$f" ]; then set -a; . "$f"; set +a; break; fi
   done
   printf '{"Authorization":"Bearer %s"}\n' "$SCRAP_DLS_MCP_TOKEN"
   ```

3. adds the server `scrap-dls` to Claude Code for all your projects, replacing a `scrap-dls`
   already there:

   ```sh
   claude mcp add-json --scope user scrap-dls \
     "{\"type\":\"http\",\"url\":\"https://scrap-$USER.diamond.ac.uk/mcp\",\"headersHelper\":\"$HOME/.claude/scrap-dls-headers.sh\"}"
   ```

A server named `scrap` for another scrap, with its `scrap-headers.sh` and `SCRAP_MCP_TOKEN`, is
left alone. The `sc` commands use `scrap` if it is there, else `scrap-dls`.

If `claude` is not on your path, or this step fails, the installer still succeeds and prints the
command to run. `SCRAP_CLAUDE=off` skips all three.

For claude-sandbox, run the installer on the host (or a DLS machine). Inside claude-sandbox the
same helper and server work, because claude-sandbox mounts the .env at
`/user-terminal-config/.env`.

```{note}
Only Claude Code on the DLS network can reach scrap's `/mcp`. Claude.ai's hosted connectors and
cloud sessions cannot reach a DLS-internal address.
```

### Before the DNS names exist

Check scrap is up with a port-forward:

```
kubectl port-forward svc/scrap 8000:80
```

and open <http://127.0.0.1:8000/healthz>. The web app answers only with your login's token, which
comes through the Ingress, so it and the phone app need the DNS names.

### If logging in fails

If logging in fails with an invalid redirect error, ask a scrap admin to add
`https://scrap-<fedid>.diamond.ac.uk/oauth2/callback` to the Keycloak client. `/mcp` does not need
it. Admins: see [](../how-to/run-the-dls-login-proxy.md).

(install-dls-no-login)=
### Without a login, for testing

```{warning}
This is for trying scrap out, with test data only. With the login off, the web app has **no login
at all**: **anyone on the DLS network can read and change every page**, and any pod in the cluster
can too. Your bearer token still guards `/mcp`, but that does not protect the web app or its API.
```

To try scrap without the login, with test data only, set `SCRAP_LOGIN=off`:

```
curl -fsSL https://raw.githubusercontent.com/gilesknap/scrap/main/deploy/install-dls.sh | SCRAP_LOGIN=off sh
```

It checks no fedid (`SCRAP_USER` is not used), and everything else is as normal: the bearer token
on `/mcp`, Claude Code, backups, public pages and the database. The installer warns you up front
and again in its summary. Only exactly `off` does this: anything but `on` or `off` stops the
installer before it touches anything.

**To turn the login on**, re-run the installer without it. Your Secret and your data are kept. If
that run fails, nothing has been turned on: the web app still has no login until it succeeds.

### Your backups

scrap backs up every night at 03:30 (UTC) to `/dls/science/users/<fedid>/scrap` on the DLS
filesystem, one folder per run, named for its time (like `20261104T033000Z`). It keeps the last 7
daily runs, and on the 1st of each month a copy in the `monthly/` folder, keeping the last 12 of
those. The folder is yours (mode 700 when the installer makes it) and the backup pods run as you, so
the backups are your files. To put them elsewhere, set `SCRAP_BACKUP_DIR` before you run the
installer. Backups work from Litestream's copy of the database, not the live one, but still
run on the same node as the scrap pod. To restore from them, see [below](#install-dls-restore).

### Publish pages

A page you make public is copied to your own static site, `https://pages-<fedid>.diamond.ac.uk/`,
where anyone on the DLS network can read it without logging in. scrap itself stays private. In the
app, open a page's **Share** menu and choose **Make public…**. To take a page down, make it private
again (**Make private** in the Share menu). What goes public with a page is in [](../how-to/publish-pages.md).

(install-dls-restore)=
### Restore

To restore from the backups in your directory, follow the restore steps in
[](../how-to/deploy-kubernetes.md) with the changes in
{ref}`with Litestream <k8s-restore-litestream>` and {ref}`backups in a hostPath <k8s-restore-hostpath>`,
and your namespace in place of `-n scrap`.

### More

For everything the chart can do (backups, restore, upgrades), see [](../how-to/deploy-kubernetes.md).
