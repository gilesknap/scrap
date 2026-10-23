# scrap Helm chart

Runs [scrap](https://github.com/gilesknap/scrap) on Kubernetes: one Deployment with exactly
**one replica** and the `Recreate` strategy (scrap's SQLite database has a single writer), a
PersistentVolumeClaim for `/data`, a ClusterIP Service (port 80, container port 8000) and a
ServiceAccount that mounts no token. On by default, a nightly backup CronJob with its own
PersistentVolumeClaim (`backup.enabled`). An Ingress and a NetworkPolicy are optional.

scrap v0 has **no login**: expose it only on a private network such as your tailnet, or behind an
authenticating proxy.

## Requirements

- Kubernetes 1.27 or newer, and Helm 3 or 4.
- A StorageClass that provides `ReadWriteOnce` volumes on a local or block filesystem. Do not use
  NFS or another network filesystem: SQLite's WAL mode needs reliable shared memory and locking.
- A private way in. The [Tailscale Kubernetes
  operator](https://tailscale.com/kb/1236/kubernetes-operator) is the recommended one.
- For photo ingest, a Claude API key in a Secret that you create (see below).

## Install

There is no published chart (no Helm repository or OCI chart): install from a checkout of this
repository, or from Argo CD with a Git source.

```
helm install scrap ./charts/scrap --namespace scrap --create-namespace -f my-values.yaml
```

A minimal `my-values.yaml` that exposes scrap on your tailnet with the Tailscale operator:

```yaml
ingress:
  enabled: true
  className: tailscale
  tls:
    - hosts:
        - scrap          # https://scrap.<tailnet>.ts.net
```

The files in [ci/](ci/) (`*-values.yaml`) are further example value sets. Values are described in
[values.yaml](values.yaml), and `values.schema.json` rejects unknown keys, so a typo fails the
install instead of being ignored.

## Image

Releases publish a multi-arch (amd64 and arm64) image to `ghcr.io/gilesknap/scrap`, and
`image.tag` defaults to the chart's `appVersion`. Until the first release no image with that tag
exists: build and push your own and set `image.repository` and `image.tag` (see the guide).

## Exposure

Use an Ingress with `className: tailscale` as above, or an authenticating proxy. Never add the
Tailscale Funnel annotation: it publishes scrap to the internet. scrap records the
`Tailscale-User-Login` header as the author of each change and falls back to `tagged` when it is
absent; whether the operator's Ingress proxy sends it is not yet verified (see the guide). Any pod
that can reach the Service can send its own value. Set `networkPolicy.enabled` and
`networkPolicy.from` (for example the operator's namespace) to restrict who in the cluster can
connect; an empty `from` admits nobody.

## Secrets and ingest

The chart never creates a Secret and never takes the API key as a value. To turn on ingest, create
a Secret yourself, then set `ingest.enabled` and `ingest.existingSecret` (`ingest.apiKeyKey` names the key in it
and defaults to `ANTHROPIC_API_KEY`; `ingest.notifyUrlKey`, `ingest.visionModel` and `ingest.budgetDayUSD` are
optional). The install fails if `ingest.enabled` is set without `ingest.existingSecret`, and an
`ingest.apiKey` value is rejected as an unknown key. Enabling ingest sets `SCRAP_INGEST=on`, which
also turns on Claude enrichment of text pages.

`/mcp` can require a bearer token: create a Secret yourself and set `mcp.tokenSecret.name` (and
`mcp.tokenSecret.key`, default `SCRAP_MCP_TOKEN`); a token given as a value is rejected. Set
`identityHeader` to the header your authenticating proxy sends for the user (it defaults to
`Tailscale-User-Login`).

## Operating

- Check it works without exposing it: `kubectl -n scrap port-forward svc/scrap 8000:80`, then
  `curl http://127.0.0.1:8000/healthz` (the install notes print this too).
- The data and backup claims are annotated `helm.sh/resource-policy: keep`, so `helm uninstall`
  leaves your data in place.
- The backup CronJob runs at `30 3 * * *` by default, keeps the newest 7 runs on a 20Gi claim and
  is a local copy only: copy it off the cluster as well.
- Database migrations are forward only, so rolling back to an older version also needs a restore
  of the database.

The full guide (secrets, exposure with the Tailscale operator, upgrades, backup and restore,
Argo CD) is [Deploy on Kubernetes](https://gilesknap.github.io/scrap/main/how-to/deploy-kubernetes.html),
in the repository as `docs/how-to/deploy-kubernetes.md`.

## Checks

`./charts/test-chart.sh` needs `helm` and `kubeconform`, and CI runs it against Helm 3 and Helm 4.
It lints the chart, renders every value set in `ci/`, validates the output with kubeconform
(Kubernetes 1.30.0 and 1.36.5 by default; override with `K8S_VERSIONS`) and asserts that no Secret
or ConfigMap is rendered, there is one replica with `Recreate`, names fit the Kubernetes limits,
bad values are refused, and every environment variable the chart sets is a documented app setting.
