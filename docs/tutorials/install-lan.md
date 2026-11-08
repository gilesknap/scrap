# Try scrap on your LAN

In this tutorial you run scrap as a single container on a laptop, a Raspberry Pi or a home PC,
and open it from your phone or another machine over your home network or Tailscale. It takes a
few minutes, needs no dedicated user and no systemd.

This is a trial install, not a hardened one. For a lasting setup on a server, see
[](install-server.md); for a cluster, see [](install-kubernetes.md).

```{warning}
scrap has **no login**. Anyone who can reach the port can read and change everything. Use this
only on a network you trust (your home LAN, your own tailnet), never on a public address, and
never with a port forward on your router.
```

## 1. Find your address

Find the machine's LAN address, for example `192.168.1.10`:

```
hostname -I
```

Use the address your other device can reach (usually the first one). If you use
[Tailscale](https://tailscale.com/download) on this machine and your phone, `tailscale ip -4`
prints its Tailscale address too (it starts `100.`).

## 2. Run scrap

Enter your Anthropic API key (optional: it lets Claude read your photos and tag your pages; press
Enter to skip), then start the container, listening on every interface. `SCRAP_PUBLIC_URL` lists
the address(es) you will open it at, comma separated:

```
printf 'Anthropic API key (Enter to skip): '; read -rs ANTHROPIC_API_KEY; export ANTHROPIC_API_KEY
podman run -d --name scrap --restart unless-stopped --network=host -v scrap-data:/data \
    -e TZ=Europe/London \
    -e SCRAP_PUBLIC_URL=http://192.168.1.10:8000,http://100.64.0.7:8000 \
    -e SCRAP_INGEST=${ANTHROPIC_API_KEY:+on} -e ANTHROPIC_API_KEY \
    ghcr.io/gilesknap/scrap:{{ release_tag }} serve --host 0.0.0.0
```

Use your own addresses and time zone; without `TZ` the server runs on UTC and `due:today`
follows the wrong day around midnight. Docker takes the same arguments. If you already started
scrap from the README, `podman rm -f scrap` first: the `scrap-data` volume keeps your pages.

Check, from another machine on the LAN: `curl http://192.168.1.10:8000/healthz` prints
`{"status":"ok",...}`.

## 3. Open it on your phone

On your phone, open `http://192.168.1.10:8000/` (your address). Check: capture a note, then find
it with search. See [](../how-to/use-the-pwa.md) for what the web app does.

Over plain HTTP the browser will not offer to install the app, the share target does not exist
and captures made while the phone is offline are not queued (see the tiers below).

## 4. Connect Claude Code

On any machine on the LAN with [Claude Code](https://code.claude.com/docs):

```
claude mcp add --transport http --scope user scrap http://192.168.1.10:8000/mcp
```

Check: `claude mcp list` shows `scrap` as connected. Ask Claude "what are my recent scrap pages?".
To add the `sc` commands and skills, see [](../how-to/connect-claude-code.md).

## Details

### What you get, and what you do not

| Tier | Phone reaches scrap by | You get | You do not get |
| --- | --- | --- | --- |
| A. LAN | `http://<lan-address>:8000` | Browse, search, edit and capture in the web page | Install as an app, Android share target, offline queue |
| B. Tailscale (HTTP) | `http://<tailscale-address>:8000` | The same as A, from anywhere | The same limits as A |
| C. Tailscale Serve (HTTPS) | `https://<host>.<tailnet>.ts.net` | Everything | Nothing missing; see [](../how-to/use-scrap-on-your-phone.md) |

The limits in A and B come from the browser, not from scrap: the app install, the share target
and the offline queue need a *secure context*, which means HTTPS or `localhost`. Plain HTTP to a
LAN address is neither.

**Tier B.** If this machine and your phone are both on your tailnet, the same port is reachable
on the machine's Tailscale address: `http://100.64.0.7:8000/`, or `http://<machine-name>:8000/`
with MagicDNS. It is still plain HTTP, with the limits of tier A, but it works away from home.

**Tier C.** For install, the Android share target and the offline queue you need HTTPS, which
Tailscale Serve provides. See [](../how-to/use-scrap-on-your-phone.md). Never use
`tailscale funnel`, which opens scrap to the internet.

### Addresses and `SCRAP_PUBLIC_URL`

The web page and the API answer loopback, any IP address, and the names listed in
`SCRAP_PUBLIC_URL`, and reply `421 Invalid Host header` to any other *name*, so list a MagicDNS or
LAN hostname if you open the app at it. `/mcp` answers only loopback and the listed addresses, so
list every address Claude Code will use, an IP address included. Page links in Claude's replies
start with the first address. To change a setting, `podman rm -f scrap` and run step 2 again.

### Firewall

`--network=host` publishes the port on **every** network interface, which is why the warning
above matters. On a firewalled machine, allow port 8000 from your LAN only (for example `sudo ufw
allow from 192.168.1.0/24 to any port 8000`), and check from your phone rather than trusting the
rule.

### Restarts

`--restart unless-stopped` brings scrap back after a crash. Docker also starts it at boot. With
rootless podman, it starts at boot only with `systemctl --user enable podman-restart.service`
and `loginctl enable-linger`; for a lasting install use [](install-server.md).

### Keep your data

The image runs as an unprivileged user (uid 10001). A named volume works as it is. If you would
rather use a host folder, it must be writable by that user, or scrap fails with "Permission
denied" on `/data`: with Docker add `--user "$(id -u):$(id -g)"`, with rootless podman add
`--userns=keep-id:uid=10001,gid=10001`, and on SELinux systems (Fedora, RHEL) add `:Z` to the
volume.

To copy everything into a second volume while scrap runs:

```
podman run --rm -v scrap-data:/data -v scrap-backup:/backup \
    ghcr.io/gilesknap/scrap:{{ release_tag }} backup /backup
```

That copy is local only; copy it off the machine to survive losing it. To update, pull a new
release tag, remove the container and run it again: the volume keeps your data. This page pins
`{{ release_tag }}`; the README's `latest` tag points to the newest release.

## Next steps

- A lasting install, with its own user, a socket and systemd: [](install-server.md).
- Run it on a cluster: [](install-kubernetes.md).
- Ingest from a Claude subscription instead of an API key: [](ingest-with-claude-seat.md).
- Every setting and the HTTP API: [](../reference/api.md).
