# Try scrap on a DLS workstation (open-source demo)

In this tutorial you run scrap on your own Diamond workstation, with no `sudo`, as a demo for
colleagues: you open it in the workstation's browser, Claude Code in
[claude-sandbox](https://diamondlightsource.github.io/claude-sandbox/) searches and writes it over
MCP, and the links Claude gives you open in that browser. Other machines on the DLS network can
open it too. To capture from your phone, which is what scrap is mostly for, add Tailscale
({ref}`dls-tailscale`): phones cannot join the DLS network, so that path needs it.

DLS workstations run RHEL 8 with SELinux enforcing and cgroups v1, are shared with other users,
mount your home directory over NFS, and already have rootless podman set up with its storage on
`/scratch`. scrap runs as you, in a rootless podman pod, on a port of the workstation.

```{danger}
**Open-source material only.** This demo has **no login**: anyone who can reach the
workstation on the DLS network can read and change everything in it, and so can every other
user of the workstation. Who wrote a change is not trustworthy either: any client can send its
own `Tailscale-User-Login` header and be recorded as anyone. Put nothing in it that is not
already public. Real adoption at DLS will run on Kubernetes behind Keycloak instead.
```

This page follows one path for a demo. The general install, with a dedicated user and a system
Tailscale, is [](installation.md); every option, and the update, backup and troubleshooting
steps, are in [](../how-to/deploy-single-server.md).

```{note}
**What has been checked.** On 22–23 Oct 2026 this page was run by hand on a DLS workstation
(RHEL 8.10, cgroups v1, SELinux enforcing, podman 4.9.4, Tailscale 1.104.2): the pod with its
published port; `/healthz` on `localhost`, on the workstation's IP address and on its hostname;
MCP (`initialize` and a search) through `http://<host>:8790/mcp`, with page links on the
hostname; and claude-sandbox's network jail reaching scrap by IP address with `allow-ip`, and
blocked without it. Earlier, on 22 Oct: a phone on the tailnet opening the web app through
Tailscale Serve, installing it as an app and capturing photos, and ingest on a Claude seat
({ref}`dls-ingest`) reading two photos in about 10 seconds. Not yet checked: opening scrap from
another machine on the DLS network, a real Claude Code session in claude-sandbox end to end
({ref}`dls-claude-code`), starting at boot with systemd ({ref}`dls-systemd`), and automatic
backups ({ref}`dls-backup`).
```

## How it fits together

A podman pod is a group of containers that share one network namespace, with its own private
`127.0.0.1`. The pod `scrap-pod` holds:

- `scrap-pod-app`, scrap itself, listening on port 8000 in the pod. The pod publishes that port
  on the workstation as port 8790 (or another you choose), on all its addresses: `localhost`,
  its hostname `<host>.diamond.ac.uk` and its IP address.
- Optionally, `scrap-pod-ts`, the official
  [Tailscale image](https://hub.docker.com/r/tailscale/tailscale), which publishes scrap over
  HTTPS on your own tailnet so that your phone can reach it. Phone capture needs it: see
  {ref}`dls-tailscale`.

Nothing here needs `sudo`. The pod maps user 10001 in its containers to you on the
workstation, and the containers run as that user, so their processes and files are yours, not
in the subordinate id range that every DLS user shares.

Claude Code at DLS runs inside claude-sandbox, whose network jail blocks the DLS network except
for addresses you allow. You allow the workstation's IP address there, and Claude Code reaches
scrap at `http://<IP address>:8790/mcp`, whether claude-sandbox runs on the same workstation or
on another machine on the network ({ref}`dls-claude-code`).

## What you need

- A DLS workstation account with rootless podman working (`podman info` runs) and `git`.
- A directory of your own on the workstation's local disk, `/scratch/<fedid>`. scrap's SQLite
  database (in WAL mode) needs a local disk, not NFS. Your home directory is on NFS and follows
  you to every machine that mounts it, so keep scrap's data and secrets on `/scratch`, not in
  your home.
- A free port on the workstation. This page uses 8790; `ss -ltn | grep :8790` prints nothing if
  it is free. If it is taken, use another in its place throughout.
- To connect Claude Code,
  [claude-sandbox](https://diamondlightsource.github.io/claude-sandbox/dls/claude-at-dls.html)
  installed and logged in, on this workstation or another.

You do not need Python or Node: the image carries everything.

## Make the data folder

Make the folders on `/scratch`, open only to you:

```
base=/scratch/$USER/scrap-pod
mkdir -p $base/data $base/backups
chmod 700 $base
```

The commands below use `$base`, so set it again in each new shell.

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

## Write scrap's settings

Find the workstation's hostname and IP address:

```
getent hosts $(hostname -f)
```

It prints the IP address, such as `172.23.244.126`, then the hostname, such as
`pc0126.diamond.ac.uk`. (`hostname -I` is less reliable: it also lists the addresses of local
bridges, such as libvirt's `192.168.122.1`.) Put them in a settings file for scrap, readable
only by you:

```
(umask 077; cat >$base/scrap.env <<'EOF'
SCRAP_PUBLIC_URL=http://<host>.diamond.ac.uk:8790,http://localhost:8790,http://<IP address>:8790
TZ=Europe/London
EOF
)
```

- `SCRAP_PUBLIC_URL` lists the addresses scrap is reached at, comma separated. `/mcp` answers
  only requests addressed to one of them (or to loopback); any other gets
  `421 Invalid Host header`. The **first** makes the page links that Claude Code shows you, so
  put the hostname first: those links then open on any machine on the network, the workstation
  included. The IP address is there for claude-sandbox, which reaches scrap by IP address for
  now ({ref}`dls-claude-code`).
- `TZ` makes `due:today` follow your day rather than UTC.

See {ref}`scrap-ingest-settings`.

## Create the pod

```
podman pod create --name scrap-pod --userns=keep-id:uid=10001,gid=10001 -p 8790:8000
podman run -d --pod scrap-pod --name scrap-pod-app \
    -v $base/data:/data:z -e SCRAP_DATA_DIR=/data --env-file $base/scrap.env \
    localhost/scrap:dev serve --host 0.0.0.0 --port 8000
```

- `--userns=keep-id:uid=10001,gid=10001` maps scrap's user in the image, 10001, to you, so the
  files under `$base/data` stay yours. Podman takes it only on the pod, not on a container in
  one.
- `-p 8790:8000` publishes the pod's port 8000 on the workstation's port 8790. Podman takes
  ports only on the pod, and only when it is created: to change one, remove the pod and create
  it again (your data stays in `$base`).
- `--host 0.0.0.0` makes scrap listen on the pod's network, not only on its `127.0.0.1`, so that
  the published port reaches it.
- `:z` relabels the folder so that the container can write to it with SELinux enforcing.
- There is no memory cap: on cgroups v1, as on DLS workstations, rootless podman ignores
  `--memory`.

If you made the pod with an earlier version of this page, which published no port, remove it
first with `podman pod rm -f scrap-pod`; `$base`, and Tailscale's login in it, are kept.

Check that scrap answers:

```
curl http://localhost:8790/healthz
curl http://$(hostname -f):8790/healthz
```

Each should print `{"status":"ok",...}`. If scrap is not running, see `podman logs scrap-pod-app`
and {ref}`scrap-troubleshooting`.

(dls-browser)=
## Open it in the browser

On the workstation, open `http://localhost:8790`. To browsers, `localhost` is a secure context
even over plain HTTP, so the whole web app works there: you can install it as an app, and
captures made while scrap is stopped wait in its offline queue. See
[](../how-to/use-the-pwa.md).

From another machine on the DLS network, open `http://<host>.diamond.ac.uk:8790`. You can read,
search and edit there, but plain HTTP on a hostname is not a secure context, so that browser
cannot install the app or queue captures offline. The links Claude Code gives you use this
address, and open on the workstation too.

If other machines cannot connect, the workstation's firewall blocks the port; `localhost`, and
claude-sandbox on the same workstation, still work.

(dls-claude-code)=
## Connect Claude Code

```{warning}
claude-sandbox's jail reaching scrap with `allow-ip` has been checked, but not a whole Claude
Code session.
```

Claude Code sessions can search, read and write scrap through its MCP server at `/mcp`. At DLS,
Claude Code runs inside
[claude-sandbox](https://diamondlightsource.github.io/claude-sandbox/dls/claude-at-dls.html),
whose network jail blocks every address on the DLS network that you have not allowed. The steps
are the same whether claude-sandbox runs on this workstation or on another machine on the
network: in both, allow the scrap workstation's IP address.

1. On the machine where you run claude-sandbox, outside any container, add the scrap
   workstation's IP address (from `getent hosts` above) to `~/.config/claude-sandbox.conf`.
   That file **replaces** claude-sandbox's shipped configuration, so if you are creating it,
   keep the shipped defaults too:

   ```ini
   allow-write = /cache
   allow-ip = 172.23.142.119   # Diamond GitLab
   local-model-port = 1920
   allow-ip = <IP address>     # scrap
   ```

   `allow-ip` takes a bare IP address, and lets Claude reach every service on that address, not
   only scrap. If the file is new, run `claude-sandbox --recreate` in your project directory so
   that the container mounts it; recreating drops forge logins, so run
   `claude-sandbox gh-auth` again if you use it. Edits to an existing file apply at the next
   launch. See claude-sandbox's
   [network access](https://diamondlightsource.github.io/claude-sandbox/how-to/network-egress-jail.html).

2. In a container terminal (`claude-sandbox shell` in your project directory), add scrap for all
   your projects, and check that it connects:

   ```
   claude mcp add --transport http --scope user scrap http://<IP address>:8790/mcp
   claude mcp list
   ```

   `claude mcp list` should show `scrap` as connected. The address must be one of those in
   `SCRAP_PUBLIC_URL`, or `/mcp` answers `421 Invalid Host header`. If it does not connect,
   check the `allow-ip` line, and that a browser on that machine can open
   `http://<host>.diamond.ac.uk:8790/healthz` ({ref}`dls-browser`).

   Use the IP address, not the hostname, for now: claude-sandbox does not yet resolve hostnames
   for `allow-ip`. Once it does, `http://<host>.diamond.ac.uk:8790/mcp` works directly, and the
   IP address can come out of `SCRAP_PUBLIC_URL`.

3. Optionally, install the `scrap-post` skill, which posts a summary of a conversation to scrap
   when you say "post this to scrap". In the same container terminal:

   ```
   mkdir -p ~/.claude/skills/scrap-post
   curl -fsSL -o ~/.claude/skills/scrap-post/SKILL.md \
       https://raw.githubusercontent.com/gilesknap/scrap/main/skills/scrap-post/SKILL.md
   ```

In claude-sandbox's containers, `~/.claude` and `~/.claude.json` are kept in
`~/.config/terminal-config` on the host. So the server added with `--scope user`, and the skill,
survive `--recreate` and apply to every project you run in claude-sandbox. On the host, the skill
is at `~/.config/terminal-config/.claude/skills/scrap-post`.

To check it all, start Claude (`claude-sandbox` in your project directory) and ask it to search
scrap for something you have put there. It lists the pages it finds, with links such as
`http://<host>.diamond.ac.uk:8790/p/<slug>`: open one in the workstation's browser.

What the tools do, which to allow without asking, and how to check `/mcp` with `curl` are in
[](../how-to/connect-claude-code.md). Its steps for setting the address and restarting scrap
(`systemctl --user restart scrap`, the `scrap` user) are for the single-server install and do
not apply here: change `$base/scrap.env` and recreate the container instead ({ref}`dls-update`).

## Logs

The user journal is not available to users on DLS workstations, so `journalctl --user` shows
nothing. Each container keeps its own output:

```
podman logs scrap-pod-app
```

Under systemd ({ref}`dls-systemd`), a container is removed when its unit stops, and its logs go
with it.

(dls-update)=
## Update or change settings

Podman reads `--env-file` only when it creates a container, so after changing `$base/scrap.env`,
or to run a newly built image, remove scrap's container and run it again:

```
podman rm -f scrap-pod-app
podman run -d --pod scrap-pod --name scrap-pod-app \
    -v $base/data:/data:z -e SCRAP_DATA_DIR=/data --env-file $base/scrap.env \
    localhost/scrap:dev serve --host 0.0.0.0 --port 8000
```

Back up first if the new image may change the database: see {ref}`scrap-upgrade-db`.

Under systemd ({ref}`dls-systemd`), do not remove containers by hand. The units create each
container afresh at every start, reading `$base/scrap.env` again and running whatever
`localhost/scrap:dev` now is, so after a settings change or a rebuild, restart the container's
unit:

```
systemctl --user restart container-scrap-pod-app.service
```

To change a container's command line, such as switching to `localhost/scrap-claude:dev`,
regenerate the units as described there.

## Start it again

The pod does not start by itself, and it stops when you log out: unless your account lingers,
systemd stops all your processes when your last session ends. After a reboot, a logout or
`podman pod stop`:

```
podman pod start scrap-pod
```

To keep the pod running after you log out, run `loginctl enable-linger` (if it is refused, see
below). That alone keeps a pod you started by hand alive; to start it at boot too, follow
{ref}`dls-systemd`.

(dls-systemd)=
### Optional: start it at boot with systemd

```{warning}
Not yet run end to end at DLS. Units generated from an earlier version of this pod, without a
published port, have been checked with `systemd-analyze --user verify` on a DLS workstation, but
not enabled there.
```

Podman 4.9 has no Quadlet `.pod` units, so generate systemd user units from the running pod
instead; `podman generate systemd` prints a DEPRECATED notice recommending Quadlet, which you can
ignore here. The units record the command lines of the pod (its published port included) and of
each container in it, Tailscale's too if you have added it, so the pod must be running as above.
Each unit gets a guard so that it runs only on this workstation, not on another machine that
mounts your NFS home:

```
mkdir -p ~/.config/systemd/user
cd ~/.config/systemd/user
podman generate systemd --new --files --name scrap-pod
for f in pod-scrap-pod.service container-scrap-pod-*.service; do
    mkdir -p $f.d
    printf '[Unit]\nConditionPathIsDirectory=/scratch/%s/scrap-pod\n' "$USER" >$f.d/host.conf
done
systemd-analyze --user verify pod-scrap-pod.service
```

With `--new`, systemd creates the pod and containers afresh at each start and removes them at each
stop, and restarts a container that fails. Stop and remove the ones you made by hand, then start
the pod's unit:

```
podman pod stop scrap-pod
podman pod rm scrap-pod
systemctl --user daemon-reload
systemctl --user enable --now pod-scrap-pod.service
loginctl enable-linger
```

`enable-linger` lets your user services run when you are not logged in, and start at boot. If it
is refused, ask IT to run `sudo loginctl enable-linger <fedid>` for you. To change a container's
command line later, first `systemctl --user disable --now pod-scrap-pod.service`, then make the
pod by hand again as above and regenerate the units.

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

To stop scrap, `podman pod stop scrap-pod` (or, under systemd,
`systemctl --user stop pod-scrap-pod.service`); start it again as above.

To remove it, first take the pod off your tailnet if you added Tailscale
({ref}`dls-tailscale-remove`), then stop and remove the pod:

```
podman pod stop scrap-pod
podman pod rm scrap-pod
```

Under systemd, run `systemctl --user disable --now pod-scrap-pod.service` instead, remove the
`*scrap-pod*` files and folders from `~/.config/systemd/user`, and run
`systemctl --user daemon-reload`. Take scrap out of Claude Code with `claude mcp remove scrap`
in a claude-sandbox container terminal, and remove its `allow-ip` line.

Your data in `/scratch/$USER/scrap-pod` stays until you delete it.

(dls-tailscale)=
## Phone capture with Tailscale (recommended)

scrap is mostly for quick capture from your phone: snap a whiteboard, share a link from another
app, jot a note, from anywhere. The installed app keeps captures in an offline queue until scrap
is reachable, and on Android it appears in the share sheet. Your phone cannot join the DLS
network, so Tailscale carries scrap to it over HTTPS: a second container in the pod joins your
own tailnet and publishes scrap there as `https://scrap.<tailnet>.ts.net`. The desktop demo above
works without it, but there is no phone capture without it.

**Check with DLS IT policy before you run Tailscale on a workstation.** It connects the
workstation to an outside network that IT does not manage.

The Tailscale container, `scrap-pod-ts`, runs with `--tun=userspace-networking`, so that it needs
no network device. Tailscale Serve, in this container, publishes `http://127.0.0.1:8000` (scrap,
in the same pod) on your tailnet. It runs as you, like scrap: anything running as you can drive
it, and whoever owns or administers your tailnet (you, if you follow {ref}`dls-make-tailnet`) can
reach scrap through it. See {ref}`scrap-access`.

:::{dropdown} Why Tailscale does not run as root in its container
DLS workstations give every user the same subordinate id range in `/etc/subuid`. Rootless
podman maps root in a container, and every id other than your own, into that range, so root in
your container is the same workstation id as root in anyone else's, and another user can become
it with `podman unshare`. A `tailscaled` running as root in its container could then be
signalled by other users, have its node key read, and be driven through its control socket via
`/proc/<pid>/root`. So on these workstations, never run a long-lived container process as root,
or as any id other than the one mapped to you, inside a rootless container. This page runs
`tailscaled` as user 10001, which is you. It does not need root: Serve here only forwards to
`http://127.0.0.1:8000`.
:::

You need a phone with the [Tailscale app](https://tailscale.com/download).

(dls-make-tailnet)=
### Make a tailnet

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
new; it also drops the default policy's `nodeAttrs` that allow Funnel, so scrap cannot be put on
the internet by mistake.

### Add Tailscale to the pod

Pick a name for the pod on your tailnet, such as `scrap`; it becomes
`https://scrap.<tailnet>.ts.net`. Add that address to the end of `SCRAP_PUBLIC_URL` in
`$base/scrap.env`, after a comma, so that Claude Code on another tailnet device can use `/mcp`
through it too:

```
SCRAP_PUBLIC_URL=http://<host>.diamond.ac.uk:8790,http://localhost:8790,http://<IP address>:8790,https://scrap.<tailnet>.ts.net
```

Keep the hostname first, so that the links Claude Code gives you still open in the workstation's
browser, and recreate scrap's container ({ref}`dls-update`). Then fetch Tailscale's image, make a
folder for its state, and start it in the pod:

```
podman pull docker.io/tailscale/tailscale:stable
mkdir -p $base/tailscale
podman run -d --pod scrap-pod --name scrap-pod-ts --user 10001:10001 \
    -v $base/tailscale:/var/lib/tailscale:z \
    --entrypoint tailscaled docker.io/tailscale/tailscale:stable \
    --tun=userspace-networking --statedir=/var/lib/tailscale --socket=/tmp/tailscaled.sock
```

- `stable` moves with each release. To stay on one version, use a tag such as `v1.104.2`
  instead, here and below.
- Tailscale's state identifies this machine on your tailnet, so it stays on `/scratch`, not in
  your NFS home.
- `--user 10001:10001` runs `tailscaled` as you. Containers in this pod run as 10001 anyway,
  but the page says so because it matters: see "Why Tailscale does not run as root in its
  container" above.
- `--socket=/tmp/tailscaled.sock` puts `tailscaled`'s control socket where user 10001 can create
  it; the default, under `/var/run/tailscale`, needs root.
- `--entrypoint tailscaled` skips the image's own start-up script, which gives up and exits if
  you have not logged in within about 40 seconds.

Check that Tailscale's container reaches scrap inside the pod; it should print
`{"status":"ok",...}`:

```
podman exec scrap-pod-ts wget -qO- http://127.0.0.1:8000/healthz
```

### Join your tailnet and publish scrap

Every `tailscale` command must name that socket, so define a shell function for them (again in
each new shell, like `$base`):

```
ts() { podman exec scrap-pod-ts tailscale --socket=/tmp/tailscaled.sock "$@"; }
```

Log in, with a terminal attached so that you can watch it:

```
podman exec -it scrap-pod-ts tailscale --socket=/tmp/tailscaled.sock up --hostname=scrap
```

This prints a login URL and waits: open it in any browser and log in to your new tailnet. (To
join without a browser, make an [auth key](https://tailscale.com/kb/1085/auth-keys) in the admin
console and pass `--auth-key=<key>` instead.) Then publish scrap with Tailscale Serve on the
standard HTTPS port:

```
ts serve --bg --https=443 http://127.0.0.1:8000
ts serve status
```

`--bg` keeps the setting, in Tailscale's state on `/scratch`, across restarts. `serve status`
prints the address. If it is not `https://scrap.<tailnet>.ts.net` (Tailscale adds a suffix if the
name is taken), put the real one in `$base/scrap.env` and recreate scrap's container
({ref}`dls-update`). Where UDP is blocked, Tailscale falls back to its DERP relays over HTTPS on
port 443: slower, but it works.

(dls-check)=
### Check it from your phone

The workstation itself is not on your tailnet (only the pod is), so check from your phone: with
Tailscale connected, open `https://scrap.<tailnet>.ts.net/healthz`, which should show
`{"status":"ok",...}`. The first request can take a few seconds while Tailscale fetches the
certificate.

If `ts status` shows the pod's node as offline, or a device hangs on "loading…", run
`ts up --hostname=scrap` again: after a restart the node's registration can stall, and running
`up` again registers it at once. The login and Serve setting are kept.

(dls-phone)=
### Open it on your phone

With the Tailscale app connected, open `https://scrap.<tailnet>.ts.net` on your phone and install
the app: see [](../how-to/use-the-pwa.md). Captures made while the workstation is off, or the pod
stopped, wait in the app's offline queue and are sent when it is back.

### Run and update Tailscale

`podman logs scrap-pod-ts` and `ts status` show what Tailscale is doing. `podman pod start` and
`podman pod stop` start and stop it with scrap. To update it, `podman pull` its image, then
remove and run `scrap-pod-ts` as above; its login and Serve setting are kept on `/scratch`.
Under systemd, add Tailscale before you generate the units, so that they include it, and
restart `container-scrap-pod-ts.service` after a pull.

(dls-tailscale-remove)=
### Remove Tailscale

While the pod is up, take it off your tailnet, then remove the container and its state:

```
ts serve reset
ts logout
podman rm -f scrap-pod-ts
rm -r /scratch/$USER/scrap-pod/tailscale
```

If you set up systemd, the pod must be running under it for the first two commands, and you
regenerate the units without `scrap-pod-ts` afterwards ({ref}`dls-systemd`). If Tailscale's state
was made by an older version of this page, which ran Tailscale as root in its container, some
files are not yours: use `podman unshare rm -r` instead. Then delete the machine under
**Machines** in the Tailscale admin console, if it is still listed, and take its address out of
`SCRAP_PUBLIC_URL`.

(dls-ingest)=
## Optional: ingest on your Claude seat

Photos are queued but not sent to Claude until you turn ingest on. On a Claude Team or
Enterprise seat it runs through Claude Code with a long-lived token
([ADR 0021](../explanations/decisions/0021-ingest-on-a-claude-seat-through-claude-p.md)). First
check with your organisation's Claude admin that unattended use of your seat is allowed. The
token can use your whole seat, and calls count against your seat's usage limits.

1. On any machine with Claude Code logged in to your seat, run `claude setup-token` and copy the
   token it prints: only the token, one line of about 108 characters starting `sk-ant-oat01-`,
   not the line after it.
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

   `podman inspect scrap-pod-app` shows the container's environment, token included, in plain
   text: do not paste its output anywhere.

4. Recreate scrap's container as in {ref}`dls-update`, with `localhost/scrap-claude:dev` in place
   of `localhost/scrap:dev` (under systemd, regenerate the units).

What the token gives away, the budget and the limits are in the how-to's "On a Claude seat, with
no API key", under {ref}`scrap-ingest-settings`. An API key works instead: it comes from a Claude
Console account, which is separate from a seat and billed per use.

If ingest pauses for `auth` with `401 OAuth access token is invalid`, the token was copied
wrongly. Put only the `sk-ant-oat01-…` token in `$base/scrap.env`, recreate scrap's container
({ref}`dls-update`), then press **Resume** on the paused photo in the app (or
`POST /api/ingest/resume`). Nothing is lost while ingest is paused.

## Where this goes next

Real adoption at DLS will run scrap on Kubernetes ([](../how-to/deploy-kubernetes.md)), behind
a Keycloak login. Nothing on this page needs undoing first: it is the same image, and a backup
of the data here can be restored there ({ref}`scrap-restore`).
