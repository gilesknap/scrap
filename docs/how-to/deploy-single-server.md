# Deploy on a single server

Run scrap on one Linux machine (a VPS, a home server) as the same container image that a
cluster would run, under rootless podman, as a systemd user service. scrap listens only on a Unix
socket that only its own user (and root) can open;
[Tailscale Serve](https://tailscale.com/kb/1312/serve) publishes it over HTTPS to your tailnet and
nowhere else. Why: [](../explanations/decisions/0018-unix-socket-for-single-server-installs.md).

Podman is the tested path. Docker works with the small changes in
{ref}`scrap-docker`. To run scrap on a Kubernetes cluster instead, see
[](deploy-kubernetes.md).

```{warning}
v0 of scrap has **no login**. Anyone who can reach it can read and change everything.
Only expose it through Tailscale Serve (tailnet only, never Funnel), or put an authenticating
reverse proxy in front of it. Read {ref}`scrap-access` first.
```

```{warning}
On the server itself, **root, anyone with `sudo`, and anything running as the scrap user** can
open the socket, read and change all of scrap's data, and send its own `Tailscale-User-Login`
header to be recorded as any author (Tailscale Serve strips forged headers, but a direct local
connection skips Serve). Other local users cannot. Run scrap as its own user with no `sudo`
rights, and run nothing else as that user. With `SCRAP_LISTEN=tcp` (below) **every local account
and process** can do the same through the port: keep that for single-purpose servers.
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
- copies `scrap.service`, `scrap-backup.service`, `scrap-backup.timer`, `scrap-gc.service` and
  `scrap-gc.timer` to `~/.config/systemd/user/`, and the scripts `scrap-run`, `scrap-backup` and
  `scrap-gc` to `~/.local/lib/scrap/`;
- enables linger if it can (otherwise it prints the `sudo loginctl enable-linger` command);
- enables and starts `scrap.service` if the image named in the settings is present, and the daily
  backup timer only if that image has the `scrap backup` command, and the nightly gc timer only if
  it has `scrap gc` (images built before them do not; re-run the script after updating the image);
- restarts a running `scrap.service` if the image it runs or its unit has changed (see
  {ref}`scrap-update`);
- prints where scrap listens, and a note if that is a TCP port (see {ref}`scrap-listen`).

It is safe to re-run after pulling a newer version of the repo.

### Settings

The service's settings live in `~/.config/scrap/env`. It is read by systemd, not a shell, so use
plain `KEY=value` lines with absolute paths.

| Variable | Default | Meaning |
| --- | --- | --- |
| `SCRAP_IMAGE` | `localhost/scrap:dev` | Image to run. |
| `SCRAP_LISTEN` | `socket` | `socket`: only the Unix socket `$XDG_RUNTIME_DIR/scrap/scrap.sock`. `tcp`: `SCRAP_PORT` on `127.0.0.1`. Unset means `tcp` (see {ref}`scrap-listen`). |
| `SCRAP_PORT` | `8790` | Port on `127.0.0.1` that scrap listens on with `SCRAP_LISTEN=tcp`. |
| `SCRAP_DATA` | `~/.local/share/scrap/data` | Database and files; mounted at `/data`. |
| `SCRAP_BACKUPS` | `~/.local/share/scrap/backups` | Where the backup job writes. |
| `SCRAP_BACKUP_KEEP` | `14` | Number of backup runs to keep (at least 1). |
| `SCRAP_MEMORY_MAX` | `1g` | Memory ceiling for the container. |

After changing a setting: `systemctl --user restart scrap`.

(scrap-listen)=
### Socket or port

With `SCRAP_LISTEN=socket` the container publishes no port. scrap listens on
`scrap.sock` in the unit's runtime folder, `$XDG_RUNTIME_DIR/scrap` (normally
`/run/user/<uid>/scrap`), which systemd creates with mode 700 when scrap starts and removes when
it stops; the socket itself is mode 600. Only the scrap user and root can open it, so Tailscale
Serve (which runs as root) can and other local users cannot. To call scrap from the server, as
the scrap user:

```
curl --unix-socket "$XDG_RUNTIME_DIR/scrap/scrap.sock" http://localhost/healthz
```

`SCRAP_LISTEN=tcp` publishes `SCRAP_PORT` on `127.0.0.1` instead, reachable by every local
process. Use it only on a server with no other users or workloads.

**Existing installs.** An env file written before the socket existed has no `SCRAP_LISTEN`,
which means `tcp`: re-running `install.sh` keeps scrap on its port, so nothing that reaches it
there today is cut off, and prints a note. To move to the socket:

1. Add `SCRAP_LISTEN=socket` to `~/.config/scrap/env` and `systemctl --user restart scrap`.
2. As an admin, point the existing Serve entry at the socket (the same `--https` port, so the
   address, `SCRAP_PUBLIC_URL` and installed PWAs stay the same):
   `sudo tailscale serve --bg --https=8446 unix:/run/user/<uid>/scrap/scrap.sock`
3. `./deploy/smoke.sh https://<host>.<tailnet>.ts.net:8446`

Between steps 1 and 2 scrap is unreachable from the tailnet; the PWA keeps captures in its
offline queue and sends them once it is back.

(scrap-ingest-settings)=
### Ingest settings

scrap's own settings go in `~/.config/scrap/ingest.env`, which podman passes into the container
(`--env-file`). `install.sh` creates it with mode 600 and every line commented out, so ingest is
off until you edit it. It holds the API key: keep it mode 600, never copy it into the repo, and do
not paste it anywhere it would be logged. The same goes for the output of `podman inspect scrap`,
which shows the key and the notify URL in plain text. Plain `KEY=value` lines, with no quotes
(podman takes the rest of the line literally). For example:

```
SCRAP_INGEST=on
ANTHROPIC_API_KEY=<your key>
SCRAP_BUDGET_DAY_USD=3
SCRAP_NOTIFY_URL=https://ntfy.sh/<your private topic>
```

Also set `TZ` to your own time zone, for example `TZ=Europe/London`. The server decides what
"today" means for `due:today` searches (the web UI and the MCP tools alike) from its own clock,
which is UTC unless `TZ` says otherwise, while the PWA uses the phone's date, so the two disagree
for the hours around midnight. The image carries the time zone database, so `TZ` takes effect.

Set `SCRAP_NOTIFY_URL`: without it, a pause (daily budget reached, credit or login problem, an
outage) is only visible when you next open scrap. An ntfy topic URL is itself a secret. Every
setting, with its default, is in the [API reference](../reference/api.md). After editing:
`systemctl --user restart scrap`.

With ingest on, Claude also tags and summarises notes and links (`SCRAP_ENRICH`, on by default).
Related pages come from a nightly pass, which `install.sh` does not install: to have it, copy
`deploy/scrap-enrich-related.service` and `deploy/scrap-enrich-related.timer` to
`~/.config/systemd/user/`, then `systemctl --user daemon-reload && systemctl --user enable --now
scrap-enrich-related.timer`. It keeps to the same daily budget and stops at a queue pause.
`podman exec scrap scrap enrich --related --dry-run` says how many pages it would do.

## First run

```
systemctl --user status scrap
./deploy/smoke.sh
```

`smoke.sh` calls `/healthz` on the socket (or the local port) and should print
`{"status":"ok",...}`. Logs:
`journalctl --user -u scrap`.

## Publish on your tailnet

As an admin on the server, publish the socket over HTTPS on a port that is not already in use
(`install.sh` prints the target). Check first, and leave existing entries alone:

```
sudo tailscale serve status
sudo tailscale serve --bg --https=8446 unix:/run/user/$(id -u scrap)/scrap/scrap.sock
```

With `SCRAP_LISTEN=tcp` the target is `http://127.0.0.1:8790` instead.

scrap is then at `https://<host>.<tailnet>.ts.net:8446` from devices on your tailnet. `--bg`
makes the setting persist across reboots. Check it from any tailnet device:

```
./deploy/smoke.sh https://<host>.<tailnet>.ts.net:8446
```

Use `--https=443` instead if the machine serves nothing else. Never use `tailscale funnel` for
scrap: that publishes it to the internet.

This is the only supported way in, from phones and other computers alike. If the server is down
or unreachable for a while (a restart, a workstation asleep or off the network), the PWA keeps
new captures in its offline queue and sends them when it can reach scrap again
([](../explanations/decisions/0005-capture-never-waits.md)); reading needs scrap to be up.

(scrap-ssh-tunnel)=
### Fallback: an SSH tunnel

From a machine that cannot join the tailnet, an SSH tunnel can carry a local port to the socket.
This is a fallback, not a supported path: sshd on the server must allow forwarding to a Unix
socket (`AllowStreamLocalForwarding`, on by default, and no `DisableForwarding` or `restrict` for
the key; `AllowTcpForwarding` does not matter here), the tunnel sends no identity header (changes are recorded under the fallback author), and anything on the client
machine can use the forwarded port while the tunnel is open.

```
ssh -N -L 8790:/run/user/<uid>/scrap/scrap.sock scrap@<host>
```

Then open `http://127.0.0.1:8790` (a loopback address is a secure context, so the PWA works),
or add the MCP server with
`claude mcp add --transport http scrap http://127.0.0.1:8790/mcp` (`/mcp` accepts loopback
hosts).

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
  front, and keep scrap on its socket or bound to `127.0.0.1`. Without Tailscale Serve, every change is recorded
  under the fixed fallback author. Do not let a proxy pass through `Tailscale-User-*` headers
  sent by clients.

Either way the network only guards the way in from outside. On the server itself, the socket's
permissions keep other users out, but root, anyone with `sudo`, and anything running as the
scrap user get full access, and so does whoever controls Tailscale on the server or administers
the tailnet (see the warning at the top). With `SCRAP_LISTEN=tcp`, anything that can open a
connection to `127.0.0.1` gets full access too.

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

If a drop-in under `~/.config/systemd/user/scrap.service.d/` replaces `ExecStart`, its command
runs instead of the unit's, now and after every update (`install.sh` prints a note when it finds
one). A drop-in that only added `--env-file ~/.config/scrap/ingest.env` is no longer needed:
delete it, then `systemctl --user daemon-reload` and `systemctl --user restart scrap`.

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

