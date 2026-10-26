# 3. One process, one SQLite database, one folder of files

Date: 2026-10-19 (recorded retrospectively; the design landed in the first commits)

## Status

Accepted

## Context

scrap replaces a much larger earlier system (a git-synced vault, a chat-bot daemon, several
paid-API integrations). It has one user, and its goals are to be tiny, readable in an afternoon, and
built from off-the-shelf parts. The store has to survive a phone, a worker thread and an API all
writing to it.

## Decision

- One Python process (FastAPI) serves the PWA, the JSON API and the MCP server. If a feature needs a
  second service, it waits. A separate ingest worker is deferred.
- Storage is SQLite in WAL mode plus a `files/` folder of content-addressed blobs
  (`files/<sha[0:2]>/<sha>`), on one persistent volume. A photo shared twice is stored once.
- Every connection sets `foreign_keys = ON` and `busy_timeout = 5000` on open, outside a
  transaction: the search index stays correct only because deletes cascade.
- IDs are ULIDs (safe to mint on the phone); times are ISO 8601 UTC. Slugs are made from titles and
  are stable once fixed.
- Migrations are numbered SQL files (`0001_init.sql` ...) run under a lock by the store.
- Backup is a SQLite online backup plus a copy of `files/`; restore is a CLI command.

## Consequences

- One writer: the deployments must run exactly one replica with a `Recreate` strategy (see
  [](0016-deployment-single-server-and-helm.md)).
- No horizontal scaling and no Postgres. Postgres/pgvector is an open question only if SQLite is
  outgrown.
- Writes that mix slow work and the database follow one pattern: do the slow thing holding no lock,
  then a short `BEGIN IMMEDIATE` to re-read and write.
- The data folder also holds a disposable cache beside `scrap.db` and `files/`: JPEG previews of
  stored photos, made on first request under `cache/previews/<size>/<sha[0:2]>/<sha>.jpg`
  (`preview.py`). Any of it can be deleted and is made again. The backup does not include it, and
  `scrap gc` removes a deleted file's previews (sizes 480 and 2048) with it. Originals are never
  changed by it.
