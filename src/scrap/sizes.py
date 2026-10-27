"""``scrap gc --report``: what the store holds, by size (#276). Read only.

It measures what retention would act on, so its defaults can be judged on real data:

- the database by table, with its indexes (``dbstat``; estimated from the columns'
  lengths where SQLite is built without it);
- the stored files, as gc sees them: in use by a page not in the trash (or by nothing
  page-bound: a Claude result's photo, a run's JPEG), used only by trashed pages, and
  unused (each with count and bytes);
- the trash: how many pages, how old, and how many a purge after N days would take;
- the Claude call records (``model_run``, ``enrich_run``, ``topic_run``) by month:
  rows and the bytes of their stored request, response and output;
- the job rows by state, and how many are finished and older than N days.

Counts and sizes only, never any page text. The database is opened read only.
"""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import retention
from .gc import COLUMNS, GcError, _files, in_use
from .store import Store, body_refs
from .store.roles import REVIEW

__all__ = ["measure", "text"]

RUNS = ("model_run", "enrich_run", "topic_run")
AGES = ((7, "under 7 days"), (30, "7-30 days"), (90, "30-90 days"))  # then older
# The captures (and so their files, results, jobs and runs) of pages in the trash
TRASHED_CAPTURE = (
    "(SELECT c.id FROM capture c JOIN page p ON p.id = c.page_id"
    " WHERE p.deleted_at IS NOT NULL)"
)
LIVE = (  # the references of everything not in the trash: gc.COLUMNS, narrowed
    "SELECT sha256 FROM capture_blob WHERE capture_id NOT IN " + TRASHED_CAPTURE,
    "SELECT source_sha256 FROM derived WHERE capture_id NOT IN " + TRASHED_CAPTURE,
    "SELECT source_sha256 FROM job WHERE capture_id NOT IN " + TRASHED_CAPTURE,
    "SELECT source_sha256 FROM model_run WHERE capture_id NOT IN " + TRASHED_CAPTURE,
    "SELECT sent_sha256 FROM model_run WHERE sent_sha256 IS NOT NULL"
    " AND capture_id NOT IN " + TRASHED_CAPTURE,
)
assert len(LIVE) == len(COLUMNS)  # keep in step with gc's references


def _open(db: Path) -> sqlite3.Connection:
    if not db.is_file():
        raise GcError(f"no database at {db}")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, isolation_level=None)
    conn.execute("PRAGMA query_only = ON")
    return conn


def _tables(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Each table's rows and bytes with its indexes, the biggest first; an FTS index's
    shadow tables under the index's name."""
    names = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    owner = {n: n for n in names}
    virtual = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND sql LIKE 'CREATE VIRTUAL TABLE%'"
        )
    ]
    for v in virtual:  # chunk_fts_data, _idx...: chunk_fts's
        for n in names:
            if n.startswith(f"{v}_"):
                owner[n] = v
    for name, table in conn.execute(
        "SELECT name, tbl_name FROM sqlite_master WHERE type = 'index'"
    ):
        owner[name] = owner.get(table, table)
    sizes: dict[str, int] = {}
    estimated = False
    try:
        for name, size in conn.execute(
            "SELECT name, sum(pgsize) FROM dbstat GROUP BY name"
        ):
            key = owner.get(name, name)
            sizes[key] = sizes.get(key, 0) + size
    except sqlite3.OperationalError:  # no dbstat: the columns' lengths, roughly
        estimated = True
        for n in names:
            if n in virtual:
                continue
            cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{n}")')]
            total = " + ".join(
                f'coalesce(length(CAST("{c}" AS BLOB)), 8)' for c in cols
            )
            row = conn.execute(f'SELECT sum({total}) FROM "{n}"').fetchone()
            key = owner.get(n, n)
            sizes[key] = sizes.get(key, 0) + (row[0] or 0)
    out = []
    for n in names:
        if owner[n] != n:
            continue
        rows = None if n in virtual else conn.execute(f'SELECT count(*) FROM "{n}"')
        out.append(
            {
                "table": n,
                "rows": rows.fetchone()[0] if rows else None,
                "bytes": sizes.get(n, 0),
                "estimated": estimated,
            }
        )
    listed = {t["table"] for t in out}
    for name in sorted(set(sizes) - listed):  # sqlite_schema, sqlite_stat1...
        out.append({"table": name, "rows": None, "bytes": sizes[name],
                    "estimated": estimated})  # fmt: skip
    out.sort(key=lambda t: (-t["bytes"], t["table"]))
    return out


