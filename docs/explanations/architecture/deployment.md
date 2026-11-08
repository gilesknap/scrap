# Deployment and operations

scrap is one service over one data folder, run from the same container image either way:
systemd and rootless podman on a single server, or the Helm chart on Kubernetes, where the
database sits on the node's disk and Litestream replicates it into the data folder. On a single
server, scheduled work (backup, gc, enrichment) runs as systemd timers. On Kubernetes, backups are
CronJobs, and gc and the Claude passes run in a `jobs` container in the scrap pod. Step by step:
[](../../how-to/deploy-single-server.md), [](../../how-to/deploy-kubernetes.md).

Colours: blue is storage, orange is work that calls Claude, green is the person using scrap.

## Single server

systemd user units run one rootless podman container; Tailscale Serve is the only way in
([](../decisions/0016-deployment-single-server-and-helm.md),
[](../decisions/0018-unix-socket-for-single-server-installs.md)).

```mermaid
flowchart TD
    me(["Phone / browser"]):::user
    subgraph host["One unix user, rootless podman"]
        ts["Tailscale Serve"]
        subgraph units["systemd user units"]
            svc["scrap.service"]
            tb["backup timers<br/>daily + monthly"]
            tg["gc timer"]
            tr["enrich-related timer"]
            tt["enrich-topics timer"]
        end
        app["scrap container<br/>(serve)"]
        data[("SCRAP_DATA<br/>scrap.db + files/")]:::store
        bak[("SCRAP_BACKUPS<br/>timestamped runs + monthly/")]:::store
    end
    me -->|HTTPS, tailnet| ts
    ts -->|"Unix socket<br/>scrap.sock"| app
    svc -->|scrap-run| app
    app --- data
    tb -->|"scrap-backup<br/>(--network=none)"| bak
    tb -.->|reads| data
    tg -->|"scrap-gc<br/>(--network=none)"| data
    tr -->|"podman exec<br/>enrich --related"| app:::claude
    tt -->|"podman exec<br/>enrich --topics"| app
    classDef store fill:#e8f1ff,stroke:#4a7bd0
    classDef claude fill:#fff3e0,stroke:#e08a00
    classDef user fill:#e9f7ef,stroke:#2e9d5b
```

| Piece | What it does |
| --- | --- |
| `scrap.service` | `Type=notify`, restarts on failure. `scrap-run` starts the container with `--userns=keep-id` (uid 10001), a memory cap and a pids limit |
| Listener | `SCRAP_LISTEN=socket` publishes only `$XDG_RUNTIME_DIR/scrap/scrap.sock`; `tcp` (the default for an env file without the setting) publishes `127.0.0.1:$SCRAP_PORT` (8790) |
| Backup, gc | Separate throwaway containers with `--network=none`, sharing one `flock` on `SCRAP_BACKUPS/.lock` so they never overlap |
| Enrichment | `podman exec scrap scrap enrich ...` inside the running container, so it shares the app's API key, settings and daily budget; the units require `scrap.service` |
| Image | One multi-arch image (amd64 + arm64) from the release workflow |

Five timers, all `Persistent` except gc:

| Timer | When | Runs |
| --- | --- | --- |
| `scrap-backup` | daily 03:30 | backup, then retention |
| `scrap-backup-monthly` | 1st of the month 03:50 | backup into `monthly/`, keeping the newest 12 (`SCRAP_BACKUP_MONTHLY_KEEP`; 0 turns it off) |
| `scrap-enrich-related` | daily 03:41 | `enrich --related` |
| `scrap-enrich-topics` | Sundays 04:11 | `enrich --topics` |
| `scrap-gc` | daily 04:30 | `gc` (a missed night is skipped, not run at boot) |

Each has a 15 minute random delay. `install.sh` enables a timer only if the installed image has
its command, and says so when it does not.

## Kubernetes

The chart runs exactly one replica with the `Recreate` strategy, because SQLite has a single
writer ([](../decisions/0003-one-process-sqlite-and-a-folder.md)). The database is not on the
data volume: it is on an emptyDir on the node's disk, and Litestream replicates it into the data
volume, because SQLite's WAL is not safe on NFS or another network filesystem
([](../decisions/0046-database-on-an-emptydir-replicated-with-litestream.md)).