(scrap-gc)=
## Deleting unused files (scrap gc)

Deleting a page only moves it to the trash, and deleting an image's line from a page's text keeps
its file, so files nothing uses build up. `scrap gc` finds them: a file is in use while a page's
text refers to it (pages in the trash too, so they can be brought back), or a capture, a Claude
result or ingest job, or a model run (the photo, or the JPEG it sent) does. Files younger than
`--grace-hours` (default 24) are kept whatever refers to them, since an upload records its files
only after writing them. **It is a dry run unless you give `--delete`**: it prints how many files
it would delete and their size (never any page text). It refuses to run, deleting nothing, if it
cannot read every reference, and it is safe while scrap serves. Each run first puts back any
file an earlier run left renamed aside (`files/ab/.gc-<sha>`) because it stopped mid-delete. Only
each page's current text counts: old revisions of a page do not keep a file.

`scrap-gc.timer` runs `scrap-gc.service` nightly (about 04:30, after the backup) with
`--delete`, but only if a backup run in `SCRAP_BACKUPS` is less than 26 hours old; otherwise it
only counts and the service fails, so a missing backup shows. Every file a backup's database names
is in that backup, so gc never deletes the only copy of a file a backup can restore. The backup
and gc scripts take the same lock (`SCRAP_BACKUPS/.lock`), so they never overlap, and
`scrap-gc.service` is ordered `After=scrap-backup.service`. The gc timer is not `Persistent`: a
night missed while the machine was off is skipped rather than run at boot, where it could take
the lock before the catch-up backup and fail for want of a recent backup. Both containers run with
`--network=none`. A `scrap gc` you run by hand takes no lock, so it can race the nightly run; the
worst case is a file left on disk after its record is deleted, which the next run removes. To see
what it would delete now, without deleting:

