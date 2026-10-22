# Try scrap on a DLS workstation

In this tutorial you run scrap on your own Diamond workstation, with no `sudo`, and open it from
your phone. DLS workstations run RHEL 8 with SELinux enforcing and cgroups v1, are shared with
other users, mount your home directory over NFS, and already have rootless podman set up with its
storage on `/scratch`. Your phone cannot join the workstation network, so Tailscale carries scrap
to it over HTTPS. Both run as you, as two containers in one rootless podman pod.

This page follows one path for a trial. The general install, with a dedicated user and a system
Tailscale, is [](installation.md); every option, and the update, backup and troubleshooting
steps, are in [](../how-to/deploy-single-server.md).

```{note}
**What has been checked.** On 22 Oct 2026 the steps up to {ref}`dls-phone` were run by hand on a
DLS workstation (RHEL 8.10, cgroups v1, SELinux enforcing, podman 4.9.4, Tailscale 1.104.2): a
phone on the tailnet opened the web app through Tailscale Serve and captured a photo. Ingest was
not turned on. Starting the pod at boot under systemd ({ref}`dls-systemd`) and backups
({ref}`dls-backup`) are not automated, and the systemd steps have not been run end to end at DLS.
```

```{warning}
v0 of scrap has **no login**. Anyone who can reach it can read and change everything. Only
expose it through Tailscale Serve (tailnet only, never `tailscale funnel`).
```

**Check with DLS IT policy before you run Tailscale on a workstation.** It connects the
workstation to an outside network that IT does not manage.

## How it fits together

A podman pod is a group of containers that share one network namespace, with its own private
`127.0.0.1`. The pod `scrap-pod` holds two containers:

- `scrap-pod-app`, scrap itself, listening on the pod's `127.0.0.1:8000`. Nothing is published
  to the workstation, so `127.0.0.1:8000` on the workstation reaches nothing.
