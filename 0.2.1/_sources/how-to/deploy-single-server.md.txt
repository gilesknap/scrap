# Deploy on a single server

Run scrap on one Linux machine (a VPS, a home server) as the same container image that a
cluster would run, under rootless podman, as a systemd user service. scrap listens only on a Unix
socket that only its own user (and root) can open;
[Tailscale Serve](https://tailscale.com/kb/1312/serve) publishes it over HTTPS to your tailnet and
nowhere else. Why: [](../explanations/decisions/0018-unix-socket-for-single-server-installs.md).

Podman is the tested path. Docker is possible, but `install.sh` needs podman, so you wire the
units up by hand: see {ref}`scrap-docker`. To run scrap on a Kubernetes cluster instead, see
[](deploy-kubernetes.md). To demo it on a DLS workstation without `sudo`, see
[](../tutorials/dls-workstation.md).

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
- Rootless [podman](https://podman.io), with `uidmap` (`newuidmap`/`newgidmap`) installed. The
  units use `--userns=keep-id:uid=,gid=`, `--sdnotify=conmon` and `--cgroups=split`, and have
  been run with podman 5.x; older versions are untested.
- cgroups v2 (the default on current distributions) for the memory and process limits. On a
  cgroups v1 host (RHEL 8, for example) scrap still runs, without `--cgroups=split`, but podman
  then ignores `--memory` and `--pids-limit`: the container has no memory cap.
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

As the `scrap` user (podman images belong to the user who pulled or built them), pull the newest
release from [scrap's releases](https://github.com/gilesknap/scrap/releases); this page uses
0.1.0:

```
podman pull ghcr.io/gilesknap/scrap:0.1.0
podman run --rm ghcr.io/gilesknap/scrap:0.1.0 --version
```

The image is public (no login needed) and built for amd64 and arm64. Pin an exact version rather
than `latest`, which moves with every release, pre-releases included.

The install script and its units are not in the image: they come from the repo's `deploy/`
folder. So, as `scrap`, clone the repo too, into the user's home directory so that the clone is
`~/scrap`: the `./deploy/...` commands below run from it, and the update steps refer to it by
that path.

```
cd ~
git clone https://github.com/gilesknap/scrap.git
cd scrap
```

````{note}
**To run unreleased changes instead**, build the image from the clone, and use
`localhost/scrap:dev` wherever this page names the release image:

```
podman build -t localhost/scrap:dev .
```

The build pulls a large build-stage image. To avoid keeping it under the `scrap` user, build as
another user and copy only the image across (with linger on, so the user's runtime directory
exists); the `scrap` user still needs its own clone for the install and update steps:

```
podman save localhost/scrap:dev |
    sudo -u scrap -H env XDG_RUNTIME_DIR=/run/user/$(id -u scrap) podman load
```
````

The image runs scrap as an unprivileged user (uid 10001) and keeps all its data under `/data`.

(scrap-install-script)=
## Install

From the clone:

```
./deploy/install.sh
```

On its first run the script writes `~/.config/scrap/env` naming a local build,
`SCRAP_IMAGE=localhost/scrap:dev`, and stops because that image is not there. Point it at the
release you pulled and run the script again:

```
sed -i 's|^SCRAP_IMAGE=.*|SCRAP_IMAGE=ghcr.io/gilesknap/scrap:0.1.0|' ~/.config/scrap/env
./deploy/install.sh
```

(If you built `localhost/scrap:dev` instead, the first run starts it.) The script:

- writes the settings files `~/.config/scrap/env` and `~/.config/scrap/ingest.env` if they do not
  exist yet (it never overwrites them);
- copies `scrap.service`, `scrap-backup.service`, `scrap-backup.timer`, `scrap-gc.service`,
  `scrap-gc.timer`, `scrap-enrich-related.service` and `scrap-enrich-related.timer` to
  `~/.config/systemd/user/`, and the scripts `scrap-run`, `scrap-backup` and `scrap-gc` to
  `~/.local/lib/scrap/`;
- enables linger if it can (otherwise it prints the `sudo loginctl enable-linger` command);
- enables and starts `scrap.service` if the image named in the settings is present, and the daily
  backup timer only if that image has the `scrap backup` command, the nightly gc timer only if
  it has `scrap gc`, and the nightly related-pages timer only if it has `scrap enrich --related`
  (images built before them do not; re-run the script after updating the image);
- restarts a running `scrap.service` if the image it runs, the unit or the `scrap-run` launcher
  has changed (see {ref}`scrap-update`);
- prints where scrap listens, and a note if that is a TCP port (see {ref}`scrap-listen`).

If the image named in the settings is not present, the script stops after writing the files and
the units, says so, and **exits 0** without enabling the service or any timer. Build or pull the
image, then re-run it.

It is safe to re-run after pulling a newer version of the repo.

### Settings

The service's settings live in `~/.config/scrap/env`. It is read by systemd, not a shell, so use
plain `KEY=value` lines with absolute paths.

| Variable | Default | Meaning |
| --- | --- | --- |
| `SCRAP_IMAGE` | `localhost/scrap:dev` | Image to run: a release such as `ghcr.io/gilesknap/scrap:0.1.0`, or a local build. |
| `SCRAP_LISTEN` | `socket` | `socket`: only the Unix socket `$XDG_RUNTIME_DIR/scrap/scrap.sock`. `tcp`: `SCRAP_PORT` on `127.0.0.1`. Unset means `tcp` (see {ref}`scrap-listen`). |
| `SCRAP_PORT` | `8790` | Port on `127.0.0.1` that scrap listens on with `SCRAP_LISTEN=tcp`. |
| `SCRAP_DATA` | `~/.local/share/scrap/data` | Database and files; mounted at `/data`. |
| `SCRAP_BACKUPS` | `~/.local/share/scrap/backups` | Where the backup job writes. |
| `SCRAP_BACKUP_KEEP` | `14` | Number of backup runs to keep (at least 1). Each is a full copy: see {ref}`scrap-backup-restore`. |
| `SCRAP_MEMORY_MAX` | `1g` | Memory ceiling for the container. |

After changing a setting: `systemctl --user restart scrap`.

The two directory defaults are `${XDG_DATA_HOME:-~/.local/share}/scrap/data` and `.../backups`,
which `install.sh` writes into the file as absolute paths and creates. If you point
`SCRAP_BACKUPS` somewhere else, create the directory first, owned by the `scrap` user: nothing
else creates it, and the backup and gc jobs fail without it. `scrap.service` creates a missing
`SCRAP_DATA` itself, and it too must belong to the `scrap` user.

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
3. As the `scrap` user again (`smoke.sh` reads the caller's `~/.config/scrap/env`):
   `./deploy/smoke.sh https://<host>.<tailnet>.ts.net:8446`

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
TZ=Europe/London
SCRAP_PUBLIC_URL=https://<host>.<tailnet>.ts.net:8446
```

The generated file also has a commented `SCRAP_VISION_MODEL` line; leave it alone to use the
default. It lists `SCRAP_PUBLIC_URL` and `TZ` commented out: uncomment and set them. With
ingest on, the container needs outbound network access: HTTPS to reach Claude, and HTTP or HTTPS
to fetch saved links.

Set `SCRAP_PUBLIC_URL` to the address you publish scrap at (see
{ref}`scrap-publish`), with the scheme and, unless it is 443, the port; several addresses can be comma separated.
`/mcp` answers only requests whose `Host` is loopback or one of these, so without it Claude Code
gets `421 Invalid Host header` through Tailscale Serve, and the MCP tools return bare paths
(`/p/<slug>`) instead of page URLs. See [](connect-claude-code.md).

Set `TZ` to your own time zone, for example `TZ=Europe/London`. The server decides what
"today" means for `due:today` searches (the web UI and the MCP tools alike) from its own clock,
which is UTC unless `TZ` says otherwise, while the PWA uses the phone's date, so the two disagree
for the hours around midnight. The image carries the time zone database, so `TZ` takes effect.

Set `SCRAP_NOTIFY_URL`: without it, a pause (daily budget reached, credit or login problem, an
outage) is only visible when you next open scrap. An ntfy topic URL is itself a secret. Every
setting, with its default, is in the [API reference](../reference/api.md); besides the ones
above, `SCRAP_MAX_UPLOAD_MB` (default 50) is the one to raise if you upload large photos. After
editing:
`systemctl --user restart scrap`.

With ingest on, Claude also tags and summarises notes and links (`SCRAP_ENRICH`, on by default).
Related pages come from a nightly pass, `scrap-enrich-related.timer` (about 03:41, run in the
scrap container), which `install.sh` enables. It keeps to the same daily budget and stops (and
the service fails) at a queue pause; while ingest is off or no key (or seat token) is set it says
so and succeeds. `podman exec scrap scrap enrich --related --dry-run` says how many pages it
would do.

#### On a Claude seat, with no API key

On a Team or Enterprise seat, ingest can run through Claude Code instead
([ADR 0021](../explanations/decisions/0021-ingest-on-a-claude-seat-through-claude-p.md)). First
check with your organisation's Claude admin that unattended use of your seat is allowed. Calls
count against your seat's usage limits, shared with your own use of Claude; when a limit is hit,
ingest pauses until it resets.

1. On your own machine, run `claude setup-token` and copy the token it prints. It is a
   long-lived credential for your **whole seat**, with no spend cap: anyone holding it can use
   your seat until it expires or you revoke it.
2. Build the image with the CLI added on top of the scrap image, from the clone (it uses only
   `Dockerfile.claude`, so an empty folder holding a copy of that file from the release works
   too):

   ```
   podman build -f Dockerfile.claude --build-arg BASE=ghcr.io/gilesknap/scrap:0.1.0 \
       -t localhost/scrap-claude:0.1.0 .
   ```

   and set `SCRAP_IMAGE=localhost/scrap-claude:0.1.0` in `~/.config/scrap/env`. It is about
   240 MB larger. Build it again on each new release (or rebuild of the scrap image), with that
   image as `BASE`.
3. In `ingest.env`, instead of `ANTHROPIC_API_KEY`:

   ```
   SCRAP_INGEST=on
   SCRAP_LLM_BACKEND=cli
   CLAUDE_CODE_OAUTH_TOKEN=<your token>
   ```

   Take the same care as with an API key, and more: mode 600, never in the repo or a log, and
   `podman inspect scrap` shows it.

   The CLI takes about 250 MB of memory while it runs, so raise `SCRAP_MEMORY_MAX` in
   `~/.config/scrap/env` too, e.g. to `1.5g`.
4. Re-run `./deploy/install.sh`, which restarts scrap on the new image. Without the token or the
   binary, ingest pauses with a login problem and the log says which is missing.

`SCRAP_BUDGET_DAY_USD` still applies, to what the calls would cost at API prices (as Claude Code
reports it), not to anything you are charged. Tagging and summarising notes and links, *Ask
Claude* and the nightly related pages run on the seat too, each a call against its limits; set
`SCRAP_ENRICH=off` to keep the seat to photos.

## First run

```
systemctl --user status scrap
./deploy/smoke.sh
systemctl --user list-timers
```

`smoke.sh` calls `/healthz` on the socket (or the local port) and should print
`{"status":"ok",...}`. Run it as the `scrap` user, in that user's login session: it reads the
caller's `~/.config/scrap/env`, so run by anyone else it falls back to TCP port 8790 and fails on
a socket install. Logs:
`journalctl --user -u scrap`. `list-timers` should show `scrap-backup.timer`,
`scrap-gc.timer` and `scrap-enrich-related.timer`; one that is missing was skipped because the
image lacks its command (see {ref}`scrap-install-script`).

(scrap-publish)=
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

Now put this address in `SCRAP_PUBLIC_URL` in `~/.config/scrap/ingest.env` (see
{ref}`scrap-ingest-settings`) and `systemctl --user restart scrap`, as the `scrap` user. It is
needed for `/mcp` to answer through Serve and for the MCP tools to return page links; the
address, port included, must match what clients use (with `--https=443`, no port).

This is the only supported way in, from phones and other computers alike. If the server is down
or unreachable for a while (a restart, a workstation asleep or off the network), the PWA keeps
new captures in its offline queue and sends them when it can reach scrap again
([](../explanations/decisions/0005-capture-never-waits.md)); reading needs scrap to be up.

(scrap-ssh-tunnel)=
### Fallback: an SSH tunnel

From a machine that cannot join the tailnet, an SSH tunnel can carry a local port to the socket.
This is a fallback, not a supported path:

- sshd on the server must allow forwarding to a Unix socket: `AllowStreamLocalForwarding`
  (on by default), and no `DisableForwarding` or `restrict` for the key. `AllowTcpForwarding`
  does not matter here.
- The tunnel sends no identity header, so changes are recorded under the fallback author.
- Anything on the client machine can use the forwarded port while the tunnel is open.

```
ssh -N -L 8790:/run/user/<uid>/scrap/scrap.sock scrap@<host>
```

Use any free local port instead of `8790` (the client machine may have a scrap of its own on it).
Then open `http://127.0.0.1:8790` (a loopback address is a secure context,
so the PWA works), or add the MCP server with
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

## Next steps

- [](use-the-pwa.md): install the app on your phone and computers.
- [](connect-claude-code.md): let Claude Code sessions search and write scrap (needs
  `SCRAP_PUBLIC_URL`, above).
- [](import-a-vault.md): bring in an existing vault with `scrap import`; its
  {ref}`import-container` section has the `podman run` recipe for this install.

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

Take a restore point first ({ref}`scrap-upgrade-db`). Then update the clone, pull the new
release (see [scrap's releases](https://github.com/gilesknap/scrap/releases)), point
`SCRAP_IMAGE` at it, and re-run the install script:

```
git -C ~/scrap pull
podman pull ghcr.io/gilesknap/scrap:<version>
sed -i 's|^SCRAP_IMAGE=.*|SCRAP_IMAGE=ghcr.io/gilesknap/scrap:<version>|' ~/.config/scrap/env
~/scrap/deploy/install.sh
~/scrap/deploy/smoke.sh
```

For ingest on a Claude seat, build `localhost/scrap-claude:<version>` on the new release first
and name that in `SCRAP_IMAGE` instead. For a local build, run
`podman build -t localhost/scrap:dev ~/scrap` in place of the pull and leave `SCRAP_IMAGE` alone.

`install.sh` restarts `scrap.service` when the image named in `SCRAP_IMAGE` is not the one the
running container was started from, or when the unit or the `scrap-run` launcher changed;
otherwise (including when only a timer changed) it leaves it running. A restart drops requests in
flight (a capture being uploaded fails and the PWA retries it), and a photo Claude is describing
at that moment counts one failed try and is retried later.
After editing only a settings file, restart by hand: `systemctl --user restart scrap`.

If a drop-in under `~/.config/systemd/user/scrap.service.d/` replaces `ExecStart`, its command
runs instead of the unit's, now and after every update (`install.sh` prints a note when it finds
one). A drop-in that only added `--env-file ~/.config/scrap/ingest.env` is no longer needed:
delete it, then `systemctl --user daemon-reload` and `systemctl --user restart scrap`.

`SCRAP_IMAGE` pinned to a release version changes only when you edit it, so pulling the repo
alone never changes the running image.

(scrap-upgrade-db)=
### Database changes and rolling back

A new image may carry database migrations. scrap runs the missing ones when it starts, before it
serves anything: each in its own transaction, under an exclusive lock on `scrap.db.lock` in the
data folder so two processes never migrate at once. A migration that fails is rolled back and
scrap does not start (`journalctl --user -u scrap -e` says why).

Migrations are **forward only**, and an older scrap refuses a database that a newer one has
migrated: it stops with `<db> has schema N; this scrap knows M`. So starting the old image again
is not a rollback. Take a restore point before you update, and keep the old image to go back to:

```
systemctl --user start scrap-backup                       # returns when the backup is done
```

A release image stays under its version tag until you remove it, so the old one is still there
to go back to. A local build of `localhost/scrap:dev` is replaced by the next build: tag it first
with `podman tag localhost/scrap:dev localhost/scrap:previous`.

To roll back, stop scrap, run `scrap restore --force` from the **old** image on the backup you took
before the update (see {ref}`scrap-restore`; set `SCRAP_IMAGE` to the old image first), and start
scrap on that image. Pages added since the backup are lost from the database; their files stay.
Backups made after the update have the new schema, so the old image refuses to restore them.

(scrap-backup-restore)=
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

**Disk use.** Each run is a full, independent copy (the database and every file, not an
increment), so `SCRAP_BACKUPS` needs about `SCRAP_BACKUP_KEEP` times the size of `SCRAP_DATA`, plus
one more while a run is in progress. Check with `du -sh "$SCRAP_DATA" "$SCRAP_BACKUPS"` (after
loading the settings, as in {ref}`scrap-restore` below), and if the backups are too big,
lower `SCRAP_BACKUP_KEEP` or point `SCRAP_BACKUPS` at a bigger disk. `scrap gc` makes later runs
smaller; it never shrinks earlier ones.

**Pruning on demand.** The retention step runs only at the end of a successful backup, so a night
that fails or is missed prunes nothing (a long outage cannot remove your last good backups).
After lowering `SCRAP_BACKUP_KEEP`, or when disk is short, apply it now without a new backup:

```
set -a; . ~/.config/scrap/env; set +a
~/.local/lib/scrap/scrap-backup prune
```

`prune` only deletes the run directories beyond the newest `SCRAP_BACKUP_KEEP`. It starts no
container and takes no lock. With a `SCRAP_BACKUP_KEEP` that is not a whole number of at least 1
it prints `SCRAP_BACKUP_KEEP must be a whole number >= 1` and exits 1, deleting nothing.

The backup directory is a local copy only: copy it off the machine (restic, rsync, a cloud
bucket) to survive losing the server. A backup holds the database (`scrap.db`) and the files
(`files/`) and nothing else. It does not include `~/.config/scrap/env` or `ingest.env` (the API
key, notify URL, `SCRAP_PUBLIC_URL`, `TZ`) nor the Tailscale Serve entry, so keep a copy of
`ingest.env` somewhere safe too (it holds a secret). Deleted pages are in a backup too: deleting
only moves a page to the trash (see {ref}`scrap-gc`).

### Data folder layout

`SCRAP_DATA` (mounted at `/data`) holds:

- `scrap.db`: the database. It is in WAL mode, so while scrap runs, recent changes are in
  `scrap.db-wal` (with `scrap.db-shm` beside it), not yet in `scrap.db`.
- `scrap.db.lock`: the lock that serialises migrations (empty; leave it alone).
- `files/<ab>/<sha256>`: every stored file (photos, uploads), named by the SHA-256 of its bytes.
  `files/.up-*` are leftovers of uploads that were cut off by a crash.
- `cache/previews/`: the 480 and 2048 pixel JPEG previews, made again on demand.

```{warning}
Do not copy `scrap.db`, or the whole folder, while scrap is running: a plain file copy can miss
what is still in the `-wal` file, or catch the database and `files/` at different moments, and
gives a backup that looks fine and is not. Use `scrap backup` (the timer, or below), which takes a
consistent snapshot of the database with SQLite's online backup and then copies the files, and is
safe while scrap serves. If you must copy files, stop scrap first and copy the whole folder.
```

A backup leaves out `cache/previews/` (a cache: it needs no backup) and anything whose name starts
with a dot, so `.up-*` leftovers are not backed up. `scrap gc` deletes `.up-*` files once they are
older than its grace period; with scrap stopped you may delete them by hand.

### Extra backups by hand

To take another backup now, use `systemctl --user start scrap-backup`: it takes the lock in
`SCRAP_BACKUPS`, so it waits for a running gc, and gc waits for it. It counts as a run for
`SCRAP_BACKUP_KEEP`.

The lock is taken only by the `scrap-backup` and `scrap-gc` scripts. A `scrap backup` you run
yourself against `SCRAP_BACKUPS` takes none, so never run it while `scrap-gc` is active. Name
the directory anything but a run's `YYYYMMDDTHHMMSSZ` form, for example `pre-import`:

```
set -a; . ~/.config/scrap/env; set +a
podman run --rm --userns=keep-id:uid=10001,gid=10001 --network=none \
    -v "$SCRAP_DATA:/data:z" -v "$SCRAP_BACKUPS:/backups:z" -e SCRAP_DATA_DIR=/data \
    "$SCRAP_IMAGE" backup /backups/pre-import
```

A directory named like a run is pruned by the retention step, and counts as a recent backup for
gc, which looks only at the name and modification time of such a directory, never at what is
inside it, so even an unfinished backup would pass. (`ls` lists `pre-import` after the runs.)
You can instead keep hand backups outside `SCRAP_BACKUPS`, in a folder you mount on its own.

### Checking the timers

Nothing notifies you when a timer's service fails: `SCRAP_NOTIFY_URL` is for ingest pauses only.
All three services (`scrap-backup`, `scrap-gc`, `scrap-enrich-related`) are one-shot, so a failed
night shows only in systemd, and you find out by looking:

```
systemctl --user list-timers                        # next and last run of each timer
systemctl --user status scrap-backup scrap-gc       # the last result of each service
systemctl --user --failed                           # any unit whose last run failed
journalctl --user -u scrap-backup -u scrap-gc -u scrap-enrich-related
```

A failed service stays listed as failed until it next runs. The two scripts report on stderr,
which the journal keeps:

- `Backup failed; kept the existing backups untouched.` The backup run failed (the container
  could not run, or `scrap backup` failed: the lines above it in the journal say why). Its
  half-written directory was removed and nothing was pruned.
- `No backup in the last 26 hours: counting only, deleting nothing.` `scrap-gc` found no run
  directory in `SCRAP_BACKUPS` modified in the last 26 hours, so it did a dry run and then failed
  on purpose. Usually last night's backup failed or did not run. Fix the cause, then
  `systemctl --user start scrap-backup`, and when that succeeds `systemctl --user start scrap-gc`.

### Changing the schedule

`scrap-backup.timer` is set to 03:30 and `scrap-gc.timer` to 04:30 (each with up to 15 minutes of
random delay, `RandomizedDelaySec`, so the run is spread over that quarter hour). Do not edit
the copies in `~/.config/systemd/user/`: `install.sh` overwrites them on every run. Use a drop-in,
which survives it:

```
systemctl --user edit scrap-backup.timer
```

In the editor that opens, clear the default `OnCalendar` with an empty line before the new one:

```
[Timer]
OnCalendar=
OnCalendar=*-*-* 02:00:00
```

Check with `systemctl --user list-timers`. The gc timer works the same way.

The two are linked: `scrap-gc` deletes only if a run directory in `SCRAP_BACKUPS` is under 26
hours old, and otherwise counts, then fails (and it always keeps files younger than 24 hours,
`--grace-hours 24`). While a backup runs daily, the newest is never much more than a day old, so
gc may run at any time of day. A backup less often than daily makes gc a dry run that fails on
the days between, as does a run of failed backups. Either keep the backup at least daily, or turn
gc off with `systemctl --user disable --now scrap-gc.timer` (unused files then build up, and you
can run `scrap gc` by hand, as below).

(scrap-restore)=
### Restore

To restore, stop the service, run `scrap restore` from the image on the backup you want, and
start again. Each run is a directory named by its UTC start time, so the newest is the last in
`ls "$SCRAP_BACKUPS"` (after loading the settings, below). The commands load the settings file
first so they use your `SCRAP_DATA`, `SCRAP_BACKUPS` and `SCRAP_IMAGE`; the backups appear at
`/backups` inside the container:

```
systemctl --user stop scrap
set -a; . ~/.config/scrap/env; set +a
ls "$SCRAP_BACKUPS"
podman run --rm --userns=keep-id:uid=10001,gid=10001 \
    -v "$SCRAP_DATA:/data:z" -v "$SCRAP_BACKUPS:/backups:z" -e SCRAP_DATA_DIR=/data \
    "$SCRAP_IMAGE" restore /backups/<timestamp> --force
systemctl --user start scrap
```

`restore` refuses a data directory that already has a database or files ("is not empty; stop
scrap and use `--force`"). Drop `--force` only for a data directory scrap has never run in. With
`--force` the whole database is replaced by the backup's, so pages added since the backup are
lost; files are only ever added, never removed. It checks the backup's integrity first, refuses
one made by a newer scrap, and leaves the data as it was if the backup is refused.
`scrap restore --help` lists the arguments.

The same pattern runs any other `scrap` command (for example `scrap export`) against the data.

**Rebuilding on a new server.** Create the `scrap` user and get the image as above, copy your
backups and `ingest.env` over, and run `./deploy/install.sh`. That starts scrap, which creates an
empty database, so stop it and restore with `--force` as shown (nothing is lost: the database
is new). Start it, and publish it with `tailscale serve` again. Make sure the new Serve address
is what `SCRAP_PUBLIC_URL` says.

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

**Deleting is not erasing.** A trashed page keeps its text, its revisions, its captures, what
Claude made of its photos and its files, and gc keeps every file it uses. So deleting a page frees
no disk space and removes none of its content from the data folder or from your backups. There is
no purge or empty-trash command; a page comes back with `POST /api/pages/{id}/undelete` (see
[](../reference/api.md)).

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
    --network=none -v "$SCRAP_DATA:/data:z" -e SCRAP_DATA_DIR=/data "$SCRAP_IMAGE" gc
journalctl --user -u scrap-gc   # what the nightly runs deleted
```

To run the nightly job now, with its recent-backup check and lock, use
`systemctl --user start scrap-gc`. To delete by hand, add `--delete` after `gc` in the command
above; that skips the recent-backup check, so make sure you have a recent backup first.

### Reading the report

A run prints one line, for example `scrap gc: would delete (dry run: --delete deletes) 3 unused
files and 1 leftover uploads, 12.4 MB; 3 unused file records; kept 2 unused files younger than
the grace period`. With `--delete` it says `deleted` instead. The parts:

| Part | Meaning |
| --- | --- |
| `N unused files` | Files nothing uses, older than the grace period. The `MB` is the size of these and of the leftover uploads together. A deleted file takes its cached 480 and 2048 previews with it. |
| `M leftover uploads` | `files/.up-*` temporaries from uploads cut off by a crash, also deleted once older than the grace period. |
| `R unused file records` | Database rows for files nothing uses. The row is deleted with its file, or on its own if the file is already gone, so this can be more than the files. |
| `kept Y unused files younger than the grace period` | Unused, but too new to delete: a later run takes them. |
| `K used again meanwhile` | Only shown when above zero. Unused when gc looked, but referenced, or uploaded again, before it deleted them (it checks again inside the delete), so they were kept. |
| `put back Z files an earlier run left aside` | Only shown when above zero. A run that stopped mid-delete left `.gc-<sha>` files; this run restored them before it began. |

When gc cannot run it prints `scrap gc: <reason>` to stderr and exits non-zero, deleting nothing.
A normal run, a dry run included, exits 0; only the nightly `scrap-gc` script fails on purpose when
it has no recent backup.

| Message | Cause and fix |
| --- | --- |
| `no database at <path>` | The data folder is wrong or empty. Check `SCRAP_DATA`, the `/data` mount and `SCRAP_DATA_DIR` (or `--data-dir`) in the command. |
| `no files folder at <path>` | The folder has a database but no `files/`. The wrong folder again, or the files were not restored with the database. |
| `the grace period must not be negative` | `--grace-hours` was below 0. |
| `cannot read what is in use, so nothing was deleted: ...` | The database or files could not be read after the reason given: a damaged or unreadable database, or a permission problem. If the reason is `<db> has schema N; this scrap knows M`, the database is from a newer scrap: run gc with the newer image (see {ref}`scrap-upgrade-db`). |
| `cannot delete: ...` | The database refused the delete (read-only, disk full). Nothing in the database changed; fix the cause and run again, which removes any file left over. |

## Uninstall

As the `scrap` user:

```
systemctl --user disable --now scrap.service scrap-backup.timer scrap-gc.timer \
    scrap-enrich-related.timer
rm ~/.config/systemd/user/scrap.service ~/.config/systemd/user/scrap-backup.* \
    ~/.config/systemd/user/scrap-gc.* ~/.config/systemd/user/scrap-enrich-related.*
rm -r ~/.local/lib/scrap
systemctl --user daemon-reload
set -a; . ~/.config/scrap/env; set +a
podman rmi "$SCRAP_IMAGE"
```

As an admin, remove the Serve entry (`sudo tailscale serve --https=8446 off`). The data,
backups and the settings in `~/.config/scrap/` stay until you delete them;
`sudo userdel --remove scrap` removes the user and everything it owns.

(scrap-docker)=
## Using Docker instead

`install.sh` exits at "podman is not installed" without podman on `PATH`, and it calls
`podman` for its image and timer checks, so on a Docker-only host you do its work yourself:
create `~/.config/scrap/env` and `ingest.env` (the templates are in the script), copy the
units from `deploy/` to `~/.config/systemd/user/` and the scripts to `~/.local/lib/scrap/`,
then edit the copies as below, `systemctl --user daemon-reload`, and enable `scrap.service` and
the timers you want (`scrap-backup.timer`, `scrap-gc.timer`, `scrap-enrich-related.timer`)
with `systemctl --user enable --now`.

In `scrap.service`: replace `/usr/bin/podman` with
`/usr/bin/docker`, change `Type=notify` to `Type=simple`, remove `NotifyAccess` and `Delegate`,
and drop `-i` from the `rm` commands. In `~/.local/lib/scrap/scrap-run`: replace `podman` with
`docker` and drop `--replace`, `-d`, `--cgroups=split` and `--sdnotify=conmon`. In
`scrap-backup` and `scrap-gc`: replace `podman` with `docker` and drop `--replace`. In all three
scripts, replace `--userns=keep-id:uid=10001,gid=10001` with `--user <uid>:<gid>` of the user
that owns `SCRAP_DATA`, `SCRAP_BACKUPS` and the socket's folder (`id -u`, `id -g`). In
`scrap-enrich-related.service`, replace `/usr/bin/podman` with `/usr/bin/docker` in `ExecStart`.
Copying the files again (an update) overwrites these edits. The commands elsewhere in this guide
that start `podman run` need `docker run` and `--user` likewise. Membership of the `docker` group
is equivalent to root, so on a shared machine prefer rootless podman.

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

**The service fails with "is in use", "may be in use", "exists and is not a socket" or "is being
set up by another process".** Something else is at `$XDG_RUNTIME_DIR/scrap/scrap.sock`: another
scrap, a busy listener, or a file scrap will not remove. Stop or move it and restart. A socket
nothing listens on (left by a scrap that stopped) is replaced on its own.

**The service fails with "is open to other users", "belongs to another user" or "is longer than
107 bytes".** These come from the socket setup (`scrap serve --uds`). Its folder must belong to
the scrap user and be mode 700, which the unit's runtime folder is; the path (including
`$XDG_RUNTIME_DIR`) must be at most 107 bytes.

**The service stops restarting: "start request repeated too quickly".** After 5 failed starts
in 5 minutes (a missing image, a missing `ingest.env`, a bad setting) systemd stops trying. Fix
the cause (`journalctl --user -u scrap -e`), then
`systemctl --user reset-failed scrap && systemctl --user start scrap`.

**scrap will not start and `ingest.env` is missing or a dangling symlink.** The launcher passes
`~/.config/scrap/ingest.env` to podman unconditionally. `install.sh` only warns about a
dangling symlink; restore the file (an empty one will do) and start scrap.

**`smoke.sh` fails with a 503, `"ingest worker stopped"`.** `/healthz` reports 503 when the
ingest worker has stopped, and `smoke.sh` fails on any error status. Look in
`journalctl --user -u scrap` for why, then `systemctl --user restart scrap`.

**Tailscale Serve answers 502 with `SCRAP_LISTEN=socket`.** scrap is not running (the socket's
folder is removed when it stops), or the Serve target names another path or user id: compare
`sudo tailscale serve status` with what `install.sh` printed.

**Permission denied writing `/data`.** The data directory must be owned by the `scrap` user and
the container started with `--userns=keep-id:uid=10001,gid=10001` (the units do this). On
SELinux systems (Fedora, RHEL) the folder must also be relabelled, which the `:z` on every
volume does. Keep it lowercase if you write your own `podman run`: `:Z` makes the label private
to one container, locking the backup and gc containers out of `SCRAP_DATA`.

**The access log shows every client as the server's own address** (`SCRAP_LISTEN=tcp`).
Rootless podman's network (pasta, the default from podman 5.0) forwards connections so that
local clients, including Tailscale Serve, appear to come from one of the host's own addresses, which may be its public one. These
lines are not outside traffic. On the socket the log shows no client address at all.

**The service will not start and the log says `<db> has schema N; this scrap knows M`.** The image
is older than the database: a newer scrap has already migrated it, and migrations only go
forward. Run the newer image again, or roll back with the old image and `scrap restore --force`
from a backup taken before the update (see {ref}`scrap-upgrade-db`).

**`scrap-gc` fails with "No backup in the last 26 hours".** There is no run directory in
`SCRAP_BACKUPS` modified in the last 26 hours, so gc only counted. Find out why the backup did not
run (`journalctl --user -u scrap-backup`), then `systemctl --user start scrap-backup` and, once
that succeeds, `systemctl --user start scrap-gc`. See {ref}`scrap-backup-restore`.

**`scrap gc` prints `scrap gc: ...` and exits non-zero.** See the table of messages under
{ref}`scrap-gc`.

**Anything else.** `journalctl --user -u scrap -e` and `podman logs scrap`.
