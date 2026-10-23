# Install scrap on a server

In this tutorial you run scrap on one Linux server, as a container under rootless podman, started
by a systemd user service. [Tailscale Serve](https://tailscale.com/kb/1312/serve) then publishes
it over HTTPS to your tailnet, so you can open it from your phone. At the end you have a running
service and its web app open on your phone.

It is the same container image a cluster would run. To run scrap on Kubernetes instead, see
[](../how-to/deploy-kubernetes.md). This page follows one happy path; every option, and the
update, backup, uninstall and troubleshooting steps, are in [](../how-to/deploy-single-server.md).

```{warning}
v0 of scrap has **no login**. Anyone who can reach it can read and change everything. Only
expose it through Tailscale Serve (tailnet only, never `tailscale funnel`).
```

```{warning}
On the server itself, **root, anyone with `sudo`, and anything running as the scrap user** can
open scrap's socket and read and change all its data. Run scrap as its own user with no `sudo`
rights, and run nothing else as that user. See {ref}`scrap-access`.
```

## What you need

- Linux with systemd (user services and `loginctl`), and an admin account with `sudo` for the
  one-off setup steps.
- Rootless [podman](https://podman.io), with `uidmap` (`newuidmap`/`newgidmap`) installed. The
  units have been run with podman 5.x; older versions are untested.
- `git` and `curl`.
- [Tailscale](https://tailscale.com/download) on the server, logged in to your tailnet, with
  [HTTPS certificates](https://tailscale.com/kb/1153/enabling-https) and MagicDNS enabled for the
  tailnet.

You do not need Python or Node on the server: the image carries everything scrap needs.

## Create a dedicated user

As an admin, create a user that does nothing but run scrap, and let its services run when nobody
is logged in:

```
sudo useradd --create-home --shell /bin/bash scrap
sudo loginctl enable-linger scrap
grep scrap /etc/subuid /etc/subgid
```

`grep` should print one line from each file; rootless podman needs those ID ranges. If it prints
nothing, see {ref}`scrap-troubleshooting`.

Everything from here to the Tailscale step runs **as that user**, in a real login session so that
`systemctl --user` works: `ssh scrap@<host>`, or from an admin account
`sudo machinectl shell scrap@`. A plain `sudo -u scrap` or `su` does not work.

## Get the image

Pull the newest release from [scrap's releases](https://github.com/gilesknap/scrap/releases);
this tutorial uses 0.1.0. The image is public, so no login is needed:

```
podman pull ghcr.io/gilesknap/scrap:0.1.0
podman run --rm ghcr.io/gilesknap/scrap:0.1.0 --version
```

The last command prints scrap's version. The install script and its units come from the repo, so
clone it too:

```
cd ~
git clone https://github.com/gilesknap/scrap.git
cd scrap
```

To run unreleased changes instead, build the image in the clone with
`podman build -t localhost/scrap:dev .` (the first build takes a while) and skip the `sed` step
below.

## Install the service

Still as `scrap`, in the clone:

```
./deploy/install.sh
```

The first run writes `~/.config/scrap/env` naming a local build, `localhost/scrap:dev`, and says
the image is not here yet. Point it at the release you pulled and run the script again:

```
sed -i 's|^SCRAP_IMAGE=.*|SCRAP_IMAGE=ghcr.io/gilesknap/scrap:0.1.0|' ~/.config/scrap/env
./deploy/install.sh
```

The script is safe to re-run. It:

- writes the settings files `~/.config/scrap/env` and `~/.config/scrap/ingest.env` if they do not
  exist yet, and never overwrites them;
- copies the systemd units (the service plus the backup, gc and related-pages timers) to
  `~/.config/systemd/user/` and its helper scripts to `~/.local/lib/scrap/`;
- enables and starts `scrap.service`, and enables each timer if the image has the command it
  runs;
- prints where scrap listens and the address to give Tailscale Serve.

If it still says the image is not here yet, check `SCRAP_IMAGE` against `podman images`.

Apart from `SCRAP_IMAGE`, the defaults in `~/.config/scrap/env` are what this tutorial uses:
`SCRAP_LISTEN=socket` (a Unix socket only you and root can open, no TCP port),
`SCRAP_DATA=~/.local/share/scrap/data`, `SCRAP_BACKUPS=~/.local/share/scrap/backups`,
`SCRAP_BACKUP_KEEP=14` and `SCRAP_MEMORY_MAX=1g`. The full table is in
[](../how-to/deploy-single-server.md). After changing a setting, run
`systemctl --user restart scrap`.

## Check that it runs

```
systemctl --user status scrap
./deploy/smoke.sh
```

`smoke.sh` calls `/healthz` on the socket and should print `{"status":"ok",...}`. If not, read the
logs with `journalctl --user -u scrap -n 50` or `podman logs scrap`.

## Publish it on your tailnet

Leave the `scrap` session. As an admin on the server, check what Serve already publishes, then add
scrap on a port that is free (the port is yours to choose; this tutorial uses 8446):

```
sudo tailscale serve status
sudo tailscale serve --bg --https=8446 unix:/run/user/$(id -u scrap)/scrap/scrap.sock
```

Leave any existing entries alone. `--bg` makes the setting persist across reboots. scrap is now at
`https://<host>.<tailnet>.ts.net:8446` for devices on your tailnet. Check it from a `scrap` login session on the server, passing the address to `smoke.sh`:

```
./deploy/smoke.sh https://<host>.<tailnet>.ts.net:8446
```

From any other tailnet device, `curl` the `/healthz` path of that address instead: `smoke.sh` also
checks the local socket first, so on a machine without scrap it fails before reaching the URL.

## Open it on your phone

On a phone that is on your tailnet, open the address above in Chrome (Android) and choose **Add to home
screen**, then **Install**. Open scrap from its icon and capture your first note. See
[](../how-to/use-the-pwa.md) for what each screen does.

## Optional: turn on Claude ingest

Photos are queued but not sent to Claude until you switch ingest on. As `scrap`, edit
`~/.config/scrap/ingest.env` (keep it mode 600, as `install.sh` created it) and uncomment or add:

```
SCRAP_INGEST=on
ANTHROPIC_API_KEY=<your key>
SCRAP_BUDGET_DAY_USD=3
SCRAP_NOTIFY_URL=https://ntfy.sh/<your private topic>
TZ=Europe/London
```

Use plain `KEY=value` lines with no quotes. Set `TZ` to your own time zone, otherwise `due:today`
follows UTC. Then restart:

```
systemctl --user restart scrap
```

Every ingest setting is described in {ref}`scrap-ingest-settings`.

## Next steps

- Connect Claude Code sessions to scrap over MCP: [](../how-to/connect-claude-code.md). It starts
  by adding `SCRAP_PUBLIC_URL=https://<host>.<tailnet>.ts.net:8446` to `ingest.env`; without it
  `/mcp` answers `421 Invalid Host header`.
- Bring in an existing vault: [](../how-to/import-a-vault.md).
- Look after the install, in [](../how-to/deploy-single-server.md): {ref}`scrap-update`, backup and
  restore (a daily backup timer is already running, but its copy stays on the server),
  {ref}`scrap-gc`, uninstalling and {ref}`scrap-troubleshooting`.
