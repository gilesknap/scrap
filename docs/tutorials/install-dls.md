# Install scrap at DLS

In this tutorial you run scrap in your own namespace on the DLS argus Kubernetes cluster, with one
script. At the end the web app and the MCP endpoint answer on `scrap-<fedid>.diamond.ac.uk`, only
from the DLS network, and `/mcp` also needs a bearer token.

```{warning}
scrap has **no login of its own**. Here the network is the gate for the web app: the hostname is
reachable only on the DLS LAN, and from your phone only once it is on the DLS VPN. `/mcp` has a second lock,
a bearer token. Do not publish the hostname anywhere wider.
```

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
2. creates a Secret `scrap-secrets` holding the key and a generated `/mcp` bearer token;
3. installs the pinned scrap release with Helm, with an Ingress for `scrap-<fedid>.diamond.ac.uk`
   on argus's `nginx` ingress, served over HTTPS by its `*.diamond.ac.uk` certificate;
4. makes `/dls/science/users/<fedid>/scrap` (mode 700, if it is new) and keeps the nightly backups there, with
   scrap's pods running as you, so the backups are your files;
5. prints the Service IP, your bearer token (once), and what to do next.

It is safe to re-run: it upgrades scrap and never overwrites the Secret. The release is pinned in
the script; set `SCRAP_VERSION` to choose another. `SCRAP_BACKUP_DIR` moves the backups (empty keeps
them on a volume in the cluster). `SCRAP_HOST` and `SCRAP_INGRESS_CLASS` adjust
the ingress; the header of the script lists every setting. Keep the hostname one level under
`diamond.ac.uk`, or the certificate does not cover it.

Keep the token in a password manager. To see it again:

```
kubectl get secret scrap-secrets -o jsonpath='{.data.SCRAP_MCP_TOKEN}' | base64 -d; echo
```

## 3. Ask for the DNS name

Names under `diamond.ac.uk` are not made for you: raise a request at
<https://jira.diamond.ac.uk/servicedesk/customer/portal/2/create/156> asking for
`scrap-<fedid>.diamond.ac.uk` to be set up on the argus ingress for your namespace.
The installer skips this step if the name already resolves. Until it exists, look at scrap with a
port-forward:

```
kubectl port-forward svc/scrap 8000:80
```

and open <http://127.0.0.1:8000/>. The phone app and `/mcp` need the DNS name.

## Your backups

scrap backs up every night at 03:30 (UTC) to `/dls/science/users/<fedid>/scrap` on the DLS
filesystem, one folder per run, named for its time (like `20261104T033000Z`). It keeps the last 7
daily runs, and on the 1st of each month a copy in the `monthly/` folder, keeping the last 12 of
those. The folder is yours (mode 700 when the installer makes it) and the backup pods run as you, so
the backups are your files. To put them elsewhere, set `SCRAP_BACKUP_DIR` before you run the
installer. To restore from them, see [below](#install-dls-restore).

## 4. Use it

- **Phone:** to use scrap from your phone, you must first add the phone to the DLS VPN; follow DLS
  IT's VPN instructions for that. Then, on the VPN, open `https://scrap-<fedid>.diamond.ac.uk/` and
  install the app.
- **Browser:** on a DLS machine, open `https://scrap-<fedid>.diamond.ac.uk/`.

## 5. Connect Claude Code

Claude Code reaches scrap at `/mcp` with your bearer token. Claude Code runs a small helper
script each time it connects, and the helper reads the token from a private file. Do this once,
on a DLS machine, after `module load argus`.

**1. Save the token** in `~/.config/terminal-config/.env`, readable only by you:

```sh
mkdir -p ~/.config/terminal-config
printf 'SCRAP_MCP_TOKEN=%s\n' \
  "$(kubectl get secret scrap-secrets -o jsonpath='{.data.SCRAP_MCP_TOKEN}' | base64 -d)" \
  >> ~/.config/terminal-config/.env
chmod 600 ~/.config/terminal-config/.env
```

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

In claude-sandbox, the helper reads the same file at `/user-terminal-config/.env`: change the path
on its `set -a` line to that. To install the `sc` commands and skills, see
[](../how-to/connect-claude-code.md).

```{note}
Only Claude Code on the DLS network can use it. Claude.ai's hosted connectors and cloud sessions
cannot reach a DLS-internal address.
```

## More

For everything the chart can do (backups, restore, upgrades), see [](../how-to/deploy-kubernetes.md).

(install-dls-restore)=
To restore from the backups in your directory, follow its restore steps with the changes in
{ref}`backups in a hostPath <k8s-restore-hostpath>`, and your namespace in place of `-n scrap`.
