# scrap Helm chart

Runs [scrap](https://github.com/gilesknap/scrap) on Kubernetes: one Deployment with exactly
**one replica** and the `Recreate` strategy (scrap's SQLite database has a single writer), a
PersistentVolumeClaim for `/data`, a ClusterIP Service (port 80, container port 8000) and a
ServiceAccount that mounts no token. On by default, a nightly backup CronJob with its own
PersistentVolumeClaim (`backup.enabled`), and a nightly `scrap gc` CronJob (`gc.enabled`, default: follows `backup.enabled`); with
ingest on, a nightly related-pages CronJob (`enrichRelated.enabled`) and a weekly topics CronJob
(`enrichTopics.enabled`) too. An Ingress and a NetworkPolicy are optional.

scrap has **no login** of its own: expose it only on a private network such as your tailnet, or
behind an authenticating proxy.

## Requirements

- Kubernetes 1.27 or newer, and Helm 3 or 4.
- A StorageClass that provides `ReadWriteOnce` volumes on a local or block filesystem. Do not use
  NFS or another network filesystem: SQLite's WAL mode needs reliable shared memory and locking.
- A private way in. The [Tailscale Kubernetes
  operator](https://tailscale.com/kb/1236/kubernetes-operator) is the recommended one.
- For photo ingest, a Claude API key in a Secret that you create (see below).

## Install

Releases publish the chart to `oci://ghcr.io/gilesknap/charts/scrap`, with the release tag as its
version (a pre-release such as `0.2.0rc1` as `0.2.0-rc.1`):

```
helm install scrap oci://ghcr.io/gilesknap/charts/scrap --version <release> \
  --namespace scrap --create-namespace -f my-values.yaml
```

From a checkout of this repository, or from Argo CD with a Git source, set `image.tag` to a release
too (a checkout's `appVersion` is the placeholder `0.0.0`, which has no image):

```
helm install scrap ./charts/scrap --namespace scrap --create-namespace -f my-values.yaml \
  --set image.tag=<release>
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
[values.yaml](values.yaml). `values.schema.json` rejects unknown top-level keys and unknown keys in
most groups, so a typo there fails the install instead of being ignored; `service`,
`networkPolicy`, `serviceAccount`, `resources` and the security contexts are not checked.

## Image

Releases publish a multi-arch (amd64 and arm64) image to `ghcr.io/gilesknap/scrap`, and
`image.tag` defaults to the chart's `appVersion`, which is set from the git tag when a release is
published to `oci://ghcr.io/gilesknap/charts/scrap`. A checkout has the placeholder `0.0.0`, with no
image: set `image.tag` to a release (or build your own and set `image.repository` too; see the guide).

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

## Public pages

Off by default. `public.enabled` runs the public site of the pages marked Public (issue 497)
from the `ghcr.io/gilesknap/scrap-public` image, in a namespace of its own (`public.namespace`,
default `scrap-public`, labelled Pod Security `restricted`; `public.createNamespace: false` if it
exists). One pod holds nginx, which serves the site read only, and an upload receiver that scrap
pushes the pages to. Only nginx gets an Ingress (`public.ingress`). A NetworkPolicy admits only
scrap's pods to the receiver and `public.networkPolicy.webFrom` (empty: anyone) to nginx, and
denies all egress. The site is an `emptyDir` (`public.sizeLimit`); scrap pushes it back after the
pod moves.

The upload token is a Secret you create, at least 32 characters, named by
`public.tokenSecret.name` and `.key`, in **both** namespaces (each pod reads only its own
namespace's Secrets). `public.site` is the site's base URL (`SCRAP_PUBLISH_SITE`). The install
fails without either. scrap then gets `SCRAP_PUBLISH_TO`, `SCRAP_PUBLISH_SITE` and
`SCRAP_PUBLISH_TOKEN`. Behind Cloudflare Access, the site's host needs its own Access application
with the Bypass action: a wildcard application covers every subdomain. See the guide.

## Operating

- Check it works without exposing it: `kubectl -n scrap port-forward svc/scrap 8000:80`, then
  `curl http://127.0.0.1:8000/healthz` (the install notes print this too).
- The data and backup claims are annotated `helm.sh/resource-policy: keep`, so `helm uninstall`
  leaves your data in place.
- The scheduled jobs (backup, monthly backup, gc, and with ingest on related pages and topics):
  turn one off with its `.enabled`, change it with `.schedule` and `.timeZone`, and check them
  with `kubectl -n scrap get cronjobs,jobs`. The
  [scheduled jobs table](https://gilesknap.github.io/scrap/main/reference/scheduled-jobs.html)
  has each one's schedule, what it does, its Claude budget and its values.
- The backup CronJob runs at `30 3 * * *` by default, keeps the newest 7 runs on a 20Gi claim and
  is a local copy only: copy it off the cluster as well. A monthly CronJob (`backup.monthly.*`,
  `50 3 1 * *`) adds a full copy on the 1st into the claim's `monthly/` folder and keeps the newest
  12, so a destructive change noticed after a week can still be undone.
- The gc CronJob purges a page that has been in the trash for more than `gc.trashDays` (default
  30), topic pages aside, with its captures and everything on them; its files then go as unused
  ones do. Nothing deletes a page before that. It also deletes finished job records older than
  `gc.jobDays` (default 30). The scrap pod shows each trashed page's purge date from
  `gc.trashDays` (`SCRAP_TRASH_DAYS`, `off` while gc does not delete). `kubectl -n scrap exec
  deploy/scrap -- scrap gc --report` prints what the store holds, by size.
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
For public pages it also checks that the token is never a plain value, no Ingress points at the
receiver, and the public NetworkPolicy exists and denies egress.
