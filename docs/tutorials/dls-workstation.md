# Try scrap on a DLS workstation

In this tutorial you run scrap on your own Diamond workstation, with no `sudo`, and open it from
your phone. DLS workstations run RHEL 8 with SELinux enforcing and cgroups v1, are shared with
other users, mount your home directory over NFS, and already have rootless podman set up with its
storage on `/scratch`. Your phone cannot join the workstation network, so a userspace Tailscale,
run as you, carries scrap to it over HTTPS. At the end scrap runs as a systemd user service on
the workstation and its web app is on your phone.

This page follows one path for a trial. The general install, with a dedicated user and a system
Tailscale, is [](installation.md); every option, and the update, backup and troubleshooting
steps, are in [](../how-to/deploy-single-server.md).

```{warning}
**Not yet verified end to end, and one step is known not to work as written.** scrap itself has
been run this way on a DLS workstation (RHEL 8, cgroups v1, SELinux enforcing, podman 4.9.4).
The Tailscale steps without root have not been run together there, and publishing scrap with
`tailscale serve` to its Unix socket is refused by current Tailscale versions: see
{ref}`dls-publish`. Expect to adjust the Tailscale steps, and report what you find.
```

```{warning}
v0 of scrap has **no login**. Anyone who can reach it can read and change everything. Only
expose it through Tailscale Serve (tailnet only, never `tailscale funnel`).
```

**Check with DLS IT policy before you run Tailscale on a workstation.** It connects the
workstation to an outside network that IT does not manage.

## What runs as you

Without `sudo` there is no dedicated user, so scrap, its data and Tailscale all run as you. Other
users on the workstation cannot open scrap's socket. Anything running in your own account can:
it can read and change all of scrap's data and send its own `Tailscale-User-Login` header to be
recorded as any author. So can root and the workstation's admins. That is fine for a trial; for
lasting use, follow [](installation.md) on a machine where scrap has its own user. See
{ref}`scrap-access`.

Your home directory is on NFS, so everything this tutorial puts there follows you to every
machine that mounts it: the systemd user units, scrap's settings, and
`~/.config/scrap/ingest.env`, which holds your Claude seat token if you turn ingest on (keep it
mode 600). The data and Tailscale's state go on the workstation's own disk, under
`/scratch/<fedid>`, and each unit gets a guard so that it runs only on the workstation where
those folders exist.

## What you need

- A DLS workstation account with rootless podman working (`podman info` runs), `git` and `curl`.
- A directory of your own on the workstation's local disk, `/scratch/<fedid>`. scrap's SQLite
  database (in WAL mode) needs a local disk, not NFS.
