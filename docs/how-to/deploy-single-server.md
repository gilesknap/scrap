# Deploy on a single server

Run scrap on one Linux machine (a VPS, a home server) as the same container image that a
cluster would run, under rootless podman, as a systemd user service. scrap listens on
`127.0.0.1` only; [Tailscale Serve](https://tailscale.com/kb/1312/serve) publishes it over HTTPS to
your tailnet and nowhere else.

Podman is the tested path. Docker works with the small changes in
{ref}`scrap-docker`. To run scrap on a Kubernetes cluster instead, see
[](deploy-kubernetes.md).

```{warning}
v0 of scrap has **no login**. Anyone who can reach its port can read and change everything.
Only expose it through Tailscale Serve (tailnet only, never Funnel), or put an authenticating
reverse proxy in front of it. Read {ref}`scrap-access` first.
```

```{warning}
scrap listens on `127.0.0.1`, so **every local account and process on the server** can read and
change all of its data, and can send its own `Tailscale-User-Login` header to be recorded as any
author (Tailscale Serve strips forged headers, but a direct local connection skips Serve). v0
assumes a single-purpose server or a dedicated VM with no untrusted local users or workloads. If
the server also runs things you do not fully trust (other people's services, agents with broad
permissions), keep only test data in scrap there, or give scrap its own VM.
```

## Prerequisites

- Linux with systemd (user services and `loginctl`), and an admin account with `sudo` for the
  one-off setup steps.
- Rootless [podman](https://podman.io) 4.4 or newer, with `uidmap` (`newuidmap`/`newgidmap`)
  installed.
- `git` and `curl`.
- [Tailscale](https://tailscale.com/download) on the server, logged in to your tailnet, with
  [HTTPS certificates](https://tailscale.com/kb/1153/enabling-https) and MagicDNS enabled for the
  tailnet.

## Create a dedicated user

Run scrap as its own unix user with no `sudo` rights, so its data and containers are separate
from everything else on the machine. As an admin:

```
sudo useradd --create-home --shell /bin/bash scrap
sudo loginctl enable-linger scrap
grep scrap /etc/subuid /etc/subgid
```

Linger keeps the user's services running when nobody is logged in, and starts them at boot.
`useradd` normally adds the `/etc/subuid` and `/etc/subgid` ranges that rootless podman needs; if
`grep` prints nothing, see {ref}`scrap-troubleshooting`.

Everything below runs **as that user**, in a real login session, so that `systemctl --user`
works: `ssh scrap@<host>`, or from an admin account `sudo machinectl shell scrap@` (`machinectl`
is in the `systemd-container` package). A plain `sudo -u scrap` or `su` does not set up the
user's systemd session.

## Get the image

Until a release is published to `ghcr.io/gilesknap/scrap`, build the image yourself, as the
`scrap` user (podman images belong to the user who built or pulled them):

```
git clone https://github.com/gilesknap/scrap.git
cd scrap
podman build -t localhost/scrap:dev .
podman run --rm localhost/scrap:dev --version
```

The build pulls a large build-stage image. To avoid keeping it under the `scrap` user, build as
another user and copy only the image across (with linger on, so the user's runtime directory
exists). The `scrap` user still needs its own clone of the repo for the install and update
steps below, so run the `git clone` above as `scrap` either way:

```
podman save localhost/scrap:dev |
    sudo -u scrap -H env XDG_RUNTIME_DIR=/run/user/$(id -u scrap) podman load
```

Once releases exist you can instead `podman pull ghcr.io/gilesknap/scrap:<version>` and put that
name in `SCRAP_IMAGE` (below).

The image runs scrap as an unprivileged user (uid 10001) and keeps all its data under `/data`.

## Install

From the clone:

```
./deploy/install.sh
```

The script:

- writes the settings files `~/.config/scrap/env` and `~/.config/scrap/ingest.env` if they do not
  exist yet (it never overwrites them);
- copies `scrap.service`, `scrap-backup.service` and `scrap-backup.timer` to
  `~/.config/systemd/user/`, and the backup script `scrap-backup` to `~/.local/lib/scrap/`;
- enables linger if it can (otherwise it prints the `sudo loginctl enable-linger` command);
- enables and starts `scrap.service` if the image named in the settings is present, and the daily
  backup timer only if that image has the `scrap backup` command (images built before it existed
  do not; re-run the script after updating the image);
- restarts a running `scrap.service` if the image it runs or its unit has changed (see
  {ref}`scrap-update`).

It is safe to re-run after pulling a newer version of the repo.

### Settings

The service's settings live in `~/.config/scrap/env`. It is read by systemd, not a shell, so use
plain `KEY=value` lines with absolute paths.

| Variable | Default | Meaning |
| --- | --- | --- |
| `SCRAP_IMAGE` | `localhost/scrap:dev` | Image to run. |
| `SCRAP_PORT` | `8790` | Port on `127.0.0.1` that scrap listens on. |
| `SCRAP_DATA` | `~/.local/share/scrap/data` | Database and files; mounted at `/data`. |
| `SCRAP_BACKUPS` | `~/.local/share/scrap/backups` | Where the backup job writes. |
| `SCRAP_BACKUP_KEEP` | `14` | Number of backup runs to keep (at least 1). |
| `SCRAP_MEMORY_MAX` | `1g` | Memory ceiling for the container. |

After changing a setting: `systemctl --user restart scrap`.

(scrap-ingest-settings)=
### Ingest settings

scrap's own settings go in `~/.config/scrap/ingest.env`, which podman passes into the container
(`--env-file`). `install.sh` creates it with mode 600 and every line commented out, so ingest is
off until you edit it. It holds the API key: keep it mode 600, never copy it into the repo, and do
not paste it anywhere it would be logged. Plain `KEY=value` lines, with no quotes (podman takes
the rest of the line literally). For example:

```
SCRAP_INGEST=on
ANTHROPIC_API_KEY=<your key>
SCRAP_BUDGET_DAY_USD=3
SCRAP_NOTIFY_URL=https://ntfy.sh/<your private topic>
```

Set `SCRAP_NOTIFY_URL`: without it, a pause (daily budget reached, credit or login problem, an
outage) is only visible when you next open scrap. An ntfy topic URL is itself a secret. Every
setting, with its default, is in the [API reference](../reference/api.md). After editing:
`systemctl --user restart scrap`.

## First run

```
systemctl --user status scrap
./deploy/smoke.sh
```

`smoke.sh` calls `/healthz` on the local port and should print `{"status":"ok",...}`. Logs:
`journalctl --user -u scrap`.

## Publish on your tailnet

As an admin on the server, publish the local port over HTTPS on a port that is not already in
use. Check first, and leave existing entries alone:

```
sudo tailscale serve status
sudo tailscale serve --bg --https=8446 http://127.0.0.1:8790
```

scrap is then at `https://<host>.<tailnet>.ts.net:8446` from devices on your tailnet. `--bg`
makes the setting persist across reboots. Check it from any tailnet device:

```
./deploy/smoke.sh https://<host>.<tailnet>.ts.net:8446
```

Use `--https=443` instead if the machine serves nothing else. Never use `tailscale funnel` for
scrap: that publishes it to the internet.

### Tailnet ACL: deny tagged servers by default

The default tailnet policy lets every device reach every other. Replace it with rules that let
your own (user-owned) devices reach the server, and give tagged devices (other servers, CI,
anything running unattended) no access unless you grant it. For example, with the server tagged
`tag:server`:

```json
"grants": [
  {"src": ["autogroup:member"], "dst": ["tag:server"], "ip": ["tcp:8446"]}
]
```

Then a compromised server elsewhere on your tailnet cannot reach scrap.

(scrap-access)=
## Access and identity

scrap v0 has no login code. Who may use it is decided by the network in front of it:

- **Behind Tailscale Serve** (recommended): the tailnet ACL is the gate. For requests from
  devices owned by a user, Serve adds identity headers such as `Tailscale-User-Login`, and scrap
  records that login as the author of each change. Tagged devices get no identity headers, so
  their changes are recorded under a fixed fallback author.
- **Anything else** (a public reverse proxy, a LAN port): put an authenticating reverse proxy in
  front, and keep scrap bound to `127.0.0.1`. Without Tailscale Serve, every change is recorded
  under the fixed fallback author. Do not let a proxy pass through `Tailscale-User-*` headers
  sent by clients.

Either way the network only guards the way in from outside. On the server itself, anything that
can open a connection to `127.0.0.1` gets full access (see the warning at the top). If you cannot
keep untrusted users and workloads off the server, run scrap on a dedicated host or VM.
Listening on a unix socket protected by file permissions, behind the proxy, would also close
this gap, but scrap v0 does not offer it yet.

(scrap-update)=
## Update

Build or pull the new image, then re-run the install script:

```
git -C ~/scrap pull
podman build -t localhost/scrap:dev ~/scrap      # or: podman pull <image>
~/scrap/deploy/install.sh
~/scrap/deploy/smoke.sh
```

`install.sh` restarts `scrap.service` when the image named in `SCRAP_IMAGE` is not the one the
running container was started from, or when the unit itself changed; otherwise it leaves it
running. A restart drops requests in flight (a capture being uploaded fails and the PWA retries
it), and a photo Claude is describing at that moment counts one failed try and is retried later.
After editing only a settings file, restart by hand: `systemctl --user restart scrap`.

`SCRAP_IMAGE` pinned to a release version changes only when you edit it.

## Backup and restore

`scrap-backup.timer` runs `scrap-backup.service` daily (about 03:30, and at the next start if the
machine was off). Each run starts a throwaway container from the same image that runs
`scrap backup` into a new timestamped directory under `SCRAP_BACKUPS`, then deletes all but the
newest `SCRAP_BACKUP_KEEP` runs. Only real directories named like a run
(`20261019T033000Z`) directly in `SCRAP_BACKUPS` are ever deleted; anything else there, including
symlinks, is left alone. A failed run removes its own directory and deletes nothing else. A
`SCRAP_BACKUP_KEEP` that is not a whole number of at least 1 fails the run. To back up now:

```
systemctl --user start scrap-backup
ls ~/.local/share/scrap/backups
```

The backup directory is a local copy only: copy it off the machine (restic, rsync, a cloud
bucket) to survive losing the server.

To restore, stop the service, run `scrap restore` from the image against the data directory, and
start again. See `scrap restore --help` for its arguments. The commands load the settings file
first so they use your `SCRAP_DATA`, `SCRAP_BACKUPS` and `SCRAP_IMAGE`:

```
systemctl --user stop scrap
set -a; . ~/.config/scrap/env; set +a
podman run --rm --userns=keep-id:uid=10001,gid=10001 \
    -v "$SCRAP_DATA:/data" -v "$SCRAP_BACKUPS:/backups" -e SCRAP_DATA_DIR=/data \
    "$SCRAP_IMAGE" restore --help
systemctl --user start scrap
```

The same pattern runs any other `scrap` command (for example `scrap export`) against the data.

## Uninstall

As the `scrap` user:

```
systemctl --user disable --now scrap.service scrap-backup.timer
rm ~/.config/systemd/user/scrap.service ~/.config/systemd/user/scrap-backup.*
rm -r ~/.local/lib/scrap
systemctl --user daemon-reload
podman rmi localhost/scrap:dev
```

As an admin, remove the Serve entry (`sudo tailscale serve --https=8446 off`). The data, backups
and the settings in `~/.config/scrap/` stay until you delete them; `sudo userdel --remove scrap` removes the
user and everything it owns.

(scrap-docker)=
## Using Docker instead

With Docker, edit the installed copies. In `scrap.service`: replace `/usr/bin/podman` with
`/usr/bin/docker`, drop `--replace`, `-d`, `--cgroups=split` and `--sdnotify=conmon`, change
`Type=notify` to `Type=simple`, remove `NotifyAccess` and `Delegate`, and drop `-i` from the `rm`
commands. In `~/.local/lib/scrap/scrap-backup`: replace `podman` with `docker` and drop
`--replace`. In both, replace `--userns=keep-id:uid=10001,gid=10001` with `--user <uid>:<gid>` of
the user that owns `SCRAP_DATA` and `SCRAP_BACKUPS` (`id -u`, `id -g`). Re-running `install.sh`
overwrites these edits. Membership of the `docker` group is equivalent to root, so on a shared
machine prefer rootless podman.

(scrap-troubleshooting)=
## Troubleshooting

**`podman` fails with "cannot find UID/GID for user" or "insufficient UIDs".** The user has no
subordinate ID range. As an admin:
`sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 scrap` (pick a range no
other user has, see `/etc/subuid`), then as `scrap`: `podman system migrate`.

**`systemctl --user` says "Failed to connect to bus".** You are not in a real login session for
the user. Log in with `ssh` or `sudo machinectl shell scrap@`.

**scrap stops when you log out, or does not start at boot.** Linger is off:
`loginctl show-user scrap -p Linger` must say `yes`; fix with `sudo loginctl enable-linger scrap`.

**Ingest pauses for an outage with "certificate verify failed" in the run's error.** The image
has no CA certificates, so no HTTPS call can succeed (Claude or the pause notification).
Images built from this repo's Dockerfile carry them; rebuild with a current checkout.

**The service fails with "address already in use".** Another process has the port:
`ss -ltnp | grep :8790`. Pick a free port in `SCRAP_PORT`, restart, and point
`tailscale serve` at the new port.

**Permission denied writing `/data`.** The data directory must be owned by the `scrap` user and
the container started with `--userns=keep-id:uid=10001,gid=10001` (the units do this). On
SELinux systems (Fedora, RHEL) also add `:Z` to the `--volume` options.

**The access log shows every client as the server's own address.** Rootless podman's network
(pasta) forwards connections so that local clients, including Tailscale Serve, appear to come
from one of the host's own addresses, which may be its public one. These lines are not outside
traffic.

**Anything else.** `journalctl --user -u scrap -e` and `podman logs scrap`.
