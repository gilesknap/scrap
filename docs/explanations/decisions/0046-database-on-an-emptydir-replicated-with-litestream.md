# 46. The database on an emptyDir, replicated with Litestream

Date: 2026-11-05

## Status

Accepted. Opt-in when made; now the chart's default, and the old mode deprecated, by
[ADR 47](0047-litestream-is-the-default-kubernetes-mode.md).

## Context

scrap keeps SQLite in WAL mode. On DLS's argus cluster the only dynamic storage is `netapp`, which
is NFS, and the [storage notes](../../how-to/deploy-kubernetes.md) say never to put the database
on NFS: WAL needs shared memory and locking a network filesystem does not provide reliably. The
owner decided that the database moves off NFS rather than testing whether it copes there. This
ADR does not claim to explain any past hang: none was traced to NFS.

Block storage, which the storage notes recommend, is not an option here: the argus admins removed
it a while back for security reasons, and `netapp` is the only dynamic class, so it was not pursued.

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
4. No replica but a `/data/scrap.db` with pages (an install from before this; an empty one counts
   as absent): brought across once with SQLite's backup API (it may have a WAL), checked, left
   where it is.
5. Neither: a new database, unless something says there should be one.

**Telling "really new" from "looks empty because something is wrong".** A new volume with no
history looks exactly like a replaced or mistakenly empty one from inside the volume, so the
evidence has to include something that outlives it. `db-init` fails closed on any of:

- `.scrap-db-state.json` on the data volume, written the first time a database is put in place
  (`how` and `at`; a later restore of the replica leaves those and sets `replica_restored_at`),
  with no replica beside it. So the replica cannot vanish unnoticed, and a stale `/data/scrap.db`
  cannot come back by rule 4. This also fires if the pod dies between the first placement and
  Litestream's first write, about a second; it costs a person a look, not data.
- Files in `files/`.
- Backup runs (daily or monthly) in the backup folder, which is on other storage (at DLS,
  `/dls/science`): the one signal that notices a new, empty data volume.

And any error looking is a failure, not "absent": `os.stat`, not `Path.exists()`, which from Python
3.12 answers `False` on a stale NFS handle. It cannot catch everything: a data volume and backup
folder both new and empty really is a new install, and with backups off only the first two apply.
`litestream.init.override` gets past these refusals, for after a person has looked. Each use is
recorded (`override_at`), and gc only counts until a person clears it (`scrap db-hold --clear`), so
leaving it on cannot make a later loss of the replica silent. A source over half of
`litestream.sizeLimit` is refused regardless, as the WAL and Litestream's own LTX share that emptyDir.

**Off Litestream.** With the setting off, or a `helm rollback` to a chart that has it off,
`/data/scrap.db` is the copy from before, and gc would delete files only the newer database uses. So
while the state file exists and `SCRAP_DB_PATH` is unset, the app and `scrap gc` refuse. A plain
`scrap restore` removes the state file: that is the way off. Installs that never used Litestream have
no state file and are not affected. A rollback to a chart from before this code cannot be guarded,
and the how-to warns of it.

**Restoring a backup.** The old steps wrote `/data/scrap.db`, which the replica would then silently
win over. So `scrap restore --stage` leaves the checked, migrated backup at `/data/scrap.db.restored`,
which outranks the replica; the replica is renamed `litestream.retired-<time>`, not deleted, and
Litestream starts a new one. Guards: a plain `scrap restore` is refused where
`SCRAP_LITESTREAM_REPLICA` is set (inside the pod), `--stage` where `SCRAP_DB_PATH` exists, and
`--stage` on a folder with no sign of Litestream, where nothing would take it up. A `/data/scrap.db`
whose size or modified time differ from the state file stops the start, saying the replica may be
the newer copy. A staged restore beside a live emptyDir database stops the pod until it is scaled to
0, and one older than any replica file (scrap kept running after it) is refused, naming how to choose.
A retired replica can bring back rows by hand, never files: files added since the backup are
unreferenced after a restore, so gc only counts for 14 days afterwards, or until cleared.

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