```
set -a; . ~/.config/scrap/env; set +a
podman run --rm --userns=keep-id:uid=10001,gid=10001 \
    --network=none -v "$SCRAP_DATA:/data" -e SCRAP_DATA_DIR=/data "$SCRAP_IMAGE" gc
journalctl --user -u scrap-gc   # what the nightly runs deleted
```

## Uninstall

As the `scrap` user:

```
systemctl --user disable --now scrap.service scrap-backup.timer scrap-gc.timer
rm ~/.config/systemd/user/scrap.service ~/.config/systemd/user/scrap-backup.* \
    ~/.config/systemd/user/scrap-gc.*
rm -r ~/.local/lib/scrap
systemctl --user daemon-reload
podman rmi localhost/scrap:dev
```

As an admin, remove the Serve entry (`sudo tailscale serve --https=8446 off`). The data,
backups and the settings in `~/.config/scrap/` stay until you delete them;
`sudo userdel --remove scrap` removes the user and everything it owns.

(scrap-docker)=
## Using Docker instead

With Docker, edit the installed copies. In `scrap.service`: replace `/usr/bin/podman` with
`/usr/bin/docker`, change `Type=notify` to `Type=simple`, remove `NotifyAccess` and `Delegate`,
and drop `-i` from the `rm` commands. In `~/.local/lib/scrap/scrap-run`: replace `podman` with
`docker` and drop `--replace`, `-d`, `--cgroups=split` and `--sdnotify=conmon`. In
`scrap-backup` and `scrap-gc`: replace `podman` with `docker` and drop `--replace`. In all three
scripts, replace `--userns=keep-id:uid=10001,gid=10001` with `--user <uid>:<gid>` of the user
that owns `SCRAP_DATA`, `SCRAP_BACKUPS` and the socket's folder (`id -u`, `id -g`). Re-running `install.sh`
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

**The service fails with "address already in use"** (`SCRAP_LISTEN=tcp`). Another process has
the port: `ss -ltnp | grep :8790`. Pick a free port in `SCRAP_PORT`, restart, and point
`tailscale serve` at the new port.

**The service fails with "is in use", "may be in use" or "is not a socket".** Something else is
at `$XDG_RUNTIME_DIR/scrap/scrap.sock`: another scrap, a busy listener, or a file scrap will not
remove. Stop or move it and restart. A socket nothing listens on (left by a scrap that stopped) is
replaced on its own.

**Tailscale Serve answers 502 with `SCRAP_LISTEN=socket`.** scrap is not running (the socket's
folder is removed when it stops), or the Serve target names another path or user id: compare
`sudo tailscale serve status` with what `install.sh` printed.

**Permission denied writing `/data`.** The data directory must be owned by the `scrap` user and
the container started with `--userns=keep-id:uid=10001,gid=10001` (the units do this). On
SELinux systems (Fedora, RHEL) also add `:Z` to the `--volume` options.

**The access log shows every client as the server's own address** (`SCRAP_LISTEN=tcp`).
Rootless podman's network (pasta) forwards connections so that local clients, including Tailscale
Serve, appear to come from one of the host's own addresses, which may be its public one. These
lines are not outside traffic. On the socket the log shows no client address at all.

**Anything else.** `journalctl --user -u scrap -e` and `podman logs scrap`.