- `scrap-pod-ts`, the official [Tailscale image](https://hub.docker.com/r/tailscale/tailscale),
  with `--tun=userspace-networking` so that it needs no network device. Tailscale Serve, in this
  container, publishes `http://127.0.0.1:8000` on your tailnet as
  `https://<name>.<tailnet>.ts.net`.

Rootless podman maps root in a container to an unprivileged id of yours, so nothing here needs
`sudo`. It still matters that `tailscaled` runs as root in its container: since Tailscale 1.98.9
([TS-2026-005](https://tailscale.com/security-bulletins#ts-2026-005)), some Serve settings are
accepted only from a local admin, which a `tailscaled` run directly as you is not.

## What runs as you

Without `sudo` there is no dedicated user, so scrap, its data and Tailscale all run as you. Other
users on the workstation cannot reach scrap: it listens only inside the pod, and its files are
yours. Anything running in your own account can: it can `podman exec` into the pod, read and
change all of scrap's data, and send its own `Tailscale-User-Login` header to be recorded as any
author. So can root and the workstation's admins, and so can whoever owns or administers your
tailnet (you, if you follow {ref}`dls-make-tailnet`). That is fine for a trial; for lasting use,
follow [](installation.md) on a machine where scrap has its own user. See {ref}`scrap-access`.

## What you need

- A DLS workstation account with rootless podman working (`podman info` runs) and `git`.
- A directory of your own on the workstation's local disk, `/scratch/<fedid>`. scrap's SQLite
  database (in WAL mode) needs a local disk, not NFS. Your home directory is on NFS and follows
  you to every machine that mounts it, so keep scrap's data, Tailscale's state (which identifies
  this machine) and any secrets on `/scratch`, not in your home.
- A phone with the [Tailscale app](https://tailscale.com/download), and another device on which
  to run Claude Code if you want to connect it (see {ref}`dls-check`).

You do not need Python or Node: the images carry everything.

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
   [HTTPS certificates](https://tailscale.com/kb/1153/enabling-https). Note the tailnet DNS name
   shown there, `<tailnet>.ts.net`.
4. In the admin console, under **Access controls**, replace the whole policy with:

   ```json
   {
     "grants": [
       {"src": ["autogroup:member"], "dst": ["autogroup:self"], "ip": ["tcp:443"]}
     ]
   }
   ```

Do step 4 **before** the pod joins the tailnet. In userspace mode, Tailscale forwards an inbound
tailnet connection to any TCP port that Serve does not handle to the same port on the pod's
`127.0.0.1` ([wgengine/netstack](https://github.com/tailscale/tailscale/tree/main/wgengine/netstack)).
Under the default policy, which lets every device reach every port, any device on your tailnet
could reach scrap directly on port 8000, over plain HTTP and without the identity header that
Serve adds. This policy lets your own devices reach each other on port 443 only, and nothing
else. Replacing the policy wipes whatever was there, which is fine only because the tailnet is
new.

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
can instead `podman pull ghcr.io/gilesknap/scrap:<version>` and use that name in place of
`localhost/scrap:dev` below.

Fetch Tailscale's image too:

```
podman pull docker.io/tailscale/tailscale:stable
```

`stable` moves with each release. To stay on one version, use a tag such as `v1.104.2` instead,
here and below.

## Create the pod

Pick a name for the workstation on your tailnet, such as `scrap`; it becomes
`https://scrap.<tailnet>.ts.net`. Make the folders on `/scratch`, and a settings file for scrap
there, readable only by you:

```
base=/scratch/$USER/scrap-pod
mkdir -p $base/data $base/backups $base/tailscale
cat >$base/scrap.env <<'EOF'
SCRAP_PUBLIC_URL=https://scrap.<tailnet>.ts.net
TZ=Europe/London
EOF
chmod 600 $base/scrap.env
```

`SCRAP_PUBLIC_URL` lets Claude Code reach `/mcp` through Serve; `TZ` makes `due:today` follow
your day rather than UTC. See {ref}`scrap-ingest-settings`. The commands below use `$base`, so
set it again in each new shell.

Create the pod, then start scrap and Tailscale in it:

```
podman pod create --name scrap-pod --userns=keep-id:uid=10001,gid=10001
podman run -d --pod scrap-pod --name scrap-pod-app \
    -v $base/data:/data:z -e SCRAP_DATA_DIR=/data --env-file $base/scrap.env \
    localhost/scrap:dev serve --host 127.0.0.1 --port 8000
podman run -d --pod scrap-pod --name scrap-pod-ts --user 0:0 \
    -v $base/tailscale:/var/lib/tailscale:z \
    --entrypoint tailscaled docker.io/tailscale/tailscale:stable \
    --tun=userspace-networking --statedir=/var/lib/tailscale
```

- `--userns=keep-id:uid=10001,gid=10001` maps scrap's user in the image, 10001, to you, so the
  files under `$base/data` stay yours. Podman takes it only on the pod, not on a container in
  one.
- `:z` relabels each folder so that a container can write to it with SELinux enforcing.
- There is no memory cap: on cgroups v1, as on DLS workstations, rootless podman ignores
  `--memory`.
- `--entrypoint tailscaled` skips the image's own start-up script, which gives up and exits if
  you have not logged in within about 40 seconds.

Check that scrap answers inside the pod and not on the workstation:

```
podman exec scrap-pod-ts wget -qO- http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/healthz
```

The first should print `{"status":"ok",...}`; the second should fail with
`Connection refused`. If scrap is not running, see `podman logs scrap-pod-app` and
{ref}`scrap-troubleshooting`.

## Join your tailnet and publish scrap

```
podman exec -it scrap-pod-ts tailscale up --hostname=scrap
```

This prints a login URL and waits: open it in any browser and log in to your new tailnet. (To
join without a browser, make an [auth key](https://tailscale.com/kb/1085/auth-keys) in the admin
console and pass `--auth-key=<key>` instead.) Then publish scrap with Tailscale Serve on the
standard HTTPS port:

```
podman exec scrap-pod-ts tailscale serve --bg --https=443 http://127.0.0.1:8000
podman exec scrap-pod-ts tailscale serve status
```

`--bg` keeps the setting, in Tailscale's state on `/scratch`, across restarts. `serve status`
prints the address. If it is not `https://scrap.<tailnet>.ts.net` (Tailscale adds a suffix if the
name is taken), put the real one in `$base/scrap.env` and recreate scrap's container
({ref}`dls-update`). Where UDP is blocked, Tailscale falls back to its DERP relays over HTTPS on
port 443: slower, but it works.

(dls-check)=
### Check it from another device

The workstation itself is not on your tailnet (only the pod is), so check from your phone or
another tailnet device instead: with Tailscale connected, open
`https://scrap.<tailnet>.ts.net/healthz`, which should show `{"status":"ok",...}`. The first
request can take a few seconds while Tailscale fetches the certificate. For the same reason, run
Claude Code on another device on your tailnet, not on the workstation.

(dls-phone)=
## Open it on your phone

With the Tailscale app connected, open `https://scrap.<tailnet>.ts.net` on your phone and install
the app: see [](../how-to/use-the-pwa.md). Captures made while the workstation is off, or the pod
stopped, wait in the app's offline queue and are sent when it is back.

To let Claude Code sessions on another tailnet device search and write scrap, see
[](../how-to/connect-claude-code.md); `SCRAP_PUBLIC_URL` is already set.

## Logs

The user journal is not available to users on DLS workstations, so `journalctl --user` shows
nothing. Each container keeps its own output:

```
podman logs scrap-pod-app
podman logs scrap-pod-ts
podman exec scrap-pod-ts tailscale status
```

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
3. Add to `$base/scrap.env`, which stays mode 600 on `/scratch` (never put the token in your NFS
   home):

   ```
   SCRAP_INGEST=on
   SCRAP_LLM_BACKEND=cli
   CLAUDE_CODE_OAUTH_TOKEN=<your token>
   ```

4. Recreate scrap's container as in {ref}`dls-update`, with `localhost/scrap-claude:dev` in place
   of `localhost/scrap:dev`.

What the token gives away, the budget and the limits are in the how-to's "On a Claude seat, with
no API key", under {ref}`scrap-ingest-settings`. An API key works instead: it comes from a Claude
Console account, which is separate from a seat and billed per use.

(dls-update)=
## Update or change settings

Podman reads `--env-file` only when it creates a container, so after changing `$base/scrap.env`,
or to run a newly built image, remove scrap's container and run it again:

```
podman rm -f scrap-pod-app
podman run -d --pod scrap-pod --name scrap-pod-app \
    -v $base/data:/data:z -e SCRAP_DATA_DIR=/data --env-file $base/scrap.env \
    localhost/scrap:dev serve --host 127.0.0.1 --port 8000
```

Back up first if the new image may change the database: see {ref}`scrap-upgrade-db`. To update
Tailscale, `podman pull` its image, then remove and run `scrap-pod-ts` the same way. Its login
and Serve setting are kept on `/scratch`.

## Start it again after a reboot

The pod does not start by itself. After the workstation restarts, or after `podman pod stop`:

```
podman pod start scrap-pod
```

(dls-systemd)=
### Optional: start it at boot with systemd

```{warning}
Not yet run end to end at DLS. The generated units have been checked with
`systemd-analyze --user verify` on a DLS workstation, but not enabled there.
```

Podman 4.9 has no Quadlet `.pod` units, so generate systemd user units from the running pod
instead. (`podman generate systemd` is deprecated in podman 5 in favour of Quadlet.) The units
record each container's command line, so the pod must be running as above. Each unit gets a
guard so that it runs only on this workstation, not on another machine that mounts your NFS home:

```
mkdir -p ~/.config/systemd/user
cd ~/.config/systemd/user
podman generate systemd --new --files --name scrap-pod
for u in pod-scrap-pod container-scrap-pod-app container-scrap-pod-ts; do
    mkdir -p $u.service.d
    printf '[Unit]\nConditionPathIsDirectory=/scratch/%s/scrap-pod\n' "$USER" \
        >$u.service.d/host.conf
done
systemd-analyze --user verify pod-scrap-pod.service
```

With `--new`, systemd creates the pod and containers afresh at each start and removes them at
each stop, so stop and remove the ones you made by hand, then start the pod's unit:

```
podman pod stop scrap-pod
podman pod rm scrap-pod
systemctl --user daemon-reload
systemctl --user enable --now pod-scrap-pod.service
loginctl enable-linger
```

`enable-linger` lets your user services run when you are not logged in, and start at boot. If it
is refused, ask IT to run `sudo loginctl enable-linger <fedid>` for you. To change a container
later, make the pod by hand again as above and regenerate the units.

(dls-backup)=
## Back up

`deploy/install.sh` and its units are not used here: its `scrap.service` would start a second
scrap. Its daily backup and nightly gc timers have no equivalent for the pod yet; until then,
back up by hand. A backup is safe while scrap runs:

```
stamp=$(date -u +%Y%m%dT%H%M%SZ)
podman run --rm --userns=keep-id:uid=10001,gid=10001 --network=none \
    -v $base/data:/data:z -v $base/backups:/backups:z -e SCRAP_DATA_DIR=/data \
    localhost/scrap:dev backup /backups/$stamp
```

Old backups are not deleted for you. `/scratch` is not backed up either, and the backups are on
the same disk as the data: copy `$base/backups` somewhere else if what you put in scrap matters.
To restore, see {ref}`scrap-restore`.

## Stop or remove it

To stop scrap and Tailscale, `podman pod stop scrap-pod` (or, under systemd,
`systemctl --user stop pod-scrap-pod.service`); start them again as above.

To remove them, first take the workstation off your tailnet, then remove the pod and Tailscale's
state:

```
podman exec scrap-pod-ts tailscale serve reset
podman exec scrap-pod-ts tailscale logout
podman pod stop scrap-pod
podman pod rm scrap-pod
podman unshare rm -r /scratch/$USER/scrap-pod/tailscale
```

Some of Tailscale's files belong to root in the container, which `podman unshare` lets you
remove. Then delete the machine under **Machines** in the Tailscale admin console. If you set up
systemd, first `systemctl --user disable --now pod-scrap-pod.service` and remove the
`*scrap-pod*` files and folders from `~/.config/systemd/user`.

Your data in `/scratch/$USER/scrap-pod` stays until you delete it.
