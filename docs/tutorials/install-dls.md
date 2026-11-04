# Install scrap at DLS

In this tutorial you run scrap in your own namespace on the DLS argus Kubernetes cluster, with one
script. At the end the web app and the MCP endpoint answer on `scrap-<fedid>.diamond.ac.uk`, only
from the DLS network, and `/mcp` also needs a bearer token.

```{warning}
scrap has **no login of its own**. Here the network is the gate for the web app: the hostname is
reachable only on the DLS LAN, and from your phone only over the DLS VPN. `/mcp` has a second lock,
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
4. makes `/dls/science/users/<fedid>/scrap` (mode 700) and keeps the nightly backups there, with
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

Names under `diamond.ac.uk` are not made for you: open a cloud team ticket asking for
`scrap-<fedid>.diamond.ac.uk` to point at the argus ingress (ingress-nginx) for your namespace.
The installer skips this step if the name already resolves. Until it exists, look at scrap with a
port-forward:

```
kubectl port-forward svc/scrap 8000:80
```

and open <http://127.0.0.1:8000/>. The phone app and `/mcp` need the DNS name.

## 4. Use it

- **Phone:** join the DLS VPN, open `https://scrap-<fedid>.diamond.ac.uk/` and install the app.
- **Claude Code**, on a DLS machine:

  ```
  claude mcp add --transport http scrap https://scrap-<fedid>.diamond.ac.uk/mcp \
      --header "Authorization: Bearer <your token>"
  ```

For everything the chart can do (backups, restore, upgrades), see [](../how-to/deploy-kubernetes.md).
