# Deploy on Kubernetes

Run scrap on a Kubernetes cluster (k3s, a home lab, a cloud cluster) with the Helm chart in
[`charts/scrap`](https://github.com/gilesknap/scrap/tree/main/charts/scrap). It runs the same
container image as the [single-server deployment](deploy-single-server.md): one pod, a persistent
volume for the data and, by default, a nightly backup job.

```{warning}
v0 of scrap has **no login**. Anyone who can reach its Service can read and change everything.
Expose it only on your tailnet (see {ref}`k8s-tailscale`) or behind an authenticating proxy
(see {ref}`k8s-ingress`), never directly to the internet. Inside the cluster, any pod that can
reach the Service has full access too, and can send its own `Tailscale-User-Login` header: turn
on the NetworkPolicy (below) if other workloads share the cluster.
```

## What you get

| Object | Notes |
| --- | --- |
| Deployment | Exactly **one replica**, strategy `Recreate`. scrap keeps everything in one SQLite database with a single writer, so the chart has no `replicas` value: the old pod always stops before the new one starts. |
| PersistentVolumeClaim | `/data`: the database, files and the preview cache. Kept on `helm uninstall`. |
| Service | `ClusterIP`, port 80. |
| ServiceAccount | No API token mounted; scrap never talks to the Kubernetes API. |
| CronJob + PVC (on by default) | Nightly `scrap backup` to a second claim, keeping the newest 7 runs. |
| Ingress, NetworkPolicy (off by default) | See below. |

The pod meets the `restricted` [Pod Security Standard](https://kubernetes.io/docs/concepts/security/pod-security-standards/):
it runs as uid/gid 10001, with a read-only root filesystem (only `/data` and an `emptyDir` at
`/tmp` are writable), no capabilities, no privilege escalation and the `RuntimeDefault` seccomp
profile.

## Prerequisites

- Kubernetes 1.27 or newer, and Helm 3 or 4.
- A StorageClass that provides `ReadWriteOnce` volumes on a **local or block** filesystem (see
  {ref}`k8s-storage`).
- A way in that is not the open internet: the
  [Tailscale Kubernetes operator](https://tailscale.com/kb/1236/kubernetes-operator) is the
  recommended one.
- For ingest: a Claude API key.

## Get the image

Releases publish a multi-arch (amd64 and arm64) image to `ghcr.io/gilesknap/scrap`, and the
chart's `appVersion` names the release it was made with. Until the first release exists, build
and push an image to a registry your cluster can pull from, and point the chart at it:

```
podman build --platform linux/amd64,linux/arm64 --manifest registry.example.com/scrap:dev .
podman manifest push registry.example.com/scrap:dev
```

```yaml
image:
  repository: registry.example.com/scrap
  tag: dev
  pullPolicy: Always
imagePullSecrets:
  - name: my-registry-credentials   # if the registry needs a login
```

Building the arm64 half on an x86 machine needs `qemu-user-static`; on a mixed cluster you can
instead pin scrap to nodes of one architecture with `nodeSelector: {kubernetes.io/arch: amd64}`
and build only that.

## Install

From a checkout of the repository:

```
kubectl create namespace scrap
helm install scrap ./charts/scrap --namespace scrap -f my-values.yaml
kubectl -n scrap rollout status deploy/scrap
```

Check it without exposing it anywhere:

```
kubectl -n scrap port-forward svc/scrap 8000:80
curl http://127.0.0.1:8000/healthz
```

and open <http://127.0.0.1:8000/> for the PWA. The PWA installs and works offline only over HTTPS
(or on `localhost`), so use one of the exposures below for a phone.

## Values

Every value is described in
[`values.yaml`](https://github.com/gilesknap/scrap/blob/main/charts/scrap/values.yaml); unknown
keys are refused, so a typo fails the install instead of being ignored. The main ones:

| Value | Default | Meaning |
| --- | --- | --- |
| `image.repository`, `image.tag` | `ghcr.io/gilesknap/scrap`, the chart's `appVersion` | Image to run. |
| `maxUploadMB` | `50` | `SCRAP_MAX_UPLOAD_MB`: largest capture. Raise a proxy's body limit to match. |
| `ingest.enabled` | `false` | `SCRAP_INGEST`: send photos to Claude (see {ref}`k8s-ingest`). |
| `ingest.visionModel`, `ingest.budgetDayUSD` | app defaults | `SCRAP_VISION_MODEL`, `SCRAP_BUDGET_DAY_USD`. |
| `persistence.size`, `.storageClass`, `.existingClaim` | `5Gi`, default class, none | The data volume. |
| `backup.enabled`, `.schedule`, `.timeZone`, `.keep` | `true`, `30 3 * * *`, UTC, `7` | The backup CronJob. |
| `backup.persistence.size` | `20Gi` | Each run is a full copy: allow about `keep + 1` times the data. |
| `resources.limits.memory` | `1Gi` | scrap's photo decoding is budgeted for a 1 GB container; a lower limit risks the pod being OOM-killed on large photos. |
| `ingress.*`, `service.annotations` | off | Exposure, below. |
| `networkPolicy.enabled`, `.from` | off | Who may connect, below. |
| `extraEnv`, `extraEnvFrom` | none | Anything else for the container. |
| `nodeSelector`, `tolerations`, `affinity`, `podAnnotations` | none | Scheduling and annotations. |

The settings themselves are in the [API reference](../reference/api.md). The chart sets
`SCRAP_DATA_DIR=/data`; `SCRAP_WEB_DIR` (for trying out a PWA build) has no value of its own,
use `extraEnv`.

Set `TZ` the same way, to your own time zone: the server decides what "today" means for
`due:today` searches from its own clock (UTC by default), while the PWA uses the phone's date.

```yaml
extraEnv:
  - name: TZ
    value: Europe/London
```

The preview cache (`cache/previews` under `/data`) stays on the data volume: it is regenerable and
never backed up, and keeping it saves redoing every preview after a restart, which is slow on
small ARM nodes.

(k8s-ingest)=
## Secrets and ingest

The chart never takes the API key as a value and never creates a Secret: it only reads a Secret
you create. Create it from a file or stdin so the key stays out of your shell history and out of
any values file:

```
read -rs KEY && printf %s "$KEY" | kubectl -n scrap create secret generic scrap-secrets \
    --from-file=ANTHROPIC_API_KEY=/dev/stdin; unset KEY
```

Optionally add the notification URL (an ntfy topic URL is itself a secret) to the same Secret
under another key, e.g. `SCRAP_NOTIFY_URL`. Then:

```yaml
ingest:
  enabled: true
  existingSecret: scrap-secrets
  apiKeyKey: ANTHROPIC_API_KEY     # the default
  notifyUrlKey: SCRAP_NOTIFY_URL   # optional
```

With GitOps, create the Secret with whatever your cluster uses for secrets (Sealed Secrets,
External Secrets, SOPS) under the same name; never commit the key. A changed Secret is not picked
up by a running pod: `kubectl -n scrap rollout restart deploy/scrap`.

## Exposure

(k8s-tailscale)=
### Tailscale Kubernetes operator (recommended)

With the [Tailscale Kubernetes operator](https://tailscale.com/kb/1236/kubernetes-operator)
installed, an Ingress of class `tailscale` publishes scrap over HTTPS on your tailnet only, with a
MagicDNS name and a Let's Encrypt certificate
([cluster ingress](https://tailscale.com/kb/1439/kubernetes-operator-cluster-ingress),
[L7 ingress how-to](https://tailscale.com/docs/kubernetes-operator/ingress/expose-workload-to-tailnet-l7)).
Your tailnet needs MagicDNS and [HTTPS certificates](https://tailscale.com/kb/1153/enabling-https)
enabled.

```yaml
ingress:
  enabled: true
  className: tailscale
  tls:
    - hosts:
        - scrap          # becomes https://scrap.<tailnet>.ts.net
```

The operator's proxy accepts traffic through Tailscale Serve
([architecture](https://tailscale.com/docs/kubernetes-operator/concepts/architecture)). Never add
the Funnel annotation: that publishes scrap to the internet.

The alternative, the Service annotation `tailscale.com/expose: "true"` (with
`tailscale.com/hostname`), forwards plain TCP: there is no HTTPS, so the PWA cannot install or
work offline, and there are no identity headers. Use the Ingress.

**Identity headers.** scrap records the `Tailscale-User-Login` header as the author of each change.
Tailscale Serve sets it, and strips any value the client sent, for requests from user-owned
devices, and sets none for tagged devices. The operator's documentation does not say whether its
Ingress proxy does the same. Its proxy configures Serve through the same local API, and in
Tailscale's source the Serve reverse proxy adds the headers to every proxied request
([`ipn/ipnlocal/serve.go`](https://github.com/tailscale/tailscale/blob/main/ipn/ipnlocal/serve.go),
`addTailscaleIdentityHeaders`), so they are expected to arrive, but this is **not yet verified**
end to end. To check on your cluster: make a change from a phone or laptop through the Ingress,
then look at the page's history (or `GET /api/pages/<id>`): your tailnet login should be its
author, not the fixed fallback author. If it is not, every change is recorded under the fallback
author; nothing else breaks.

Because a pod inside the cluster can send its own `Tailscale-User-Login` header straight to the
Service, let only the operator's proxies in (they run in the operator's namespace, `tailscale` by
default):

```yaml
networkPolicy:
  enabled: true
  from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: tailscale
```

A NetworkPolicy needs a CNI that enforces it (k3s's built-in controller does). Whether kubelet
probes still get through depends on the CNI; if the pod never becomes ready after turning the
policy on, check that first.

#### Tailnet ACL: deny tagged devices by default

The operator's proxies are tagged devices (`tag:k8s` by default). As for the single server, use a
tailnet policy that lets your own devices reach them and gives other tagged devices (servers, CI,
anything unattended) no access unless you grant it:

```json
"grants": [
  {"src": ["autogroup:member"], "dst": ["tag:k8s"], "ip": ["tcp:443"]}
]
```

(k8s-ingress)=
### Any other ingress controller

scrap has no login, so put an authenticating proxy in front: for example
[oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/) through your controller's external
auth annotations, or your SSO's forward-auth middleware. Raise the controller's request body
limit to at least `maxUploadMB`.

```yaml
ingress:
  enabled: true
  className: <your-ingress-class>
  annotations:
    # Your controller's annotations for external authentication and for a
    # request body limit of at least maxUploadMB; see its documentation.
    <auth-annotation>: <auth-service-url>
    <body-size-annotation>: 50m
  hosts:
    - scrap.example.com
  tls:
    - hosts:
        - scrap.example.com
      secretName: scrap-tls
```

The annotation names differ for every controller (Traefik uses Middleware objects instead), so
the chart takes them as plain `ingress.annotations`. Make sure the proxy removes any `Tailscale-User-*` headers sent by clients; changes are then
recorded under the fixed fallback author. Never expose the Service without authentication.

### Port-forward

For a quick try, `kubectl -n scrap port-forward svc/scrap 8000:80`. Nothing is exposed beyond your own machine.

## Upgrades

Back up first, then change the image (or update the chart and its `appVersion`):

```
kubectl -n scrap create job --from=cronjob/scrap-backup scrap-backup-pre-upgrade
kubectl -n scrap wait --for=condition=complete job/scrap-backup-pre-upgrade --timeout=30m
helm upgrade scrap ./charts/scrap -n scrap -f my-values.yaml --set image.tag=<new>
```

The old pod stops before the new one starts (`Recreate`), so there is a short outage; the PWA
queues captures meanwhile. A clean stop gives any ingest job in flight back to the queue. scrap
runs its database migrations at startup, before it answers `/healthz`: the startup probe allows
them five minutes.

Migrations are **forward only**, and an older scrap refuses a database migrated by a newer one.
So `helm rollback` alone does not go back: roll back to the old image *and* restore the
pre-upgrade backup with `--force` (below). Anything captured since the upgrade is then lost from
the database; its files stay. The one exception is migration 0004 (Markdown-aware search
text), which changes no schema: to go back past it, stop scrap and run
`sqlite3 scrap.db 'PRAGMA user_version = 3'` on its data folder instead of restoring.

## Backup and restore

The CronJob runs `scrap backup` into a new timestamped directory on the backup claim
(`/backups/20261019T033000Z`), then keeps only the newest `backup.keep` runs, using the same
rules as the single-server deployment: `keep` must be a whole number of at least 1 (the chart
refuses anything else), and only real directories named like a run are ever deleted; anything
else on the volume, including symlinks, is left alone. A failed run removes only its own
directory. `scrap backup` is safe while scrap is serving. The job runs on the same node as the
scrap pod (pod affinity), because the data volume is `ReadWriteOnce`; while scrap is scaled to
zero, a run waits and gives up after an hour.

Backups are on by default because the data is personal and irreplaceable; set
`backup.enabled: false` if you back up the data volume another way (volume snapshots, Longhorn
or Velero backups). Either way the backup claim lives in the same cluster: copy it somewhere
else too.

Run one now and list the runs:

```
kubectl -n scrap create job --from=cronjob/scrap-backup scrap-backup-now
kubectl -n scrap logs -f job/scrap-backup-now
```

To restore, stop scrap (and anything that would restart it), then run `scrap restore` in a
one-off pod with both claims mounted:

```
kubectl -n scrap patch cronjob scrap-backup -p '{"spec":{"suspend":true}}'
kubectl -n scrap scale deploy/scrap --replicas=0
kubectl -n scrap wait --for=delete pod -l app.kubernetes.io/name=scrap --timeout=2m
kubectl -n scrap apply -f restore.yaml
kubectl -n scrap logs -f pod/scrap-restore
kubectl -n scrap delete pod scrap-restore
kubectl -n scrap scale deploy/scrap --replicas=1
kubectl -n scrap patch cronjob scrap-backup -p '{"spec":{"suspend":false}}'
```

With Argo CD or another GitOps controller, pause its automatic sync first, or it scales scrap
straight back up. `restore.yaml`, with the run to restore, the image of the scrap version you
want and, for a non-empty data volume, `--force` (which replaces the whole database; see
`scrap restore --help`):

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: scrap-restore
spec:
  restartPolicy: Never
  securityContext:
    runAsNonRoot: true
    runAsUser: 10001
    runAsGroup: 10001
    fsGroup: 10001
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: restore
      image: ghcr.io/gilesknap/scrap:<version>
      args: ["restore", "/backups/<run>", "--force"]
      env:
        - name: SCRAP_DATA_DIR
          value: /data
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop: [ALL]
      volumeMounts:
        - {name: data, mountPath: /data}
        - {name: backups, mountPath: /backups}
        - {name: tmp, mountPath: /tmp}
  volumes:
    - name: data
      persistentVolumeClaim:
        claimName: scrap-data
    - name: backups
      persistentVolumeClaim:
        claimName: scrap-backups
    - name: tmp
      emptyDir: {}
```

The claim names are `<fullname>-data` and `<fullname>-backups`, where the fullname is the
release name if it contains `scrap`, else `<release>-scrap`: `kubectl -n scrap get pvc` shows
them. The backups claim must be mounted writable: a backup's database is in SQLite's WAL mode,
and `scrap restore` cannot open it in a read-only directory. The same pod with other arguments
runs any `scrap` command against the data, for example `["export", "/backups/export"]` (pruning
only ever deletes directories named like a backup run, so an export there is kept). To restore into a fresh volume instead, create a new claim,
restore into it without `--force`, and point `persistence.existingClaim` at it.

## Health and monitoring

`/healthz` answers 200 with the version while scrap is well. It answers 503 when the ingest
worker thread has died; the liveness probe then restarts the pod, which is intended (the
readiness probe takes it out of the Service first). Logs: `kubectl -n scrap logs deploy/scrap`.
Ingest pauses (budget spent, credit, auth) are reported once per episode to `SCRAP_NOTIFY_URL`
if set, and are visible at `GET /api/ingest`. The backup CronJob's failed jobs stay listed
(`kubectl -n scrap get jobs`); alert on them with whatever watches your cluster.

(k8s-storage)=
## k3s and storage notes

- k3s's default `local-path` provisioner keeps the volume in a directory on one node and pins
  the pod to that node: if the node is down, scrap is down. That is fine for a home cluster; move
  the data with a backup and restore.
- `local-path` does not apply `fsGroup`; its directories are world-writable, so uid 10001 can
  still write. On other storage the chart's `fsGroup: 10001` makes the volume writable.
- Do **not** put the data on NFS or another network filesystem: SQLite's WAL mode needs shared
  memory and locking that network filesystems do not provide reliably. Block storage (Longhorn,
  a cloud disk) is fine. `ReadWriteOncePod` volumes would keep the backup job out; use
  `ReadWriteOnce`.
- Mixed arm64 and amd64 nodes (e.g. ARM boards and an x86 mini PC) need no settings: the image is
  multi-arch. Use `nodeSelector` only to choose where the data lives.

## Argo CD

A generic Application that installs the chart from this repository (replace the placeholders,
and pin `targetRevision` to a release tag):

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: scrap
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/gilesknap/scrap.git
    targetRevision: <release-tag>
    path: charts/scrap
    helm:
      valuesObject:
        ingress:
          enabled: true
          className: tailscale
          tls:
            - hosts: [scrap]
        ingest:
          enabled: true
          existingSecret: scrap-secrets
  destination:
    server: https://kubernetes.default.svc
    namespace: scrap
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

Both claims carry two annotations by default, and keep them if you set your own
`persistence.annotations` or `backup.persistence.annotations`:

- `helm.sh/resource-policy: keep`: `helm uninstall` leaves the claim, and Argo CD treats it as
  `Delete=false`, so deleting the Application leaves it too
  ([Argo CD and Helm](https://argo-cd.readthedocs.io/en/stable/user-guide/helm/)).
- `argocd.argoproj.io/sync-options: Prune=false`: with `prune: true`, Argo CD deletes any
  object that drops out of the rendered chart, which is what a claim does when you switch to
  `persistence.existingClaim` or set `backup.enabled: false`. This annotation stops that
  ([sync options](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/)); Helm
  ignores it. Delete a claim you no longer need by hand.

Also use a StorageClass (or set the PV) with the `Retain` reclaim policy: k3s's `local-path`
defaults to `Delete`, so a deleted claim takes the data with it.

## What the chart does not do

- Run more than one replica, or any high availability: SQLite has a single writer.
- Create Secrets, take the API key as a value, or log in users.
- Expose scrap to the internet, or add authentication.
- Copy backups off the cluster.
- Restrict egress (ingest needs `api.anthropic.com`; notifications need your notify URL).
- Publish a Helm repository or OCI chart: install from a checkout or a Git source.