def _live(conn: sqlite3.Connection) -> set[str]:
    used: set[str] = set()
    for sql in LIVE:
        used.update(row[0] for row in conn.execute(sql))
    for (body,) in conn.execute("SELECT body FROM page WHERE deleted_at IS NULL"):
        used |= body_refs(body)
    return used


def _review_only(conn: sqlite3.Connection) -> set[str]:
    """The files gc's review pages in the trash showed (in any revision) that no page
    out of the trash shows: a purge of those pages lets them go (scrap.retention),
    if they are orphans then (roughly: the capture holding them is still counted)."""
    review = REVIEW.format(p="p")
    shown: set[str] = set()
    for (body,) in conn.execute(
        "SELECT r.body FROM page_rev r JOIN page p ON p.id = r.page_id"
        f" WHERE p.deleted_at IS NOT NULL AND {review}"
    ):
        shown |= body_refs(body)
    for (body,) in conn.execute("SELECT body FROM page WHERE deleted_at IS NULL"):
        shown -= body_refs(body)
    return shown


def _files_split(store: Store, conn: sqlite3.Connection) -> dict[str, Any]:
    """The stored files by use: in use (not only by the trash), used only by pages in
    the trash, held only for review pages in the trash (see _review_only), and
    unused: each {files, bytes}."""
    try:
        files, _ = _files(store)
    except (GcError, OSError):
        files = {}
    rows = dict(conn.execute("SELECT sha256, size FROM blob"))
    every = in_use(conn)
    live = _live(conn)
    review = _review_only(conn)
    kinds = ("in_use", "review_only", "trash_only", "unused")
    out: dict[str, Any] = {k: {"files": 0, "bytes": 0} for k in kinds}
    for sha, path in files.items():
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            continue
        key = (
            "trash_only" if sha in every and sha not in live
            else "unused" if sha not in every
            else "review_only" if sha in review
            else "in_use"
        )  # fmt: skip
        out[key]["files"] += 1
        out[key]["bytes"] += size
    out["missing"] = sum(1 for sha in rows if sha not in files)  # rows with no file
    return out


def _age(stamp: str, today: datetime) -> float:
    try:
        return (today - datetime.fromisoformat(stamp)).total_seconds() / 86400
    except ValueError:
        return 0.0


def _trash(conn: sqlite3.Connection, trash_days: float | None) -> dict[str, Any]:
    today = datetime.now(UTC)
    rows = conn.execute(
        "SELECT p.deleted_at, EXISTS (SELECT 1 FROM topic t WHERE t.page_id = p.id)"
        " FROM page p WHERE p.deleted_at IS NOT NULL ORDER BY p.deleted_at"
    ).fetchall()
    ages = [_age(r[0], today) for r in rows]
    bands = {label: 0 for _, label in AGES} | {"older": 0}
    for age in ages:
        label = next((lab for d, lab in AGES if age < d), "older")
        bands[label] += 1
    due = (
        0
        if trash_days is None
        else len(retention.due(conn, retention.stamp(trash_days)))
    )
    return {
        "pages": len(rows),
        "topics": sum(1 for r in rows if r[1]),
        "oldest_days": round(max(ages), 1) if ages else None,
        "ages": bands,
        "days": trash_days,
        "due": due,
    }


def _runs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    out = []
    for table in RUNS:
        found = conn.execute(
            "SELECT substr(started_at, 1, 7), count(*),"
            " sum(length(CAST(request AS BLOB))"
            " + coalesce(length(CAST(response AS BLOB)), 0)"
            " + coalesce(length(CAST(output AS BLOB)), 0))"
            f" FROM {table} GROUP BY 1 ORDER BY 1"
        ).fetchall()
        out += [
            {"table": table, "month": m, "rows": n, "bytes": b or 0}
            for m, n, b in found
        ]
    return out


