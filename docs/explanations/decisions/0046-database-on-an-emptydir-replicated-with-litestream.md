# 46. The database on an emptyDir, replicated with Litestream

Date: 2026-11-05

## Status

Accepted. Opt-in (`litestream.enabled`, off by default); the DLS installer turns it on. With it off
the chart renders exactly as before.

## Context

scrap keeps SQLite in WAL mode. On DLS's argus cluster the only dynamic storage is `netapp`, which
is NFS, and the [storage notes](../../how-to/deploy-kubernetes.md) say never to put the database
on NFS: WAL needs shared memory and locking a network filesystem does not provide reliably. The
owner decided that the database moves off NFS rather than testing whether it copes there. This
ADR does not claim to explain any past hang: none was traced to NFS.

## Decision

**The shape.** The database is at `/db/scrap.db` (`SCRAP_DB_PATH`) on an emptyDir on the node's
disk (not `medium: Memory`; argus's is a local xfs, seen on the cluster). A Litestream sidecar
replicates it to `/data/litestream` on the data volume. `files/` and the preview cache stay on the
data volume. With `SCRAP_DB_PATH` unset nothing changes: `Store` builds `dir / "scrap.db"`, as
before. The lock, WAL and `scrap restore`'s `scrap.db.restore` follow the database, so its rename
never crosses filesystems. `gc.lock` stays in the data folder, on NFS, as it does today.

**The version: Litestream 0.5.18, by tag and digest.** The 0.5 line is the maintained one (the
docs call 0.3.14 "previous"); its restore checks LTX files and fails on a damaged one, seen below,
and it has what is used here: `shutdown-sync-timeout`, `snapshot`, and a file replica whose renames
are fsynced (0.5.16). 0.5.18 rather than the two-month-old 0.5.17, despite being two days old when
chosen, for its fixes on this path: "read the whole WAL when the last-page check fails", "keep read
lock alive after caller context is cancelled" and "cache LTX pages for checkpoint verification";
and it is the version the trial below ran. Moving it is a decision: read the release notes, and
repeat the trial's restore steps.

**Two images.** The sidecar is Litestream's own image, not a binary added to scrap's, so nobody
with `litestream.enabled` off carries it. An init container copies its static binary into a small
emptyDir, so the Python below can call it. The Debian image (`0.5.18`, not `-scratch`) has the
`cp` and `sh` this needs. The chart still makes no ConfigMap: the sidecar writes its config at start.

**Starting up: `scrap db-init`, in an init container, so the logic can be unit tested.** The first
that applies decides:

1. A database on the emptyDir is kept (the pod restarted on its node), never overwritten.
2. A staged restore is taken up (below), and the replica renamed aside.
3. A replica is restored. No `-if-replica-exists`: if the restore or the integrity and schema
   check fails, the init container fails and scrap does not start. A retry can work.
4. No replica but a `/data/scrap.db` (an install from before this): brought across once with
   SQLite's backup API (it may have a WAL), checked, left where it is.
5. Neither: a new database, unless something says there should be one.

**Telling "really new" from "looks empty because something is wrong".** A new volume with no
history looks exactly like a replaced or mistakenly empty one from inside the volume, so the
evidence has to include something that outlives it. `db-init` fails closed on any of:

- `.scrap-db-state.json` on the data volume, written the first time a database is put in place,
  with no replica beside it. So the replica cannot vanish unnoticed, and a stale `/data/scrap.db`
  cannot come back by rule 4. This also fires if the pod dies between the first placement and
  Litestream's first write, about a second; it costs a person a look, not data.
- Files in `files/`.
- Backup runs (daily or monthly) in the backup folder, which is on other storage (at DLS,
  `/dls/science`): the one signal that notices a new, empty data volume.

And any error looking is a failure, not "absent": `os.stat`, not `Path.exists()`, which from Python
3.12 answers `False` on a stale NFS handle. It cannot catch everything: a data volume and backup
folder both new and empty really is a new install, and with backups off only the first two apply.
`litestream.init.override` gets past these refusals, for after a person has looked.

**Restoring a backup.** The old steps wrote `/data/scrap.db`, which the replica would then silently
win over. So `scrap restore --stage` leaves the checked, migrated backup at `/data/scrap.db.restored`,
which outranks the replica; the replica is renamed `litestream.retired-<time>`, not deleted, and
Litestream starts a new one. Three guards for someone on the old steps: a plain `scrap restore` is
refused where `SCRAP_LITESTREAM_REPLICA` is set (inside the pod); a `/data/scrap.db` whose size or
modified time differ from those recorded in the state file stops the start, naming the rename that
keeps it; and a staged restore beside a live emptyDir database stops the pod, until it is scaled to 0.

**Backups stay CronJobs and work from the replica.** `scrap backup --from-replica` restores to a
temporary file, then runs the existing `backup()` on that plus `/data/files`: same integrity check
and `COMPLETE` marker, both jobs. The data volume is mounted read only. The restore is at or
behind the live database and blobs are written before the row that names them, so the files it
names are there, but for a gc in the last second, and gc and backups share a lock and run an hour
apart.

**A stale replica must not make a good-looking backup,** because gc trusts `COMPLETE`. Idle
databases write nothing: Litestream's files do not change, and a snapshot is skipped when nothing
changed (seen locally), so file times prove nothing. So `scrap schedule` stamps the time in the
database header (`PRAGMA application_id`, unused and needing no schema change) every 15 minutes,
and the backup refuses a restore whose stamp is over 3 hours old. If Litestream is failing, or the
jobs container, the backup fails loudly and then gc only counts.

**gc and the Claude passes must see the live database, so they move into the pod.** A `jobs`
container runs `scrap schedule`, on the existing image with no new dependency: about a hundred
lines of five-field cron (`cron.py`, with names, steps and `@daily`) and threads. The same values
set the same schedules, time zones and deadlines, and an overlapping run is skipped, as
`concurrencyPolicy: Forbid` did. gc's script is the same one, shared through a Helm template, so it
still takes the backup lock, checks for a `COMPLETE` run under 26 hours old and otherwise only
counts and fails. So the backup volume is mounted in the scrap pod.

**Not fighting Litestream.** scrap never checkpoints or sets `wal_autocheckpoint`,
`locking_mode` or `synchronous`; its one `journal_mode = WAL` is what Litestream needs; it sets the
`busy_timeout = 5000` Litestream's docs ask for; a test keeps it that way. SQLite's automatic passive
checkpoint stays: Litestream's docs recommend turning it off only at very high write rates, and
Litestream's read lock holds it back anyway. A restart of Litestream alone, with writes during the
gap, caught up with no loss on the cluster.

**Shutdown and probes.** Litestream is a native sidecar (an init container with `restartPolicy:
Always`, Kubernetes 1.29), so it starts before scrap and stops after it, and scrap's last writes
reach it. Its final sync has up to 25 s, and `terminationGracePeriodSeconds` grows by 30. Probes are
unchanged: init containers run before the startup probe counts, so a slow restore cannot fail it,
and readiness still means `/healthz`.

## Consequences

- **What can be lost.** Replication is asynchronous: about a second of writes if the node dies. A
  clean stop loses none. Files are written straight to NFS, so the file of a lost capture stays
  until gc removes it.
- **Backup jobs still run beside the scrap pod.** It was hoped they would not need to. They do on
  argus: the data claim is `ReadWriteOnce`, and a pod on another node, even mounting it read only,
  waits with `FailedAttachVolume: Waiting for detach ... Volume is already used by pod(s)` (seen on
  the cluster). The affinity stays. A new `ReadWriteMany` claim (`netapp` offers it) might allow
  dropping it, but `accessModes` cannot change on an existing claim, and that was not tried.
- A failed gc or Claude pass no longer shows as a failed Job: it is in the `jobs` container's log,
  and pushed to `SCRAP_NOTIFY_URL` if set. A time missed while the pod is down is not made up.
- A restart of `litestream` or `jobs` that keeps failing takes the pod out of its Service. For
  Litestream that is arguably right: scrap would otherwise accept writes it cannot protect.
- The scrap pod now needs the backup folder mounted: a `hostPath` that a node lacks, or an RWO
  backup claim on another node, keeps the pod from starting.
- The database must fit `litestream.sizeLimit` (2 Gi), and at DLS a backup's restored copy must fit
  the 2 Gi per container argus allows. Past that the pod is evicted, or the backup fails.
- As with SQLite on any RWO volume, one writer relies on `Recreate` and the attach check; two
  Litestreams replicating into one place can corrupt it.
- Turning it off again does not bring the database back: `/data/scrap.db` is the old one. Take a
  backup, turn it off, and `scrap restore --force` it (see the how-to).

**Tested** on argus on 2026-11-05, with Litestream 0.5.18 from Docker Hub, in a throwaway release,
as the DLS uid, and this branch's Python laid over the 1.6.0 image with `PYTHONPATH` (there is no
published image with it yet). Writes reached the replica; a deleted pod came back on another node
with its data, including a write just before the delete; truncated LTX files and a missing replica
each failed the init container, and scrap did not start; a `/data/scrap.db` with a `-wal` came across
once; both backup jobs made `COMPLETE` runs; a staged restore of one came up with its file, without
the later write; a plain restore was caught; a stale stamp failed a backup; gc ran in the pod, by
hand and on its schedule, and refused to delete with no backup. Not tried there: the Claude passes
doing real work (no API key: only that `scrap enrich --related` runs in the container), a real node
death, the backups on a `hostPath`, `install-dls.sh` itself, and a database of real size. The
override and rule 1 have only unit tests.
