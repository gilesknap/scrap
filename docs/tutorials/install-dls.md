# Install scrap at DLS

In this tutorial you run scrap in your own namespace on the DLS argus Kubernetes cluster, with one
script. At the end the web app and the MCP endpoint answer on `scrap-<fedid>.diamond.ac.uk`, and
the pages you make public on `pages-<fedid>.diamond.ac.uk`, all only from the DLS network.

Who can get in:

- **The web app**: only you. It asks for your DLS login (Keycloak) and lets in only your own
  email address.
- **`/mcp`**: whoever has your bearer token, which the installer makes and shows you once.
- **Your public pages**: anyone on the DLS network. Only the pages you make public are there.

## What you need

- A DLS account. Your namespace is named after your fedid, which is also your Linux username.
- A Claude API key, for ingest (reading photos and tagging pages). Without one, photos queue and
  nothing more happens.

## 1. Load argus

```
module load argus
```

This puts `kubectl` and `helm` on your path and selects your own namespace.

## 2. Run the installer

```
curl -fsSL https://raw.githubusercontent.com/gilesknap/scrap/main/deploy/install-dls.sh | sh
```

It:

1. asks for your Claude API key (input hidden; Enter skips ingest);
2. creates a Secret `scrap-secrets` holding the key, a generated `/mcp` bearer token and a
   generated upload token for your public pages;
3. installs the latest scrap release with Helm, with Ingresses for `scrap-<fedid>.diamond.ac.uk`
   and `pages-<fedid>.diamond.ac.uk` on argus's `nginx` ingress, served over HTTPS by its
   `*.diamond.ac.uk` certificate;
4. puts the web app behind the DLS login, letting in only your email address, which it reads from
   your namespace;
5. makes `/dls/science/users/<fedid>/scrap` (mode 700, if it is new) and keeps the nightly backups there, with
   scrap's pods running as you, so the backups are your files;
6. prints the Service IP, your bearer token (once), and what to do next.

It is safe to re-run: a re-run upgrades to the latest release and never overwrites the Secret. A
Secret made by an older installer gets only the upload token added. Set `SCRAP_VERSION` to install a particular release.
`SCRAP_BACKUP_DIR` moves the backups (empty keeps them on a volume in the cluster). If the
installer stops with "Cannot find your email address", set `SCRAP_EMAIL` to your DLS email
address (`first.last@diamond.ac.uk`) and run it again. The header of the script lists every
setting.

Keep the token in a password manager. To see it again:

```
kubectl get secret scrap-secrets -o jsonpath='{.data.SCRAP_MCP_TOKEN}' | base64 -d; echo
```

## 3. Ask for the DNS names

Names under `diamond.ac.uk` are not made for you: raise a request at
<https://jira.diamond.ac.uk/servicedesk/customer/portal/2/create/156> asking for
`scrap-<fedid>.diamond.ac.uk` and `pages-<fedid>.diamond.ac.uk` to be set up on the argus ingress
for your namespace. The installer lists only the names that do not resolve yet. Until they exist,
look at scrap with a port-forward:

```
kubectl port-forward svc/scrap 8000:80
```

and open <http://127.0.0.1:8000/>. The login, the phone app and `/mcp` need the DNS names.

## 4. Ask for your login address

Ask a scrap admin to add your login address to the Keycloak client:

```
https://scrap-<fedid>.diamond.ac.uk/oauth2/callback
```

Until it is added, logging in to the web app fails with an invalid redirect error. `/mcp` does not
need it. Admins: see [](../how-to/run-the-dls-login-proxy.md).

## Your backups

scrap backs up every night at 03:30 (UTC) to `/dls/science/users/<fedid>/scrap` on the DLS
filesystem, one folder per run, named for its time (like `20261104T033000Z`). It keeps the last 7
daily runs, and on the 1st of each month a copy in the `monthly/` folder, keeping the last 12 of
those. The folder is yours (mode 700 when the installer makes it) and the backup pods run as you, so
the backups are your files. To put them elsewhere, set `SCRAP_BACKUP_DIR` before you run the
installer. To restore from them, see [below](#install-dls-restore).

## 5. Use it

- **Phone:** to use scrap from your phone, you must first add the phone to the DLS VPN; follow DLS
  IT's VPN instructions for that. Then, on the VPN, open `https://scrap-<fedid>.diamond.ac.uk/`,
  log in with your DLS account on the login page that shows the first time, and install the app.
- **Browser:** on a DLS machine, open `https://scrap-<fedid>.diamond.ac.uk/` and log in with your
  DLS account.

## 6. Connect Claude Code

Claude Code reaches scrap at `/mcp` with your bearer token. Claude Code runs a small helper
script each time it connects, and the helper reads the token from a private file. Do this once,
on a DLS machine, after `module load argus`.

**1. Save the token** in `~/.config/terminal-config/.env`, readable only by you:

```sh
mkdir -p ~/.config/terminal-config
touch ~/.config/terminal-config/.env
chmod 600 ~/.config/terminal-config/.env
token=$(kubectl get secret scrap-secrets -o jsonpath='{.data.SCRAP_MCP_TOKEN}' | base64 -d)
if [ -n "$token" ]; then
  printf 'SCRAP_MCP_TOKEN=%s\n' "$token" >> ~/.config/terminal-config/.env
else
  echo "No token: check kubectl get secret scrap-secrets"
fi
unset token
```

The file is private before the token goes in, and nothing is written if `kubectl` fails.

**2. Make the helper** `~/.claude/scrap-headers.sh`:

```sh
mkdir -p ~/.claude
cat > ~/.claude/scrap-headers.sh <<'EOF'
#!/bin/sh
# Headers for scrap's /mcp: the bearer token
set -a; . ~/.config/terminal-config/.env; set +a
printf '{"Authorization":"Bearer %s"}\n' "$SCRAP_MCP_TOKEN"
EOF
chmod 700 ~/.claude/scrap-headers.sh
```

**3. Add scrap to Claude Code**, for all your projects:

```sh
claude mcp add-json --scope user scrap \
  "{\"type\":\"http\",\"url\":\"https://scrap-$USER.diamond.ac.uk/mcp\",\"headersHelper\":\"$HOME/.claude/scrap-headers.sh\"}"
```

**4. Check it.** `claude mcp list` shows `scrap` as connected. Ask Claude to search your pages.

In claude-sandbox, do steps 2 to 4 inside the container, and in the helper's `set -a` line use
`/user-terminal-config/.env`, where claude-sandbox mounts the same file. To install the `sc`
commands and skills, see [](../how-to/connect-claude-code.md).

```{note}
Only Claude Code on the DLS network can reach scrap's `/mcp`. Claude.ai's hosted connectors and
cloud sessions cannot reach a DLS-internal address.
```

## Publish pages

A page you make public is copied to your own static site, `https://pages-<fedid>.diamond.ac.uk/`,
where anyone on the DLS network can read it without logging in. scrap itself stays private. In the
app, open a page's **Share** menu and choose **Make public…**. To take a page down, make it private
again (**Make private** in the Share menu). What goes public with a page is in [](../how-to/publish-pages.md).

## More

For everything the chart can do (backups, restore, upgrades), see [](../how-to/deploy-kubernetes.md).

(install-dls-restore)=
To restore from the backups in your directory, follow its restore steps with the changes in
{ref}`backups in a hostPath <k8s-restore-hostpath>`, and your namespace in place of `-n scrap`.