def _jobs(conn: sqlite3.Connection, job_days: float) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for table in ("job", "enrich_job"):
        out[table] = dict(
            conn.execute(f"SELECT state, count(*) FROM {table} GROUP BY state")
        )
    out["days"] = job_days
    out["old_jobs"], out["old_enrich_jobs"] = retention.prune_jobs(
        conn, retention.stamp(job_days)
    )
    return out


def measure(
    store: Store,
    trash_days: float | None = retention.TRASH_DAYS,
    job_days: float = retention.JOB_DAYS,
) -> dict[str, Any]:
    """The report (see the module), as data. Raises GcError if there is no
    database, sqlite3.Error if it cannot be read."""
    with closing(_open(store.db)) as conn:
        conn.execute("BEGIN")  # one snapshot
        try:
            size = sum(
                p.stat().st_size
                for p in (store.db, Path(f"{store.db}-wal"))
                if p.is_file()
            )
            return {
                "database_bytes": size,
                "tables": _tables(conn),
                "files": _files_split(store, conn),
                "trash": _trash(conn, trash_days),
                "runs": _runs(conn),
                "jobs": _jobs(conn, job_days),
            }
        finally:
            conn.execute("ROLLBACK")


def _mb(n: int) -> str:
    return f"{n / 2**20:.1f} MB" if n >= 2**20 else f"{n / 1024:.0f} kB"


def text(r: dict[str, Any]) -> str:
    """The report as lines to print."""
    lines = [
        f"scrap gc --report: database {_mb(r['database_bytes'])} (the file, with its"
        " write-ahead log)",
        "",
    ]
    est = any(t["estimated"] for t in r["tables"])
    lines.append(
        "Tables, with their indexes (and SQLite's own, sqlite_schema...)"
        + (" (estimated: this SQLite has no dbstat)" if est else "")
        + ":"
    )
    for t in r["tables"]:
        rows = "" if t["rows"] is None else f"{t['rows']:>9} rows"
        lines.append(f"  {t['table']:<20} {rows:>14} {_mb(t['bytes']):>10}")
    f = r["files"]
    lines += ["", "Stored files:"]
    for key, label in (
        ("in_use", "in use"),
        (
            "review_only",
            "shown only on Orphaned assets pages in the trash (a purge lets them go)",
        ),
        ("trash_only", "used only by pages in the trash"),
        ("unused", "unused (gc deletes them after the grace period)"),
    ):
        lines.append(f"  {f[key]['files']:>7} {_mb(f[key]['bytes']):>10}  {label}")
    if f["missing"]:
        lines.append(f"  {f['missing']:>7} file records with no file")
    t = r["trash"]
    lines += [
        "",
        f"Trash: {t['pages']} pages ({t['topics']} topics, never purged)"
        + (
            f", the oldest {t['oldest_days']} days"
            if t["oldest_days"] is not None
            else ""
        ),
        "  by age: " + ", ".join(f"{label} {n}" for label, n in t["ages"].items()),
        (
            f"  trashed more than {t['days']:g} days ago (a purge's): {t['due']}"
            if t["days"] is not None
            else "  never purged (--trash-days off)"
        ),
        "",
        "Claude call records (rows, and bytes of request, response and output;"
        " --run-days prunes model_run and enrich_run, not topic_run):",
    ]
    for run in r["runs"]:
        lines.append(
            f"  {run['table']:<11} {run['month']}  {run['rows']:>7}"
            f" {_mb(run['bytes']):>10}"
        )
    j = r["jobs"]
    lines.append("")
    for table in ("job", "enrich_job"):
        states = ", ".join(f"{s} {n}" for s, n in sorted(j[table].items())) or "none"
        lines.append(f"{table}: {states}")
    lines.append(
        f"  finished more than {j['days']:g} days ago (a prune's): {j['old_jobs']}"
        f" ingest jobs, {j['old_enrich_jobs']} enrich jobs"
    )
    return "\n".join(lines)
