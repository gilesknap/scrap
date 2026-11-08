(scrap-ingest-seat)=
# Ingest on a Claude seat instead of an API key

By the end of this page scrap reads your photos, and tags and summarises your notes, through
your Claude seat rather than an API key. It is a change to an install you already have, not an
install of its own: do [](install-kubernetes.md) first. It also works on a single server
([](install-server.md)) or a trial on your LAN ([](install-lan.md)).

Not for the DLS install ([](install-dls.md)) yet: its installer has no seat option, and a
`helm upgrade` with your own values would replace the installer's settings.

```{important}
**An API key is the encouraged default.** Use this page only if you have a Claude seat (Team or
Enterprise) and no Claude Console account to make a key in. scrap runs the Claude
Code CLI (`claude -p`) with a long-lived token from `claude setup-token`
([ADR 0021](../explanations/decisions/0021-ingest-on-a-claude-seat-through-claude-p.md)). Use
your own seat only. Whether your plan or organisation lets a seat be used for unattended work
is its own policy: check it with your Claude admin first. These docs cannot promise it is
allowed.
```

The token is a credential for your **whole seat**, with no spend cap, until it expires or you
revoke it. Calls count against your seat's usage limits, shared with your own use of Claude;
when a limit is hit, ingest pauses until it resets. Every Claude call in scrap takes this
route, photos and text enrichment alike.

```{warning}
A published `-claude` image is planned. Until then, **you build it yourself**: the next section
does it, from the release image you already run.
```

## Build the image with the Claude CLI

`Dockerfile.claude` adds only the CLI's native binary (pinned, and checked against its SHA-256)
on top of a scrap image. It is from the release you run, so fetch it in an empty folder:

```
mkdir -p ~/scrap-claude-build && cd ~/scrap-claude-build
curl -fsSL -o Dockerfile.claude \
    https://raw.githubusercontent.com/gilesknap/scrap/{{ release_tag }}/Dockerfile.claude
podman build -f Dockerfile.claude --build-arg BASE=ghcr.io/gilesknap/scrap:{{ release_tag }} \
    -t localhost/scrap-claude:{{ release_tag }} .
podman run --rm --entrypoint claude localhost/scrap-claude:{{ release_tag }} --version
```

The last command should print a Claude Code version. The image is about 240 MB larger than
scrap's. Build it again, with the new release as `BASE`, each time you update scrap.

On Kubernetes, build the same way, then tag the image for your own registry and push it; the
Kubernetes section below sets your values to it.

## Get the token

On any machine where Claude Code is logged in to your seat, run:

```
claude setup-token
```

Copy only the token it prints: one line starting `sk-ant-oat01-`, not the line after it. Keep
it out of shell history, notes and anything you commit.

## Give scrap the token

Use the one section for your install.

### Kubernetes

The chart has no first-class option for the token, so pass it through `extraEnv`. The chart still
reads `ANTHROPIC_API_KEY` from `ingest.existingSecret` whenever ingest is on, so put an empty
one in the same Secret:

```
read -rs TOKEN && printf %s "$TOKEN" | kubectl -n scrap create secret generic scrap-claude \
    --from-literal=ANTHROPIC_API_KEY= --from-file=CLAUDE_CODE_OAUTH_TOKEN=/dev/stdin; unset TOKEN
```

The token goes in on standard input, so it is not on `kubectl`'s command line.

If you set `ingest.notifyUrlKey`, add that key to `scrap-claude` too: the chart reads it from
`ingest.existingSecret`.

If your registry needs credentials, create an image pull Secret and list it under
`imagePullSecrets` in the values. Then edit your values file (`my-values.yaml` from the
tutorial, which holds all your settings) to match this, with your own image from the build
section: add `image`, change `ingest.existingSecret`, and add the two entries to the `extraEnv`
list already there, keeping `SCRAP_PUBLIC_URL`. Do not repeat a key, and do not put these in a
second values file: one would replace the whole `extraEnv` list.

```yaml
image:
  repository: registry.example.com/me/scrap-claude
  tag: {{ release_tag }}
ingest:
  enabled: true
  existingSecret: scrap-claude
extraEnv:
  - name: SCRAP_PUBLIC_URL
    value: https://scrap.example.com
  - name: SCRAP_LLM_BACKEND
    value: cli
  - name: CLAUDE_CODE_OAUTH_TOKEN
    valueFrom:
      secretKeyRef:
        name: scrap-claude
        key: CLAUDE_CODE_OAUTH_TOKEN
```

Then upgrade with the whole file, so nothing you set before is lost:

```
helm upgrade scrap oci://ghcr.io/gilesknap/charts/scrap --version {{ chart_version }} \
    -n scrap -f my-values.yaml
```

The pod's `jobs` container, which runs the nightly related-pages and weekly topics passes, gets
the same environment. The CLI takes about 250 MB while it runs: if a container is killed for
memory, raise `resources.limits.memory` (the web app) or `litestream.jobs.resources.limits.memory`
(the `jobs` container).

### On a single server, or a trial on your LAN

`SCRAP_LLM_BACKEND` is `api` (the default) or `cli`. Set it with the token and drop
`ANTHROPIC_API_KEY`:

- LAN: read the token into your shell the way the README reads the key, then remove the container
  and run it again with the new image (the volume keeps your data):

  ```
  printf 'Claude token: '; read -rs CLAUDE_CODE_OAUTH_TOKEN; export CLAUDE_CODE_OAUTH_TOKEN
  podman rm -f scrap   # only if you started it with --name scrap
  podman run -d --name scrap --restart unless-stopped --network=host -v scrap-data:/data \
      -e SCRAP_INGEST=on -e SCRAP_LLM_BACKEND=cli -e CLAUDE_CODE_OAUTH_TOKEN \
      localhost/scrap-claude:{{ release_tag }} serve
  ```

  Add `--host 0.0.0.0`, `TZ` and `SCRAP_PUBLIC_URL` from [](install-lan.md) if you used them.
- Server: in `~/.config/scrap/ingest.env` (mode 600) set:

  ```
  SCRAP_INGEST=on
  SCRAP_LLM_BACKEND=cli
  CLAUDE_CODE_OAUTH_TOKEN=<your token>
  ```

  Set `SCRAP_IMAGE=localhost/scrap-claude:{{ release_tag }}` in `~/.config/scrap/env` and re-run
  `./deploy/install.sh`. The CLI takes about 250 MB while it runs, so raise `SCRAP_MEMORY_MAX`
  there too, for example to `1.5g`.

`podman inspect scrap` shows the container's environment, token included: do not paste it
anywhere.

## Check a photo is read

Capture a photo in the app. Within about a minute its page shows a kind, a description and tags
instead of waiting. If it does not, read scrap's log
(`kubectl -n scrap logs deploy/scrap -c scrap`; on a single server or LAN, `podman logs scrap` or
`journalctl` as in your install). Without the token or the `claude` binary, ingest pauses with
reason `auth` until you press **Resume**, and the log says which is missing. Nothing is lost while
it is paused. A `401 ... invalid` means the token was copied wrongly: fix it, restart scrap, then
**Resume**.

`SCRAP_BUDGET_DAY_USD` still applies, to what the calls would cost at API prices, not to
anything you are charged. Set `SCRAP_ENRICH=off` to keep the seat to photos.
