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

## Start from the README

Run scrap as in [Try it](../index.md#try-it) on the front page, which covers
the API key prompt, the container and connecting Claude Code. This page only adds what changes
when the browser or Claude is on another device.

## What you get, and what you do not

| Tier | Phone reaches scrap by | You get | You do not get |
| --- | --- | --- | --- |
| A. LAN | `http://<lan-address>:8000` | Browse, search, edit and capture in the web page | Install as an app, Android share target, offline queue |
| B. Tailscale (HTTP) | `http://<tailscale-address>:8000` | The same as A, from anywhere | The same limits as A |
| C. Tailscale Serve (HTTPS) | `https://<host>.<tailnet>.ts.net` | Everything | Nothing missing; see [](../how-to/use-scrap-on-your-phone.md) |

The limits in A and B come from the browser, not from scrap: the app install, the share target
and the offline queue need a *secure context*, which means HTTPS or `localhost`. Plain HTTP to a
LAN address is neither.

## Find your address

Find the machine's LAN address, for example `192.168.1.10`:

```
hostname -I
```

Use the address your other device can reach (usually the first one). A Tailscale address, if you
have one, starts `100.` and is printed by `tailscale ip -4`. For tier B, install
[Tailscale](https://tailscale.com/download) on this machine and on your phone, both logged in to
the same tailnet.

## Run it for other devices

The README command listens on loopback only. To be reachable from other devices, stop it and run
it again with `--host 0.0.0.0` and `SCRAP_PUBLIC_URL` set to the address(es) you will use,
comma separated:

```
podman rm -f scrap   # only if you started it with --name scrap
podman run -d --name scrap --restart unless-stopped --network=host -v scrap-data:/data \
    -e TZ=Europe/London \
    -e SCRAP_PUBLIC_URL=http://192.168.1.10:8000,http://100.64.0.7:8000 \
    -e SCRAP_INGEST=${ANTHROPIC_API_KEY:+on} -e ANTHROPIC_API_KEY \
    ghcr.io/gilesknap/scrap:0.11.0 serve --host 0.0.0.0
```

Set `ANTHROPIC_API_KEY` in your shell first as in the README, or leave it empty to skip it. Use
your own addresses and time zone; without `TZ` the server runs on UTC and `due:today` follows
the wrong day around midnight. To stop it, `podman stop scrap`; to run it again with new
settings, `podman rm -f scrap` and re-run the command (the `scrap-data` volume keeps your
pages). Docker takes the same arguments.

`SCRAP_PUBLIC_URL` matters to Claude, not the web page. `/mcp` answers only loopback and the
addresses listed there, and replies `421 Invalid Host header` to any other. Page links in
Claude's replies start with the first address, and the app opens a link to any listed address in
place, so Back returns to the page you were on. Claude Code on this machine needs none of it; on
another machine, use `claude mcp add` from the README with the LAN address, for example
`http://192.168.1.10:8000/mcp`.

`--network=host` publishes the port on **every** network interface, which is why the warning
above matters. On a firewalled machine, allow port 8000 from your LAN only (for example `sudo ufw
allow from 192.168.1.0/24 to any port 8000`), and check from your phone rather than trusting the
rule.

## Tier A: open it on your phone over the LAN

On your phone, open `http://192.168.1.10:8000/` (your address). Try capturing a note and a
photo, searching, and editing a page. See [](../how-to/use-the-pwa.md) for what the web app does.

Over plain HTTP the browser will not offer to install the app, the share target does not exist
and captures made while the phone is offline are not queued: the page must be open and the
machine reachable.

## Tier B: reach it from anywhere over Tailscale

If this machine and your phone are both on your tailnet, the same port is already reachable on
the machine's Tailscale address. Open `http://100.64.0.7:8000/` (`tailscale ip -4` prints yours),
or `http://<machine-name>:8000/` with MagicDNS, and list that address in `SCRAP_PUBLIC_URL` if
Claude connects through it. It is still plain HTTP, so it has the same limits as tier A, but it
works away from home, and Tailscale encrypts the traffic between the devices.

## Tier C: the full phone experience

For install, the Android share target and the offline queue you need HTTPS, which Tailscale Serve
provides. See [](../how-to/use-scrap-on-your-phone.md). Never use `tailscale funnel`, which opens
scrap to the internet.

## Keep your data

The image runs as an unprivileged user (uid 10001). A named volume works as it is. If you would
rather use a host folder, it must be writable by that user, or scrap fails with "Permission
denied" on `/data`: with Docker add `--user "$(id -u):$(id -g)"`, with rootless podman add
`--userns=keep-id:uid=10001,gid=10001`, and on SELinux systems (Fedora, RHEL) add `:Z` to the
volume.

To copy everything into a second volume while scrap runs:

```
podman run --rm -v scrap-data:/data -v scrap-backup:/backup \
    ghcr.io/gilesknap/scrap:0.11.0 backup /backup
```

That copy is local only; copy it off the machine to survive losing it. To update, pull a new
release tag, remove the container and run it again: the volume keeps your data.

## Next steps

- A lasting install, with its own user, a socket and systemd: [](install-server.md).
- Run it on a cluster: [](install-kubernetes.md).
- Ingest from a Claude subscription instead of an API key: [](ingest-with-claude-seat.md).
- Every setting and the HTTP API: [](../reference/api.md).
