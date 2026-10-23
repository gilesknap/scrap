# Run in a container

Try scrap, or run it by hand, from the container image: scrap and its dependencies are already
installed. This page is a quickstart with Docker or podman. For a real, persistent install
(a service that restarts, daily backups, Tailscale), follow [](deploy-single-server.md); on
Kubernetes, see [](deploy-kubernetes.md).

```{warning}
v0 of scrap has **no login**. Anyone who can reach it can read and change everything. Publish
the port on loopback only (`127.0.0.1:8000:8000`, as below, not `-p 8000:8000`, which opens it to
every network the host is on), and put Tailscale Serve or an authenticating reverse proxy in front
of it for anything beyond this machine. Read {ref}`scrap-access` first.
```

## Get the image

Images are published to GHCR ([`ghcr.io/gilesknap/scrap`](https://ghcr.io/gilesknap/scrap)) only
when a release tag is pushed, for linux/amd64 and linux/arm64. The tags are the release versions
(see the [releases](https://github.com/gilesknap/scrap/releases)), and `latest`, which follows the
newest release. Every tag moves `latest`, pre-releases included, so pin an exact version for
anything you keep running.

Until a release is published, build the image yourself:

```
git clone https://github.com/gilesknap/scrap.git
cd scrap
docker build -t localhost/scrap:dev .       # or: podman build -t localhost/scrap:dev .
```

Build from a git clone, not a bare source archive: the version string that `--version` reports is
derived from git. Node is not needed on the host, because the PWA is built inside the image build,
but the first build downloads Node, Python and the npm and uv dependencies, so it takes a while.
The published multi-arch image comes from this same Dockerfile. Leave `--target` alone: the
`developer` target is the devcontainer image, not the one to run; the default final stage is the
runtime image.

Once releases exist you can instead pull one, and use its name in place of `localhost/scrap:dev`
below:

```
docker pull ghcr.io/gilesknap/scrap:<version>
```

Check the image runs:

```
docker run --rm localhost/scrap:dev --version
```

It prints the version string and exits.

## Run the service

The image's entrypoint is `scrap`, so everything after the image name is a `scrap` subcommand
(`serve`, `backup`, `restore`, `export`, `import`, `gc`, `enrich`, `ingest-once`; see the
[CLI reference](../reference/api.md)). With no arguments it runs `--version`. To run the service:

```
docker run --rm -p 127.0.0.1:8000:8000 -v scrap-data:/data \
    localhost/scrap:dev serve --host 0.0.0.0 --port 8000
```

`--host 0.0.0.0` is needed because `serve` defaults to `127.0.0.1`, which inside a container is
unreachable from the published port. The container is the network boundary here: it is the
`-p 127.0.0.1:...` that keeps scrap off the host's other interfaces. As an alternative to a port,
`serve --uds PATH` listens only on a Unix socket (not with `--host` or `--port`); that is what the
single-server install uses.

Check it works, from the host (the image has no `curl`):

```
curl http://127.0.0.1:8000/healthz
```

It answers `{"status":"ok","version":...,"max_upload_bytes":...}`. Open <http://127.0.0.1:8000>
for the PWA (see [](use-the-pwa.md)). The PWA needs a secure context, and a loopback address
counts as one; to reach scrap by any other hostname it must be served over HTTPS. `/mcp` (see
[](connect-claude-code.md)) answers only loopback hosts and those in `SCRAP_PUBLIC_URL`, with
`421` for any other `Host`.

## Keep the data

The image keeps everything (the database and the files) in `/data`, declared as a volume and set
by `SCRAP_DATA_DIR=/data`, and runs as an unprivileged user, uid 10001. Without `-v` the data
goes to an anonymous volume that is easy to lose; always give the volume a name or a path.

- **A named volume** (`-v scrap-data:/data`) works as it is.
- **A host directory** must be writable by uid 10001, otherwise scrap fails with "Permission
  denied" writing `/data`. With Docker, either run as the directory's owner,
  `--user "$(id -u):$(id -g)"`, or `chown 10001:10001` it. With rootless podman, add
  `--userns=keep-id:uid=10001,gid=10001`, which maps uid 10001 in the container to you. On SELinux
  systems (Fedora, RHEL) add `:Z` to the volume, for example `-v "$PWD/data:/data:Z"`; use
  lowercase `:z` instead if other containers (a backup, say) share the folder.

## Settings

Settings are environment variables. Pass them with `-e NAME=value`, or put them in a file and pass
`--env-file`, as plain `KEY=value` lines without quotes (podman takes the rest of the line
literally). For example:

```
SCRAP_INGEST=on
ANTHROPIC_API_KEY=<your key>
SCRAP_BUDGET_DAY_USD=3
SCRAP_NOTIFY_URL=https://ntfy.sh/<your private topic>
SCRAP_PUBLIC_URL=https://<your address>
TZ=Europe/London
```

Ingest (Claude reading photos, tagging notes) is off until `SCRAP_INGEST=on` and an
`ANTHROPIC_API_KEY` are set. Set `TZ` to your own time zone: without it the server runs on UTC and
`due:today` follows the wrong day around midnight (the image carries the time zone database and
the CA certificates that Claude and notification calls need). Every setting, with its default, is
in the [API reference](../reference/api.md).

Keep the env file mode 600 and out of any repository. The key shows in plain text in
`docker inspect` and `podman inspect` for the container, so do not paste their output anywhere it
would be logged.

## Run one-off commands

The other subcommands run the same way, as a throwaway container on the same data. For example, a
backup into a second named volume (use the same `--user` or `--userns` options as above if you
use host directories instead):

```
docker run --rm -v scrap-data:/data -v scrap-backup:/backup \
    localhost/scrap:dev backup /backup
```

`backup` is safe while the service runs. `restore` into a non-empty data folder (`--force`) needs
the service stopped first. `gc` takes no directory, and only counts unless given `--delete`. The
rootless-podman specifics, `scrap restore` and `scrap gc` are in [](deploy-single-server.md). A
backup volume is a local copy only: copy it off the machine to survive losing it.

## Next

To run scrap as a service on one machine, with restarts, daily backups and Tailscale Serve, see
[](deploy-single-server.md); on Kubernetes, see [](deploy-kubernetes.md).
