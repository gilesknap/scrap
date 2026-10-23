# Try scrap on your LAN

In this tutorial you run scrap as a single container on a laptop, a Raspberry Pi or a home PC,
and open it from your phone over your home network or Tailscale. It takes a few minutes, needs no
dedicated user and no systemd, and is the quickest way to see what scrap does. At the end you can
browse, search, edit and capture pages from your phone, and Claude Code on the same machine can
search and write them.

This is a trial install, not a hardened one. For a lasting setup on a server, see
[](install-server.md); for a cluster, see [](install-kubernetes.md).

```{warning}
scrap has **no login**. Anyone who can reach the port can read and change everything. Use this
only on a network you trust (your home LAN, your own tailnet), never on a public address, and
never with a port forward on your router.
```

## What you get, and what you do not

How far you get depends on how your phone reaches scrap. There are three tiers; the tutorial
takes you through them in order and you can stop at any of them.

| Tier | Phone reaches scrap by | You get | You do not get |
| --- | --- | --- | --- |
| A. LAN | `http://<lan-address>:8000` | Browse, search, edit and capture in the web page | Install as an app, Android share target, offline queue |
| B. Tailscale | `http://<tailscale-address>:8000` | The same as A, from anywhere | The same limits as A |
| C. Tailscale Serve | `https://<host>.<tailnet>.ts.net` | Everything: install, share target, offline queue | Nothing missing |

The limits in A and B come from the browser, not from scrap: the app install, the share target
and the offline queue need a *secure context*, which means HTTPS or `localhost`. Plain HTTP to a
LAN address is neither.

## What you need

- A machine with [podman](https://podman.io) or Docker (the commands below use `podman`; Docker
  takes the same arguments). The image is built for amd64 and arm64, so a Raspberry Pi 4 or 5
  with a 64-bit OS works.
