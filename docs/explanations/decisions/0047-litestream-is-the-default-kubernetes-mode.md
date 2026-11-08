# 47. Litestream is the default Kubernetes mode

Date: 2026-11-08

## Status

Accepted

## Context

[ADR 46](0046-database-on-an-emptydir-replicated-with-litestream.md) put the database on an emptyDir,
replicated by Litestream to the data volume, behind `litestream.enabled`, off by default. The chart
then had two modes: the old one, with the database at `/data/scrap.db` on the data volume and gc and
the Claude passes as CronJobs, and the Litestream one, with those in the scrap pod's `jobs` container.

- The old mode needs a data volume on a local or block filesystem: SQLite's WAL is not safe on NFS.
  Clusters where NFS is all there is, such as DLS's argus (its only dynamic class is `netapp`), can
  run only the Litestream mode, and the DLS installer turns it on.
- The owner's home cluster already runs the Litestream mode.
- So every install we know of is on it, the old mode is the less tested of the two, and keeping both
  doubles what each chart change has to think about (the CronJobs, `gc.resources`, `enrich*.resources`,
  the backup jobs' two scripts).
- The Litestream mode works on any storage class, NFS or not.

## Decision

**`litestream.enabled` is `true` by default.** A new install gets the Litestream mode with no setting.

**The old mode is deprecated.** `litestream.enabled: false` keeps the database on the data volume; it
will be removed in a later release. Until then it renders as before, the chart's install notes say it
is deprecated, and `charts/test-chart.sh` keeps checking it (`ci/no-litestream-values.yaml`, and the
CronJob checks with `--set litestream.enabled=false`).

**The chart needs Kubernetes 1.29**, in either mode (`kubeVersion: ">=1.29.0-0"`, was 1.27). Litestream
runs as a native sidecar, which 1.29 has on by default. `_litestream.tpl`'s own check for 1.29 is
now never reached, as `kubeVersion` refuses first; it stays in case the minimum moves. The minimum is the chart's, not the mode's, so the old mode is no reason to stay on an older cluster.

**An existing install moves by itself.** A release that never set `litestream.enabled` gets the
Litestream mode on its next `helm upgrade`, and `scrap db-init` brings `/data/scrap.db` across on the
first start (ADR 46, rule 4).

**The old gc and Claude-pass CronJobs become suspended stubs.** In the Litestream mode the chart
renders `<fullname>-gc`, `-enrich-related` and `-enrich-topics` under the same names with
`suspend: true`, running only `true` and mounting nothing (`templates/old-mode-cronjobs.yaml`). Simply
dropping them would rely on the upgrade deleting them, and Argo CD without pruning does not: the old
CronJob would keep its old image and spec. From a chart of 1.6.0 or older its gc has no guard
against the old file, so it would `scrap gc --delete` on `/data/scrap.db` and delete the files only
the new database uses. Rendered under the same names, helm and Argo CD update them to the suspended
stubs instead. They are for upgrades from the old mode and go in a later release, with it.

**`scrap enrich` refuses the old file** as `scrap gc` and `scrap serve` already did
(`refuse_old_database`): run without `SCRAP_DB_PATH` on a data folder with Litestream's state file,
it stops before writing anything.

## Consequences

- **Upgrading from the old mode** (below) is a plain `helm upgrade` once three things are checked: a
  backup, Kubernetes 1.29, and a database under half of `litestream.sizeLimit`. To put it off, set
  `litestream.enabled: false` before the upgrade, not after.
- A cluster older than 1.29 cannot install or upgrade the chart in either mode: `helm` refuses on
  `kubeVersion`.
- Values that are valid only for CronJobs are refused once Litestream is on: a `gc.schedule`,
  `enrichRelated.schedule` or `enrichTopics.schedule` of `@every ...` or with signed numbers (the
  schema and `scrap db-init`'s schedule check). An empty `timeZone` now means UTC, not the
  controller's zone. `gc.resources` and `enrich*.resources` are no longer used:
  `litestream.jobs.resources` covers them all.
- The scrap pod is bigger: requests grow by 100m CPU and 320Mi memory (the `jobs` container and the
  Litestream sidecar), memory limits by 2.25Gi, and it has a 2Gi emptyDir for the database. A
  namespace's ResourceQuota or LimitRange (`ephemeral-storage` included) must have room.
- The scrap pod mounts the backups (claim or `backup.persistence.hostPath`) as well as the data claim.
  The backup jobs already ran beside it with both, so an install whose backups worked is placed the
  same way; but a namespace under the baseline or restricted Pod Security Standard now stops the scrap
  pod, not only the backup jobs, if the backups are a `hostPath`.
- Failures of gc and the Claude passes are in the `jobs` container's log and `scrap schedule status`,
  not failed Jobs (ADR 46).
- When the old mode is removed, the chart loses the gc and Claude-pass CronJob templates and their
  suspended stubs, the
  `gc.resources` and `enrich*.resources` values, and the backup jobs' direct-from-the-database path.
  `scrap db-init`'s rule 4 (bringing `/data/scrap.db` across) stays for as long as installs may still
  upgrade from it.

### Upgrading from the old mode

What happens, for a release that never set `litestream.enabled`, on the first `helm upgrade` to a
chart with this default:

1. The CronJobs `<fullname>-gc`, `<fullname>-enrich-related` and `<fullname>-enrich-topics` (the
   last two exist only with ingest on) are replaced by suspended stubs of the same names, by helm
   and by Argo CD with or without pruning. Suspending starts no new Job but does not stop one already running.
   The two backup CronJobs stay, changed to back up from a restore of the replica, with the data
   claim read only.
2. The Deployment's old pod stops before the new one starts (`Recreate`), so `/data/scrap.db` is
   closed when it is copied.
3. In the new pod, `db-init` finds no database on the emptyDir, no staged restore, no replica and no
   state file (an old-mode install has none), and a `/data/scrap.db` with pages. It copies that with
   SQLite's backup API, WAL included, checks its integrity, moves it to `/db/scrap.db`, and writes
   `/data/.scrap-db-state.json` with the old file's size and modified time. It refuses, starting
   nothing, if the database and its WAL are over half of `litestream.sizeLimit`. The checks that
   refuse an empty start when there are files or backup runs come after this rule, so they do not
   stop an upgrade.
4. The Litestream sidecar starts and makes the replica in `/data/litestream` within about a second;
   then scrap and the `jobs` container start. Nothing is lost: the copy is of the closed file.
5. `/data/scrap.db` is left where it is, as the copy from before. Each later start checks it is
   unchanged: if anything writes to it, the pod stops in `db-init`, saying it has changed since the
   replica began.

If the pod dies in the second between step 3 and Litestream's first write, the next start refuses
(a state file but no replica) and needs `litestream.init.override: true` once, after a look.

The steps:

1. **Check Kubernetes** is 1.29 or newer: `kubectl version`.
2. **Check the values.** No `@every` or signed numbers in `gc.schedule`, `enrichRelated.schedule` or
   `enrichTopics.schedule`; room in any ResourceQuota or LimitRange for the bigger pod; with
   `backup.persistence.hostPath`, a namespace that allows `hostPath` volumes.
3. **Check the database's size**:
   `kubectl -n scrap exec deploy/scrap -- ls -l /data/scrap.db /data/scrap.db-wal` (there may be no
   `-wal`). The two together must be at most half of `litestream.sizeLimit`: 1 GiB (1073741824
   bytes) at the default 2Gi. If not, set `litestream.sizeLimit` to over twice that, with room to
   grow, on nodes with that much free disk.
4. **Back up**, and wait for it:
   `kubectl -n scrap create job --from=cronjob/scrap-backup scrap-backup-pre-litestream`, then
   `kubectl -n scrap wait --for=condition=complete job/scrap-backup-pre-litestream --timeout=30m`.
5. **Pick a quiet moment**: `kubectl -n scrap get jobs` shows none running. By default they start
   between 03:30 and 04:30 (topics at 04:11 on Sundays), and related pages can run for hours. A gc
   or Claude pass running then is killed, and an old Job still writing `/data/scrap.db` after the
   copy stops the next start.
6. **Upgrade**: `helm upgrade` as usual, or an Argo CD sync. Then check the three old CronJobs show
   `SUSPEND True`: `kubectl -n scrap get cronjob scrap-gc scrap-enrich-related scrap-enrich-topics`.
   Never leave one running its old job: delete any that is not suspended (a sync that skipped it).
   An old one left running keeps its old image: from a chart of 1.6.0 or older its gc deletes the
   files the new database added, and any old Claude pass writes to `/data/scrap.db`, which stops the
   next start.
7. **Check**: `kubectl -n scrap logs deploy/scrap -c db-init` says it `brought /data/scrap.db across to
   /db/scrap.db, and left it there`; `kubectl -n scrap exec deploy/scrap -c jobs -- scrap schedule
   status` lists the jobs; and a backup from the replica completes:
   `kubectl -n scrap create job --from=cronjob/scrap-backup scrap-backup-post-litestream`.
8. **Later**, once you are happy, delete `/data/scrap.db` and any `/data/scrap.db-wal` and
   `/data/scrap.db-shm` (from a one-off pod, or the `jobs` container). Until then it must not change.

To stay on the old mode for now, set `litestream.enabled: false` in your values **before** upgrading;
the install notes then say it is deprecated. `helm upgrade --reuse-values` from a 1.7 or 1.8 release
does the same without being asked: it reuses the old chart's defaults, `enabled: false` among them,
and the notes say DEPRECATED. If `db-init` refuses the database as too big, nothing has changed yet
(the size is checked before anything is copied or the state file written), so setting
`enabled: false` then is safe too. Turning it off after a start with Litestream does not
bring the database back (`/data/scrap.db` is the old copy): scrap and gc refuse to start on it while
the state file is there, and the way off is a backup and `scrap restore --force`
([Deploy on Kubernetes](../../how-to/deploy-kubernetes.md), its Litestream section). A `helm rollback` to the release before the upgrade is therefore no way back
either: scrap refuses to start, harmlessly, but with ingest on its Claude-pass CronJobs come back and
write to the old file. Never roll back to a chart older than 1.7.0, which has no such guard and would
serve the old file while its gc deletes the files only the newer database uses.
