(scrap-ingest-seat)=
# Ingest on a Claude seat instead of an API key

By the end of this page scrap reads your photos, and tags and summarises your notes, through
your Claude seat rather than an API key. It is a change to an install you already have, not an
install of its own: do one of [](install-lan.md), [](install-server.md) or
[](install-kubernetes.md) first.

```{important}
**An API key is the encouraged default.** Use this page only if you have a Claude seat (Pro,
Max, Team or Enterprise) and no Claude Console account to make a key in. scrap runs the Claude
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
    https://raw.githubusercontent.com/gilesknap/scrap/0.2.2/Dockerfile.claude
podman build -f Dockerfile.claude --build-arg BASE=ghcr.io/gilesknap/scrap:0.2.2 \
    -t localhost/scrap-claude:0.2.2 .
podman run --rm --entrypoint claude localhost/scrap-claude:0.2.2 --version
```

The last command should print a Claude Code version. The image is about 240 MB larger than
scrap's. Build it again, with the new release as `BASE`, each time you update scrap.

On Kubernetes, build the same way, then tag the image for your own registry, push it, and set
`image.repository` and `image.tag` in your values to it.

## Get the token

On any machine where Claude Code is logged in to your seat, run:

```
claude setup-token
```

Copy only the token it prints: one line starting `sk-ant-oat01-`, not the line after it. Keep
it out of shell history, notes and anything you commit.

## Give scrap the token

Use the one section for your install.

### Container on a LAN, or single server

Edit the settings file (`~/.config/scrap/env` for the LAN tutorial, `~/.config/scrap/ingest.env`
as the `scrap` user for the server tutorial). It stays mode 600. Remove `ANTHROPIC_API_KEY` and
set:

```
SCRAP_INGEST=on
SCRAP_LLM_BACKEND=cli
CLAUDE_CODE_OAUTH_TOKEN=<your token>
```

`SCRAP_LLM_BACKEND` is `api` (the default) or `cli`. Then run the new image:

- LAN: remove the container and run it again with `localhost/scrap-claude:0.2.2` in place of
  `ghcr.io/gilesknap/scrap:0.2.2`; the volume keeps your data.
- Server: set `SCRAP_IMAGE=localhost/scrap-claude:0.2.2` in `~/.config/scrap/env`, then re-run
  `./deploy/install.sh`. The CLI takes about 250 MB while it runs, so raise `SCRAP_MEMORY_MAX`
  there too, for example to `1.5g`.

`podman inspect scrap` shows the container's environment, token included: do not paste it
anywhere.

### Kubernetes

The chart has no first-class option for the token, so pass it through `extraEnv`. The chart still
reads `ANTHROPIC_API_KEY` from `ingest.existingSecret` whenever ingest is on, so put an empty
one in the same Secret:

```
read -rs TOKEN && kubectl -n scrap create secret generic scrap-claude \
    --from-literal=ANTHROPIC_API_KEY= --from-literal=CLAUDE_CODE_OAUTH_TOKEN="$TOKEN"; unset TOKEN
```

If your registry needs credentials, create an image pull Secret and list it under
`imagePullSecrets` in the values. Add to your values, with your own image from the build section:

```yaml
image:
  repository: registry.example.com/me/scrap-claude
  tag: 0.2.2
ingest:
  enabled: true
  existingSecret: scrap-claude
extraEnv:
  - name: SCRAP_LLM_BACKEND
    value: cli
  - name: CLAUDE_CODE_OAUTH_TOKEN
    valueFrom:
      secretKeyRef:
        name: scrap-claude
        key: CLAUDE_CODE_OAUTH_TOKEN
```

Then `helm upgrade` as in the install. The nightly related-pages CronJob gets the same
environment. Raise `resources.limits.memory` if the pod is killed: the CLI takes about 250 MB.

## Check a photo is read

Capture a photo in the app. Within about a minute its page shows a kind, a description and tags
instead of waiting. If it does not, read scrap's log (`podman logs scrap`, `journalctl` or
`kubectl logs` as in your install). Without the token or the `claude` binary, ingest pauses with
reason `auth` until you press **Resume**, and the log says which is missing. Nothing is lost while
it is paused. A `401 ... invalid` means the token was copied wrongly: fix it, restart scrap, then
**Resume**.

`SCRAP_BUDGET_DAY_USD` still applies, to what the calls would cost at API prices, not to
anything you are charged. Set `SCRAP_ENRICH=off` to keep the seat to photos.

```{note}
**What has been checked.** The `Dockerfile.claude` build command and argument names were run on
23 Oct 2026 against `ghcr.io/gilesknap/scrap:0.2.2`, and the image's `claude --version` printed
2.1.281. The Helm values above were rendered with `helm template` and give the three environment
variables, the image and the CronJob settings shown; they have not been installed on a cluster.
Ingest on a seat reading two photos in about 10 seconds was checked by hand on 22 Oct 2026 on a
DLS workstation (see [](../how-to/run-on-dls-workstation.md)). The steps for the LAN and server
installs, and the empty `ANTHROPIC_API_KEY` Secret key, have not been run in full.
```