**Writes must not be accepted while replication is broken, then rolled back at the next start.**
Litestream that cannot write logs `monitor error` and stays up. Nightly backups would notice hours
later, and everything since would go at the next restart. So the jobs container looks each minute for
a new file under the replica: a working one has one within about 15 minutes, from the stamp alone. At
20 minutes (`watch.py`; nothing is judged until 20 minutes after it starts, so a start cannot flap)
it logs, notifies and removes the file its readiness probe wants young, so the pod leaves its Service.
It recovers by itself. It also notes each stamp on the data volume, with a last one at shutdown. The
next start compares: behind is a warning (a node that died, or a last sync that did not land, which
nothing else can detect: Litestream's only sign of that is a log line in a container that has gone);
over 30 minutes behind is a refusal. The note is on the same volume, so a whole volume failing does
not show here, only as the stall.

**gc's safety limit is the backstop** for what all that misses, since deleted originals cannot come
back. On a Litestream install `gc --delete` counts only, and fails, when the database has no captures
but `files/` has content, or when the files to delete are over `MAX_UNUSED_SHARE` (10 %) of them and
at least `MIN_UNUSED` (5). Low on purpose: a healthy night deletes few, a false alarm costs one
`--allow-large` by hand, and a miss deletes originals. It cannot catch a small rollback, whose few
files fall under it; that is what the state holds are for.

**gc and the Claude passes must see the live database, so they move into the pod.** A `jobs`
container runs `scrap schedule`, on the existing image with no new dependency: a few hundred lines
of cron (`cron.py`, following robfig/cron v3 as a CronJob's schedule is read, but refusing `@every`
and signed numbers, and stopping the rollout on a bad one) and threads (`schedule.py`). The same values set the
same schedules and deadlines. It is close to a CronJob, not the same: an overlapping run is skipped,
and after a gap one run stands for those missed, if one is within the hour, as with
`concurrencyPolicy: Forbid` and `startingDeadlineSeconds: 3600`; but an empty
`timeZone` is UTC rather than the controller's zone; a time missed during a rollout is not made up
and a rollout stops a running pass, as there is deliberately no state to resume from; the jobs share
one set of resources, not one each; and there is no Job object to look at afterwards. gc's script is the same one, shared through a Helm template, so it
still takes the backup lock, checks for a `COMPLETE` run under 26 hours old and otherwise only
counts and fails. So the backup volume is mounted in the scrap pod.

**Not fighting Litestream.** scrap never checkpoints or sets `wal_autocheckpoint`,
`locking_mode` or `synchronous`; its one `journal_mode = WAL` is what Litestream needs; it sets the
`busy_timeout = 5000` Litestream's docs ask for; a test checks all of that. SQLite's automatic passive
checkpoint stays: Litestream's docs recommend turning it off only at very high write rates, and
Litestream's read lock holds it back anyway. A restart of Litestream alone, with writes during the
gap, caught up with no loss on the cluster.

**Shutdown and probes.** Litestream is a native sidecar (an init container with `restartPolicy:
Always`, Kubernetes 1.29), so it starts before scrap and stops after it, and scrap's last writes
reach it. Its final sync has up to 25 s, and `terminationGracePeriodSeconds` grows by 30. Probes are
unchanged: init containers run before the startup probe counts, so a slow restore cannot fail it,
and readiness still means `/healthz`.

## Consequences

- **What can be lost.** Replication is asynchronous: while it is healthy, about a second of writes
  if the node dies. While it has stalled, up to the 20 minutes before scrap leaves its Service. A
  clean stop loses none. Files are written straight to NFS, so the file of a lost capture stays
  until gc removes it.
- **Backup jobs still run beside the scrap pod.** It was hoped they would not need to. They do on
  argus: the data claim is `ReadWriteOnce`, and a pod on another node, even mounting it read only,
  waits with `FailedAttachVolume: Waiting for detach ... Volume is already used by pod(s)` (seen on
  the cluster). The affinity stays. A new `ReadWriteMany` claim (`netapp` offers it) might allow
  dropping it, but `accessModes` cannot change on an existing claim, and that was not tried.
- A failed gc or Claude pass no longer shows as a failed Job: it is in the `jobs` container's log,
  and pushed to `SCRAP_NOTIFY_URL` if set. Since #558 each run is also recorded in the database
  (table `scheduled_job`, so it survives the pod), and `scrap schedule status` (a probe: it exits 1 on
  a failed or stale job, or a backup over 26 hours old) and opt-in Prometheus metrics served by the
  scheduler report it, with the newest `COMPLETE` backup. A pass stopped by a queue pause or a spent budget is not
  reported as failed: it says so on stderr, and `scrap schedule` reads that last line.
- A restart of `litestream` or `jobs` that keeps failing takes the pod out of its Service. For both
  that is right: `jobs` is what watches replication, so with it down nothing does.
- The scrap pod now needs the backup folder mounted: a `hostPath` that a node lacks, or an RWO
  backup claim on another node, keeps the pod from starting.
- The database must fit half of `litestream.sizeLimit` (2 Gi), and at DLS a backup's restored copy
  must fit the 2 Gi per container argus allows. Past that the start is refused or the backup fails.
  `jobs` has a `/tmp` of its own, so a job cannot fill scrap's.
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
death, the backups on a `hostPath`, `install-dls.sh` itself, and a database of real size. The rule
that keeps a database on the emptyDir has only unit tests: a killed container does not rerun the
init container, and a pod restarting on its node with its emptyDir could not be forced. The override
was tried, starting a fresh database past a refusal.