```mermaid
flowchart TD
    me(["Browser"]):::user
    subgraph edge["Edge (your choice)"]
        ing["Ingress<br/>Cloudflare Access or<br/>the DLS login proxy"]
    end
    subgraph ns["Release namespace"]
        np["NetworkPolicy<br/>(optional)"]
        svc["Service :80"]
        subgraph pod["scrap pod (1 replica, Recreate)"]
            init["init: litestream-tool,<br/>db-init"]
            app["scrap serve"]
            ls["litestream<br/>(native sidecar)"]
            jobs["jobs: scrap schedule<br/>gc 04:30, enrich-related 03:41,<br/>enrich-topics Sun 04:11"]
            db[("emptyDir /db<br/>scrap.db")]:::store
        end
        pvc[("Data volume /data<br/>files/ + litestream/")]:::store
        cb["Backup CronJobs<br/>03:30 + monthly 1st"]
        bk[("Backups<br/>timestamped runs + monthly/")]:::store
    end
    me --> ing --> np --> svc --> app
    init -->|"restore or place"| db
    app --- db
    app --- pvc
    ls -->|"replicates"| pvc
    jobs -.-> db
    jobs -.->|"gc needs recent<br/>COMPLETE"| bk
    cb -->|"restore of the replica<br/>+ files/"| bk
    cb -.-> pvc
    classDef store fill:#e8f1ff,stroke:#4a7bd0
    classDef claude fill:#fff3e0,stroke:#e08a00
    classDef user fill:#e9f7ef,stroke:#2e9d5b
```

- **Where the data is.** `/db/scrap.db` (`SCRAP_DB_PATH`) is on an emptyDir capped by
  `litestream.sizeLimit` (2Gi). `/data` keeps `files/`, the regenerable preview cache (never
  backed up) and the replica, `/data/litestream`. The data volume may be NFS.
- **Starting.** An init container copies the Litestream binary in; `scrap db-init` then keeps a
  database already on the emptyDir, takes up a staged restore, or restores the replica, and
  refuses to start when an install with history (a state file, files, backups) has no replica.
  Litestream runs as a native sidecar (Kubernetes 1.29 or newer), so it starts before scrap and
  stops after it.
- **What can be lost.** About a second of writes if the node dies; none on a clean stop. If
  replication stalls for 20 minutes, the `jobs` container's readiness probe fails and the pod
  leaves its Service, so scrap stops taking writes it could lose.
- **Scheduled work.** gc and, with ingest on, the related and topics passes run in the pod's
  `jobs` container (`scrap schedule`), on the live database. `scrap schedule status` (and opt-in
  Prometheus metrics) report each job's last run. The backups stay CronJobs: `scrap backup
  --from-replica` checks and backs up a restore of the replica with `/data/files`. They run on
  the scrap pod's node, as the data claim is `ReadWriteOnce`.
- **No login in scrap.** Reach it only through an authenticating proxy: Cloudflare Access, or
  the DLS login proxy (oauth2-proxy and Keycloak, the chart's `authProxy`), whose token scrap
  verifies. `identityHeader` names the header recorded as the author and `mcp.tokenSecret` can
  require a bearer token on `/mcp`
  ([](../decisions/0023-bearer-token-on-mcp-and-an-identity-header-setting.md),
  [](../decisions/0045-scrap-verifies-the-login-proxys-keycloak-token.md)).
- **Public pages** (optional, `public.enabled`) run in a pod of their own, nginx and the upload
  receiver from the `scrap-public` image; scrap pushes to the receiver and the public site never
  talks to scrap ([](../../reference/public-site.md)).
- **Secrets are never values.** The chart names an existing Secret for the API key, notify URL
  and MCP token and never creates one. The PVCs carry `helm.sh/resource-policy: keep`.
- **Hardening.** Restricted Pod Security: non-root uid 10001, read-only root filesystem, all
  capabilities dropped, `RuntimeDefault` seccomp.
- **Health.** `GET /healthz` returns 200 with `status`, `version`, `max_upload_bytes`, `paused`
  (why the Claude queue is paused, else null) and `publish` (the public site's state); 503 if
  the ingest worker has stopped. The pod is ready only while the `jobs` container sees
  replication working.

Settings are in [](../../reference/api.md); every chart value is in `charts/scrap/values.yaml`,
checked by `values.schema.json`.

## Data protection loop

Backup, retention, gc and restore form one loop, and gc will not delete unless the loop has
recently worked.

```mermaid
flowchart LR
    b["Backup<br/>SQLite online backup<br/>+ files/ copy"] --> v["Integrity check<br/>write COMPLETE"]
    v --> r["Retention<br/>keep newest N"]
    r --> g{"COMPLETE run<br/>under 26 h old?"}
    g -->|yes| d["gc --delete"]
    g -->|no| c["gc counts only,<br/>job fails loudly"]
    r -.-> x[("Backups<br/>newest N runs")]:::store
    x --> s["Restore"]
    s --> k{"Checks"}
    k -->|"integrity ok<br/>schema not newer"| ok["Swap in DB,<br/>add files"]
    k -->|"non-empty dir<br/>without --force"| no["Refused"]
    classDef store fill:#e8f1ff,stroke:#4a7bd0