- A phone with the [Tailscale app](https://tailscale.com/download), and another device on which
  to run Claude Code if you want to connect it (see {ref}`dls-own-address`).

You do not need Python or Node: the image carries everything scrap needs.

(dls-make-tailnet)=
## Make a tailnet

**Do not sign up with your `@diamond.ac.uk` address.** Tailscale ties a tailnet to a custom email
domain: the first person to sign up with a `diamond.ac.uk` address creates a tailnet that owns
that domain, and everyone who signs up with one later joins it, subject to its admins' approval
(see [domain ownership](https://tailscale.com/docs/concepts/domain-ownership) and
[user approval](https://tailscale.com/kb/1239/user-approval)). It would also be treated as
business use and start an Enterprise trial. Use a personal identity instead: a personal GitHub
account, whose tailnet others can join only by invitation
([GitHub](https://tailscale.com/kb/1284/sso-github)), or a personal Google, Apple or Microsoft
account.

1. Sign up for a free Personal [Tailscale](https://tailscale.com) account with that identity.
2. Install the Tailscale app on your phone and log in to the same account. A phone is on one
   tailnet at a time.
3. In the admin console, under **DNS**, turn on MagicDNS and
   [HTTPS certificates](https://tailscale.com/kb/1153/enabling-https).
4. In the admin console, under **Access controls**, replace the whole policy with:

   ```json
   {
     "grants": [
       {"src": ["autogroup:member"], "dst": ["autogroup:self"], "ip": ["tcp:443"]}
     ]
   }
   ```

Do step 4 **before** the workstation joins the tailnet. In userspace mode, Tailscale forwards an
inbound tailnet connection to any TCP port that Serve does not handle to the same port on the
workstation's `127.0.0.1`
([wgengine/netstack](https://github.com/tailscale/tailscale/tree/main/wgengine/netstack)). On a
shared workstation that loopback address carries every user's local services, so under the
default policy, which lets every device reach every port, your tailnet could reach all of them.
This policy lets your own devices reach each other on port 443 only, and nothing else. Replacing
the policy wipes whatever was there, which is fine only because the tailnet is new.

## Keep your services running after you log out

Let your systemd user services run when you are not logged in, and start at boot:

```
loginctl enable-linger
loginctl show-user $USER -p Linger
```

The second command should print `Linger=yes`. RHEL normally lets you do this for yourself. If it
is refused, ask IT to run `sudo loginctl enable-linger <fedid>` for you; until then scrap and
Tailscale stop when you log out, and start only when you next log in.

## Run Tailscale without root

Download the static binaries into `~/.local/bin`. Take the current version number from the
[static binaries page](https://pkgs.tailscale.com/stable/#static):

```
v=<version>
mkdir -p ~/.local/bin
curl -fsSL https://pkgs.tailscale.com/stable/tailscale_${v}_amd64.tgz |
    tar -xz -C ~/.local/bin --strip-components=1 \
        tailscale_${v}_amd64/tailscale tailscale_${v}_amd64/tailscaled
```

`--tun=userspace-networking` runs Tailscale with no network device, so it needs no root. Run it
as a systemd user service, with its state on `/scratch` (it identifies this machine, so it must
not follow you to others) and its control socket in your runtime folder.
`ConditionPathIsDirectory` keeps it from starting on any other machine that mounts your home:

```
mkdir -p ~/.config/systemd/user /scratch/$USER/tailscale
chmod 700 /scratch/$USER/tailscale
cat >~/.config/systemd/user/tailscaled.service <<'EOF'
[Unit]
Description=Tailscale in userspace networking mode, for this user
ConditionPathIsDirectory=/scratch/%u/tailscale

[Service]
ExecStart=%h/.local/bin/tailscaled --tun=userspace-networking --statedir=/scratch/%u/tailscale --socket=%t/tailscale/tailscaled.sock
RuntimeDirectory=tailscale
RuntimeDirectoryMode=0700
Type=notify
Restart=on-failure

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now tailscaled
```

Every `tailscale` command needs the same `--socket`, so define a shell alias for it (add the line
to `~/.bashrc` to keep it):

```
alias ts='~/.local/bin/tailscale --socket=$XDG_RUNTIME_DIR/tailscale/tailscaled.sock'
ts up
```

`ts up` prints a login URL: open it in any browser and log in to your new tailnet. Where UDP is
blocked, Tailscale falls back to its DERP relays over HTTPS on port 443: slower, but it works. (On
a machine that reaches the internet only through a proxy, you would add
`Environment=HTTPS_PROXY=http://<proxy>:<port>` under `[Service]`.)

To update Tailscale, download a newer version the same way and
`systemctl --user restart tailscaled`.

## Build the image

There is no published release image yet, so build it from a clone of the repo:

```
cd ~
git clone https://github.com/gilesknap/scrap.git
cd scrap
podman build -t localhost/scrap:dev .
podman run --rm localhost/scrap:dev --version
```

The first build downloads a large build-stage image, so it takes a while. Once releases exist you
can instead `podman pull ghcr.io/gilesknap/scrap:<version>` and put that name in `SCRAP_IMAGE`
(next step).

## Install scrap

Write the settings file **before** the first install, so that scrap's data goes on `/scratch`
from the start (`install.sh` never overwrites an existing file). systemd reads this file, not a
shell, so the paths must be absolute; the shell fills in `$USER` here:

```
mkdir -p ~/.config/scrap /scratch/$USER/scrap/data /scratch/$USER/scrap/backups
cat >~/.config/scrap/env <<EOF
SCRAP_IMAGE=localhost/scrap:dev
SCRAP_LISTEN=socket
SCRAP_DATA=/scratch/$USER/scrap/data
SCRAP_BACKUPS=/scratch/$USER/scrap/backups
SCRAP_BACKUP_KEEP=14
SCRAP_MEMORY_MAX=1g
EOF
```

On cgroups v1, as on DLS workstations, podman ignores `SCRAP_MEMORY_MAX`: the container has no
memory cap. If you have already run `install.sh`, changing `SCRAP_DATA` or `SCRAP_BACKUPS` later
only points scrap at a new, empty folder: stop scrap and move the old folder's contents yourself.
The settings are described in {ref}`scrap-install-script`.

Next, give each of scrap's units the same guard as Tailscale, so that none of them runs on
another machine that mounts your home:

```
for u in scrap.service scrap-backup.service scrap-backup.timer scrap-gc.service \
        scrap-gc.timer scrap-enrich-related.service scrap-enrich-related.timer; do
    mkdir -p ~/.config/systemd/user/$u.d
    printf '[Unit]\nConditionPathIsDirectory=/scratch/%s/scrap\n' "$USER" \
        >~/.config/systemd/user/$u.d/host.conf
done
```

The user journal is not available to users on DLS workstations, so `journalctl --user` shows
nothing. To keep scrap's start-up errors (from `scrap-run` and podman) in a file instead:

```
printf '[Service]\nStandardError=file:/scratch/%s/scrap/scrap.err\n' "$USER" \
    >~/.config/systemd/user/scrap.service.d/logs.conf
```

(RHEL 8's systemd 239 has `file:`, which rewrites the file from the start; it does not have
`append:`.) While scrap runs, `podman logs scrap` shows its own output.

Then, from the clone:

```
./deploy/install.sh
./deploy/smoke.sh
```

`install.sh` writes `~/.config/scrap/ingest.env`, installs the units and starts scrap on a Unix
socket, `$XDG_RUNTIME_DIR/scrap/scrap.sock`, that only you and root can open. It also starts the
daily backup, nightly gc and related-pages timers. `smoke.sh` should print
`{"status":"ok",...}`. If not, look in `/scratch/$USER/scrap/scrap.err`,
`systemctl --user status scrap` and `podman logs scrap`, and see {ref}`scrap-troubleshooting`.

The backups go to the same disk as the data, and `/scratch` is not backed up for you: copy
`/scratch/$USER/scrap/backups` somewhere else if what you put in scrap matters.

With SELinux enforcing, a container can write to a host folder only once it is relabelled. The
units, and the `podman run` commands in the how-to, mount scrap's folders with `:z`, which does
that.

(dls-publish)=
## Publish it on your tailnet

```{danger}
**This step does not work as written.** Since Tailscale 1.98.9
([TS-2026-005](https://tailscale.com/security-bulletins#ts-2026-005),
[tailscale#19977](https://github.com/tailscale/tailscale/issues/19977)), `tailscale serve` accepts
a `unix:` socket as its target only from a local admin: root, or an operator who can `sudo`. A
`tailscaled` that you run as yourself, without `sudo`, does not qualify, so the `serve` command
below is refused on a DLS workstation.

**TODO, not yet verified:** the intended replacement runs Tailscale as a rootless container (the
official `tailscale/tailscale` image) in a podman pod with scrap. Inside its user namespace the
Tailscale CLI runs as uid 0, and scrap listens on the pod's private `127.0.0.1`, which Serve
targets as `http://127.0.0.1:8000` (set with `TS_SERVE_CONFIG`). This also confines userspace
mode's forwarding to loopback (see {ref}`dls-make-tailnet`) to the pod, away from the
workstation's other services. This page will be rewritten once that has been tried.
```

The step as first planned pointed Tailscale Serve at the socket, on the standard HTTPS port:

```
ts serve --bg --https=443 unix:$XDG_RUNTIME_DIR/scrap/scrap.sock
ts serve status
```

`--bg` keeps the setting across restarts. `serve status` prints the address,
`https://<host>.<tailnet>.ts.net`.

In `~/.config/scrap/ingest.env`, uncomment the `SCRAP_PUBLIC_URL` and `TZ` lines and set them,
with no port since Serve uses 443:

```
SCRAP_PUBLIC_URL=https://<host>.<tailnet>.ts.net
TZ=Europe/London
```

then `systemctl --user restart scrap`. `SCRAP_PUBLIC_URL` lets Claude Code reach `/mcp` through
Serve; `TZ` makes `due:today` follow your day rather than UTC. See {ref}`scrap-ingest-settings`.

(dls-own-address)=
### Check it from your phone, not the workstation

In userspace mode the workstation cannot reach its own tailnet address, so
`./deploy/smoke.sh https://<host>.<tailnet>.ts.net` run there fails even when Serve works. Check
from your phone instead: with the Tailscale app connected, open
`https://<host>.<tailnet>.ts.net/healthz`, which should show `{"status":"ok",...}`. For the same
reason, run Claude Code on another device on your tailnet, not on the workstation.

## Open it on your phone

With the Tailscale app connected, open `https://<host>.<tailnet>.ts.net` on your phone and
install the app: see [](../how-to/use-the-pwa.md). Captures made while the workstation is off or
asleep wait in the app's offline queue and are sent when it is back.

To let Claude Code sessions on another tailnet device search and write scrap, see
[](../how-to/connect-claude-code.md); `SCRAP_PUBLIC_URL` is already set.

## Optional: ingest on your Claude seat

Photos are queued but not sent to Claude until you turn ingest on. On a Claude Team or
Enterprise seat it runs through Claude Code with a long-lived token
([ADR 0021](../explanations/decisions/0021-ingest-on-a-claude-seat-through-claude-p.md)). First
check with your organisation's Claude admin that unattended use of your seat is allowed. The
token can use your whole seat, and calls count against your seat's usage limits.

1. On any machine with Claude Code logged in to your seat, run `claude setup-token` and copy the
   token it prints.
2. From the clone, build the image with the CLI added:

   ```
   podman build -f Dockerfile.claude --build-arg BASE=localhost/scrap:dev \
       -t localhost/scrap-claude:dev .
   ```

   Rebuild this image whenever you rebuild `localhost/scrap:dev`, or scrap keeps running the old
   one.
3. In `~/.config/scrap/env`, set `SCRAP_IMAGE=localhost/scrap-claude:dev` and
   `SCRAP_MEMORY_MAX=1.5g` (ignored on cgroups v1, as on DLS workstations: there is no cap).
4. In `~/.config/scrap/ingest.env` (keep it mode 600; it is on your NFS home), set:

   ```
   SCRAP_INGEST=on
   SCRAP_LLM_BACKEND=cli
   CLAUDE_CODE_OAUTH_TOKEN=<your token>
   ```

5. Re-run `./deploy/install.sh`, which restarts scrap on the new image.

What the token gives away, the budget and the limits are in the how-to's "On a Claude seat, with
no API key", under {ref}`scrap-ingest-settings`. An API key works instead: it comes from a Claude
Console account, which is separate from a seat and billed per use.

## Stop or remove it

To stop scrap, its timers and Tailscale, and keep them from starting again at boot:

```
systemctl --user disable --now scrap.service scrap-backup.timer scrap-gc.timer \
    scrap-enrich-related.timer tailscaled.service
```

`systemctl --user enable --now` the same units starts them again.

To remove scrap, follow the how-to's "Uninstall" section in [](../how-to/deploy-single-server.md)
and also remove the drop-in folders, `~/.config/systemd/user/scrap*.d`. Before stopping
Tailscale, remove the Serve entry, then remove Tailscale itself:

```
ts serve --https=443 off
ts logout
systemctl --user disable --now tailscaled
rm ~/.config/systemd/user/tailscaled.service ~/.local/bin/tailscale ~/.local/bin/tailscaled
rm -r /scratch/$USER/tailscale
systemctl --user daemon-reload
```

Your data in `/scratch/$USER/scrap` stays until you delete it.
