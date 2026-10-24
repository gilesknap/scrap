(scrap-dls)=
# Run scrap on a DLS workstation

How to run scrap as a demo on your own Diamond Light Source workstation, with no `sudo`, and let
Claude Code in [claude-sandbox](https://diamondlightsource.github.io/claude-sandbox/) reach it.
It is the container install of [](../tutorials/install-lan.md) with the DLS differences below.
For a hardened install with a dedicated user, see [](../tutorials/install-server.md).

```{danger}
**Open-source material only.** This demo has **no login**: anyone who can reach the
workstation on the DLS network can read and change everything in it, and so can every other
user of the workstation. Who wrote a change is not trustworthy either: any client can send its
own `Tailscale-User-Login` header and be recorded as anyone. Put nothing in it that is not
already public. Real adoption at DLS will run on Kubernetes behind Keycloak instead
([](deploy-kubernetes.md)).
```

DLS workstations run RHEL 8 with SELinux enforcing and cgroups v1, are shared with other users,
mount your home directory over NFS, and have rootless podman with its storage on `/scratch`.

## Keep the data on `/scratch`

scrap's SQLite database needs a local disk, not NFS, and your NFS home follows you to every
machine. Keep the data and the settings file on `/scratch`:

```
base=/scratch/$USER/scrap-pod
mkdir -p $base/data
chmod 700 $base
image=ghcr.io/gilesknap/scrap:0.2.2
```

Write `$base/scrap.env` as in the LAN tutorial's settings step (mode 600), with the workstation's
full name first, then `localhost`:

```
SCRAP_PUBLIC_URL=http://<host>.diamond.ac.uk:8790,http://localhost:8790
TZ=Europe/London
```

## Create the pod

```
podman pod create --name scrap-pod --userns=keep-id:uid=10001,gid=10001 -p 8790:8000
podman run -d --pod scrap-pod --name scrap-pod-app \
    -v $base/data:/data:z -e SCRAP_DATA_DIR=/data --env-file $base/scrap.env \
    $image serve --host 0.0.0.0 --port 8000
curl http://localhost:8790/healthz
```

- `--userns=keep-id:uid=10001,gid=10001` maps scrap's user in the image, 10001, to you, so its
  processes and files are yours and not in the subordinate id range that every DLS user shares.
  Podman takes it only on the pod.
- `-p 8790:8000` publishes the port without `sudo`. Podman takes ports only on the pod, and only
  when it is created; to change one, remove the pod and make it again (the data stays).
- `:z` relabels the folder so the container can write to it under SELinux.
- There is no memory cap: on cgroups v1, rootless podman ignores `--memory`.
- `--env-file` is read only when a container is created, so after changing `scrap.env`
  run `podman rm -f scrap-pod-app` and the `podman run` again.

Open `http://localhost:8790` on the workstation; `localhost` is a secure context, so the app can
be installed. Other machines use `http://<host>.diamond.ac.uk:8790`, if the firewall allows it.
The pod does not survive a logout or reboot: `podman pod start scrap-pod` brings it back.

## Connect Claude Code in claude-sandbox

claude-sandbox's network jail gives the agent its own `localhost` and blocks the DLS network. To
reach scrap on the same workstation, relay its port with `local-port`, in
`~/.config/claude-sandbox.conf` on the workstation. That file **replaces** the shipped
configuration, so keep the defaults:

```ini
allow-write = /cache
allow-ip = 172.23.142.119   # Diamond GitLab
local-model-port = 1920
local-port = 8790           # scrap
```

`local-port` relays only that port; it relies on the launcher's default host networking (not
`--bridge`). If the file is new, run `claude-sandbox --recreate` in each project whose container
exists. Then, in a container terminal (`claude-sandbox shell`):

```
claude mcp add --transport http --scope user scrap http://localhost:8790/mcp
claude mcp list
```

From claude-sandbox on another machine, use `allow-ip = <workstation IP address>` instead of
`local-port` (the IP address, from `getent hosts $(hostname -f)`, not the hostname: claude-sandbox
does not resolve hostnames for `allow-ip`; it lets Claude reach every service on that machine).
Add `http://<IP address>:8790` to `SCRAP_PUBLIC_URL` after the hostname, recreate the container,
and add scrap with `http://<IP address>:8790/mcp`. Without `allow-ip`, the jail blocks the IP address. More on the tools and the
`s` skill: [](connect-claude-code.md).

To read photos on a Claude seat instead of a key, see [](../tutorials/ingest-with-claude-seat.md).
Tailscale on a workstation (for phone capture) needs IT's agreement and care with user ids; it is
not covered here, but the earlier version of this page, in git history, has the checked steps.

```{note}
**What has been checked.** On 22–23 Oct 2026 the longer page this one replaces was run by hand on a
DLS workstation, with release 0.1.0 (this page's 0.2.2 pin has not been re-run)
(RHEL 8.10, cgroups v1, SELinux enforcing, podman 4.9.4, Tailscale 1.104.2): the pod with its
published port; `/healthz` on `localhost`, on the workstation's IP address and on its hostname;
MCP (`initialize` and a search) through `http://<host>:8790/mcp`, with page links on the
hostname; claude-sandbox's network jail (in its 5.0.0-beta.1 image, with the launcher's default
host networking) reaching scrap at `http://localhost:8790` with `local-port`, while the
workstation's IP address stayed blocked; the jail reaching scrap by IP address with `allow-ip`,
and blocked without it; and systemd units generated from the pod, started, restarted and
stopped. Earlier, on 22 Oct: a phone on the tailnet opening the web app through Tailscale
Serve, installing it as an app and capturing photos, and ingest on a Claude seat reading two
photos in about 10 seconds. Not yet checked: opening scrap from another machine on the DLS
network, a real Claude Code session in claude-sandbox end to end, starting at boot with
systemd, and automatic backups.
```