- `curl`, and a phone on the same network.
- Optional, for Claude to read your photos and tag your notes: an
  [Anthropic API key](https://console.anthropic.com/). Capture, search and editing work without
  one.
- Optional, for tiers B and C: [Tailscale](https://tailscale.com/download) on this machine and on
  your phone, both logged in to the same tailnet.

## Find your address

Find the machine's LAN address, for example `192.168.1.10`:

```
hostname -I
```

Use the address your phone can reach (usually the first one). A Tailscale address, if you have
one, starts `100.` and is printed by `tailscale ip -4`.

## Write the settings file

scrap is configured with environment variables. Put them in a file rather than on the command
line, so a key never shows in your shell history or in `ps`. Create it readable by you only:

```
mkdir -p ~/.config/scrap
umask 077
cat > ~/.config/scrap/env <<'EOF'
SCRAP_PUBLIC_URL=http://192.168.1.10:8000
TZ=Europe/London
EOF
```

Replace the address with yours (add your Tailscale address too, comma separated, if you will use
tier B: `SCRAP_PUBLIC_URL=http://192.168.1.10:8000,http://100.64.0.7:8000`). Replace `TZ` with
your own time zone; without it the server runs on UTC and `due:today` follows the wrong day
around midnight.

`SCRAP_PUBLIC_URL` matters for one thing: `/mcp`, the endpoint Claude uses, answers only the
loopback addresses and the addresses listed there, and replies `421 Invalid Host header` to any
other. The web page does not care. Page links that Claude gives you also start with the first
address in it.

Now the optional part, which is recommended. Add these two lines to the same file with your
editor, as plain `KEY=value` lines without quotes:

```
SCRAP_INGEST=on
ANTHROPIC_API_KEY=<your key>
```

With them, a background worker sends photos to Claude for their text, a description, tags and a
redrawing, and tags and summarises text pages. It costs money, so a daily budget pauses it
(`SCRAP_BUDGET_DAY_USD`, default 3 dollars; see [](../reference/api.md)). Without them scrap
still captures and searches; it just does not read anything. To use a Claude subscription
instead of a key, see [](ingest-with-claude-seat.md).

## Run the container

```
podman run -d --name scrap --restart unless-stopped \
    -p 8000:8000 -v scrap-data:/data --env-file ~/.config/scrap/env \
    ghcr.io/gilesknap/scrap:0.2.2 serve --host 0.0.0.0 --port 8000
```

This pulls the image, which is public (no login needed), and starts scrap. In turn:

- `-p 8000:8000` publishes the port on **every** network interface of the machine. That is what
  lets your phone in, and it is also why the warning above matters. To keep it to one address,
  write `-p 192.168.1.10:8000:8000`.
- `-v scrap-data:/data` is a named volume holding the database and your files. Always give the
  data a volume: without one it goes to an anonymous volume that is easy to lose.
- `--host 0.0.0.0` is needed inside the container, because the default `127.0.0.1` cannot be
  reached from a published port.
- `--restart unless-stopped` brings it back after a reboot (with Docker; podman needs a systemd
  unit for that, which is what [](install-server.md) sets up).

Check it, from the machine itself:

```
curl http://127.0.0.1:8000/healthz
curl -X POST http://127.0.0.1:8000/api/captures -H 'Content-Type: application/json' \
  -d '{"id": "01JABCDEFGHJKMNPQRSTVWXYZ0", "text": "First note"}'
```

The first prints `{"status":"ok","version":"0.2.2",...}`. The second creates a page and prints
its id and slug; `id` is a ULID the client makes, so sending the same one again is a safe retry.

On a firewalled machine, allow port 8000 from your LAN only (for example `sudo ufw allow from
192.168.1.0/24 to any port 8000`). Docker publishes ports around `ufw`, so check from your phone
rather than trusting the rule.

## Tier A: open it on your phone over the LAN

On your phone, open `http://192.168.1.10:8000/` (your address). You see your first note. Try
capturing a note and a photo, searching, and editing a page. See [](../how-to/use-the-pwa.md) for
what the web app does.

Over plain HTTP the browser will not offer to install the app, the share target does not exist
and captures made while the phone is offline are not queued: the page must be open and the
machine reachable. That is the limit of this tier.

## Tier B: reach it from anywhere over Tailscale

If this machine and your phone are both on your tailnet, the same published port is already
reachable on the machine's Tailscale address. On your phone, open `http://100.64.0.7:8000/`
(`tailscale ip -4` prints yours), or `http://<machine-name>:8000/` with MagicDNS. Remember to
list that address in `SCRAP_PUBLIC_URL` if you use Claude from another machine (see the next
section).

It is still plain HTTP, so it has the same limits as tier A, but it works away from home. Tailscale
encrypts the traffic between the devices.

## Tier C: HTTPS with Tailscale Serve, for the full phone experience

[Tailscale Serve](https://tailscale.com/kb/1312/serve) gives scrap a real HTTPS address on your
tailnet, which is a secure context. It needs [HTTPS certificates and
MagicDNS](https://tailscale.com/kb/1153/enabling-https) enabled for the tailnet. Then:

```
sudo tailscale serve --bg --https=443 http://127.0.0.1:8000
tailscale serve status
```

`status` prints the address, `https://<host>.<tailnet>.ts.net`. Open it on your phone, and add
the address to the settings file so `/mcp` accepts it:

```
SCRAP_PUBLIC_URL=https://<host>.<tailnet>.ts.net
```

Then recreate the container so it reads the file (`podman rm -f scrap`, then run the command from
"Run the container" again; the data volume keeps your pages). In your phone's browser, use *Add
to Home screen* or *Install app*. The Android share target and the offline queue now work. Never
use `tailscale funnel`, which opens it to the internet.

For the hardened version of this (a dedicated user, a Unix socket instead of a published port,
systemd), follow [](install-server.md), which does not repeat the Serve details.

## Connect Claude Code

On the same machine, loopback always works, so no `SCRAP_PUBLIC_URL` is needed:

```
claude mcp add --transport http --scope user scrap http://127.0.0.1:8000/mcp
```

Start `claude` and ask it to search your pages. On another machine on the LAN or tailnet, use the
address that machine reaches scrap at (for example `http://192.168.1.10:8000/mcp`), which must be
in `SCRAP_PUBLIC_URL`. See [](../how-to/connect-claude-code.md) for the details and
[](../reference/mcp.md) for the tools.

## Keep your data

The image runs as an unprivileged user (uid 10001). A named volume works as it is. If you would
rather use a host folder, it must be writable by that user, or scrap fails with "Permission
denied" on `/data`: with Docker add `--user "$(id -u):$(id -g)"`, with rootless podman add
`--userns=keep-id:uid=10001,gid=10001`, and on SELinux systems (Fedora, RHEL) add `:Z` to the
volume.

To copy everything into a second volume while scrap runs:

```
podman run --rm -v scrap-data:/data -v scrap-backup:/backup \
    ghcr.io/gilesknap/scrap:0.2.2 backup /backup
```

That copy is local only; copy it off the machine to survive losing it. To update, pull a new
release tag, remove the container and run it again: the volume keeps your data. Keep the env file
out of any repository: the key shows in plain text in `podman inspect`.

## Running from a checkout instead

If you would rather not use a container, from a checkout (Python 3.11 or newer, [uv](https://docs.astral.sh/uv/),
and Node 22 to build the web app) `uv run scrap serve --data-dir ./data --host 0.0.0.0 --port 8000`
serves the same thing. The container is simpler, because the web app is already built into it.

```{note}
**What has been checked.** On 23 Oct 2026 the commands above were run by hand on Ubuntu with
rootless podman and the published `ghcr.io/gilesknap/scrap:0.2.2` image: the container with a
named volume and an env file; `/healthz` and a `curl` capture (201) on both the LAN and the
Tailscale address, with the page then listed; the home page loading from the LAN address;
`/mcp` accepting the LAN address when it was in `SCRAP_PUBLIC_URL` and returning 421 for the
Tailscale address when it was not, and 200 for both once both were listed; and restarting the
container with the same volume keeping the page, with `SCRAP_INGEST=on` reporting ingest enabled
(a placeholder key, so no real Claude call was made). Not checked: a phone (tiers A and B and the
browser limits are as documented by browsers, not observed here), `tailscale serve` with
`--https=443` in tier C (the server install tutorial runs the Serve flow), `claude mcp add`
against this container, Docker rather than podman, a Raspberry Pi, the `backup` command, and the
checkout alternative.
```

## Next steps

- A lasting install, with its own user, a socket and systemd: [](install-server.md).
- Run it on a cluster: [](install-kubernetes.md).
- Ingest from a Claude subscription instead of an API key: [](ingest-with-claude-seat.md).
- Every setting and the HTTP API: [](../reference/api.md).
- Update, back up and fix a single-server install: [](../how-to/deploy-single-server.md).