```

- **Backup is safe while serving.** It snapshots the database first and copies `files/` second.
  Blobs are written before the transaction that names them, so the snapshot never names a missing
  file.
- **`COMPLETE` marks a good run.** Only a checked snapshot gets one; a failed run's directory is
  removed and older runs are untouched.
- **Retention** (`SCRAP_BACKUP_KEEP` on a single server, `backup.keep` in the chart; install.sh writes 14, the chart defaults to 7)
  deletes only directories named like a run (`20261019T033000Z`); symlinks and other files are
  never touched. Both add a monthly tier in `monthly/` (`backup.monthly` in Helm, `SCRAP_BACKUP_MONTHLY_KEEP` on a
  single server; newest 12) for changes noticed late.
- **gc follows backup.** It takes the same lock, so a file removed mid-backup cannot be one the
  backup's database names. Without a recent `COMPLETE` run it only counts and exits non-zero, so a
  missing backup shows up as a failed job.
- **On Kubernetes the backup reads the replica.** `scrap backup --from-replica` restores the
  replica to a temporary file and backs that up with `/data/files`. It refuses a replica whose
  heartbeat (stamped every 15 minutes by `scrap schedule`) is over 3 hours old, so a stalled
  replica fails the job rather than writing a `COMPLETE` run that gc would trust. gc there also
  only counts, and fails, when the files it would delete are over 10% of them and at least 5, or
  the database has no captures beside stored files (`--allow-large` after a person has looked),
  and after an override, until `scrap db-hold --clear`. For 14 days after a restore it only counts
  without failing; that hold ends by itself, or sooner with `scrap db-hold --clear`.
- **Restore** copies the backup database beside the live one and opens only the copy, so
  read-only media work. The copy must pass `integrity_check` and not be from a newer schema
  than the code; it is then migrated and swapped in. Files are only added. A refusal leaves the
  data folder as it was, and a non-empty folder needs `--force` with scrap stopped. On
  Kubernetes a restore is staged instead (`scrap restore --stage`): the next pod start takes it
  up in place of the replica.
- **A local copy is not an off-site copy.** Copy `SCRAP_BACKUPS` (or the backup volume) elsewhere.

## See also

- [](../design.md), the architecture landing page; [](data-model.md) for the database and
  files; [](mcp-and-access.md) for tokens and identity; [](claude-pipeline.md) for the Claude
  passes the schedules start.
- [](../../reference/scheduled-jobs.md) and [](../../reference/api.md) for commands and
  settings.
- How-to: [](../../how-to/deploy-single-server.md), [](../../how-to/deploy-kubernetes.md).
- ADRs: [](../decisions/0003-one-process-sqlite-and-a-folder.md),
  [](../decisions/0007-tailscale-serve-for-access-and-identity.md),
  [](../decisions/0016-deployment-single-server-and-helm.md),
  [](../decisions/0018-unix-socket-for-single-server-installs.md),
  [](../decisions/0021-ingest-on-a-claude-seat-through-claude-p.md),
  [](../decisions/0023-bearer-token-on-mcp-and-an-identity-header-setting.md),
  [](../decisions/0045-scrap-verifies-the-login-proxys-keycloak-token.md),
  [](../decisions/0046-database-on-an-emptydir-replicated-with-litestream.md).
