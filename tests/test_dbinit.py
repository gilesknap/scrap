"""The init container's rules (ADR 46), against a fake litestream program."""

import json
import os
import shutil
import sqlite3
import stat
import subprocess
import time
from contextlib import closing
from pathlib import Path

import pytest
import yaml

from scrap import dbinit, dbstate
from scrap.__main__ import main
from scrap.dbinit import InitError, Paths, put_in_place
from scrap.replica import ReplicaError, has_replica
from scrap.schedule import load
from scrap.store import Store, connect, migrate

FAKE = """#!/bin/sh
# Fake litestream: `restore -o OUT file://DIR` copies DIR/fake.db to OUT, or fails.
[ "$1" = restore ] || exit 2
out=$3; dir=${4#file://}
[ -e "$dir/FAIL" ] && { echo "Error: broken replica" >&2; exit 1; }
[ -e "$dir/NOTHING" ] && exit 0
cp "$dir/fake.db" "$out"
"""


def make_db(path, title):
    Store(path.parent, path).migrate()
    with closing(connect(path)) as conn:
        conn.execute(
            "INSERT INTO page(id, slug, title, created_at, updated_at)"
            " VALUES (?, ?, ?, '2026-01-01', '2026-01-01')",
            (title, title, title),
        )
    path.with_name(f"{path.name}.lock").unlink(missing_ok=True)


def titles(path):
    with closing(sqlite3.connect(path)) as conn:
        return [row[0] for row in conn.execute("SELECT title FROM page")]


@pytest.fixture
def paths(tmp_path, monkeypatch):
    fake = tmp_path / "litestream"
    fake.write_text(FAKE)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("SCRAP_LITESTREAM_BIN", str(fake))
    monkeypatch.delenv("SCRAP_DB_PATH", raising=False)
    data = tmp_path / "data"
    data.mkdir()
    return Paths(
        db=tmp_path / "local" / "scrap.db",
        data=data,
        replica=data / "litestream",
        backups=tmp_path / "backups",
    )


def with_replica(paths, title="from replica"):
    paths.replica.mkdir(parents=True, exist_ok=True)
    make_db(paths.replica / "fake.db", title)


def with_legacy(paths, title="legacy"):
    make_db(paths.data / "scrap.db", title)


# Rule 1: a database on the emptyDir is kept


def test_a_database_on_the_emptydir_is_kept(paths):
    paths.db.parent.mkdir()
    make_db(paths.db, "live")
    with_replica(paths)
    with_legacy(paths)
    before = paths.db.read_bytes()
    assert "kept" in put_in_place(paths)
    assert paths.db.read_bytes() == before
    assert titles(paths.db) == ["live"]


def test_a_kept_database_even_with_a_broken_replica(paths):
    paths.db.parent.mkdir()
    make_db(paths.db, "live")
    with_replica(paths)
    (paths.replica / "FAIL").touch()
    assert "kept" in put_in_place(paths)


def test_a_kept_database_gets_its_state_if_the_first_start_died(paths):
    paths.db.parent.mkdir()
    make_db(paths.db, "live")
    assert not (paths.data / dbinit.STATE).exists()
    put_in_place(paths)
    assert json.loads((paths.data / dbinit.STATE).read_text())["how"] == "kept"


# Rule 2 (the brief's): a replica is restored, and failure is failure


def test_a_replica_is_restored(paths):
    with_replica(paths)
    assert "restored" in put_in_place(paths)
    assert titles(paths.db) == ["from replica"]
    assert (paths.data / dbinit.STATE).is_file()


def test_the_state_file_stays_truthful_across_restores(paths, monkeypatch):
    """First start, then the pod replaced: how and at still say how and when the
    database was first put in place; the restore is recorded beside them."""
    clock = ["2026-11-01T09:00:00+00:00"]
    monkeypatch.setattr(dbinit, "now_iso", lambda: clock[0])
    monkeypatch.setattr(dbstate, "now_iso", lambda: clock[0])
    assert "new" in put_in_place(paths)
    first = json.loads((paths.data / dbinit.STATE).read_text())
    assert first["how"] == "new" and first["at"] == "2026-11-01T09:00:00+00:00"
    assert "replica_restored_at" not in first
    paths.db.unlink()  # the pod is replaced, its emptyDir gone
    with_replica(paths)
    clock[0] = "2026-11-03T10:00:00+00:00"
    assert "restored" in put_in_place(paths)
    state = json.loads((paths.data / dbinit.STATE).read_text())
    assert state["how"] == "new" and state["at"] == "2026-11-01T09:00:00+00:00"
    assert state["replica_restored_at"] == "2026-11-03T10:00:00+00:00"
    assert "restored_at" not in state  # that would hold gc
    paths.db.unlink()
    shutil.rmtree(paths.replica)  # and the replica then lost: the refusal reads true
    with pytest.raises(InitError) as refused:
        put_in_place(paths)
    assert (
        "put in place on 2026-11-01T09:00:00+00:00 (new), last restored from its"
        " replica on 2026-11-03T10:00:00+00:00"
    ) in str(refused.value)


def test_a_replica_restored_with_no_state_file_says_so(paths):
    with_replica(paths)
    put_in_place(paths)
    state = json.loads((paths.data / dbinit.STATE).read_text())
    assert state["how"] == "replica" and state["replica_restored_at"]


def test_a_staged_restore_is_a_new_placement(paths):
    with_replica(paths)
    put_in_place(paths)
    paths.db.unlink()
    staged_store(paths)
    put_in_place(paths)
    state = json.loads((paths.data / dbinit.STATE).read_text())
    assert state["how"] == "staged restore" and "replica_restored_at" not in state


def test_a_restore_that_fails_fails_and_starts_nothing(paths):
    with_legacy(paths)  # a way out it must not take
    put_in_place(paths)
    paths.db.unlink()
    with_replica(paths)
    (paths.replica / "FAIL").touch()
    with pytest.raises(ReplicaError, match="failed"):
        put_in_place(paths)
    assert not paths.db.exists()


def test_a_restore_with_a_damaged_result_fails(paths):
    with_replica(paths)
    (paths.replica / "fake.db").write_bytes(b"not a database" * 1000)
    with pytest.raises(ReplicaError):
        put_in_place(paths)
    assert not paths.db.exists()


def test_a_restore_that_makes_nothing_fails(paths):
    with_replica(paths)
    (paths.replica / "NOTHING").touch()
    with pytest.raises(ReplicaError, match="made no database"):
        put_in_place(paths)


def test_a_replica_from_a_newer_scrap_fails(paths):
    with_replica(paths)
    with closing(sqlite3.connect(paths.replica / "fake.db")) as conn:
        conn.execute("PRAGMA user_version = 9999")
    with pytest.raises(ReplicaError, match="9999"):
        put_in_place(paths)
    assert not paths.db.exists()


def test_after_a_failed_restore_a_retry_can_work(paths):
    with_replica(paths)
    (paths.replica / "FAIL").touch()
    with pytest.raises(ReplicaError):
        put_in_place(paths)
    (paths.replica / "FAIL").unlink()
    assert "restored" in put_in_place(paths)


def test_empty_replica_folders_are_not_a_replica(paths):
    (paths.replica / "ltx" / "0").mkdir(parents=True)
    (paths.replica / "ltx" / "0" / "half.ltx.tmp").touch()  # never finished
    assert not has_replica(paths.replica)
    assert not has_replica(paths.data / "none")


def test_an_unreadable_replica_is_an_error_not_none(paths, monkeypatch):
    with_replica(paths)

    def broken(*a, **kw):
        kw["onerror"](OSError(116, "Stale file handle"))
        return iter(())

    monkeypatch.setattr(os, "walk", broken)
    with pytest.raises(OSError, match="Stale"):
        has_replica(paths.replica)


def test_a_stale_mount_is_an_error_not_absent(paths, monkeypatch):
    real = os.stat

    def stale(path, *a, **kw):
        if str(path).endswith(dbinit.STAGED):
            raise OSError(116, "Stale file handle")
        return real(path, *a, **kw)

    monkeypatch.setattr(os, "stat", stale)
    with pytest.raises(OSError, match="Stale"):
        put_in_place(paths)


# Rule 3: an install from before Litestream comes across, once


def test_a_legacy_database_comes_across_with_its_wal_and_stays(paths):
    legacy = paths.data / "scrap.db"
    Store(paths.data, legacy).migrate()
    keep = connect(legacy)  # holds the WAL open, so the row is only in the -wal
    keep.execute("SELECT 1 FROM page").fetchall()
    with closing(connect(legacy)) as conn:
        conn.execute(
            "INSERT INTO page(id, slug, title, created_at, updated_at)"
            " VALUES ('w', 'w', 'in the wal', '2026-01-01', '2026-01-01')"
        )
    assert os.path.getsize(f"{legacy}-wal") > 0
    assert "brought" in put_in_place(paths)
    keep.close()
    assert titles(paths.db) == ["in the wal"]
    assert titles(legacy) == ["in the wal"]  # left in place


def test_a_damaged_legacy_database_fails(paths):
    (paths.data / "scrap.db").write_bytes(b"not a database" * 1000)
    with pytest.raises((ReplicaError, sqlite3.DatabaseError)):
        put_in_place(paths)
    assert not paths.db.exists()
    assert not (paths.data / dbinit.STATE).exists()


def test_a_legacy_database_comes_across_only_once(paths):
    with_legacy(paths)
    put_in_place(paths)
    # The next start, with the replica Litestream has made by now
    paths.db.unlink()
    with_replica(paths, "newer")
    assert "restored" in put_in_place(paths)
    assert titles(paths.db) == ["newer"]


def test_a_lost_replica_never_brings_a_stale_legacy_database_back(paths):
    with_legacy(paths)
    put_in_place(paths)
    paths.db.unlink()
    with pytest.raises(InitError, match="no replica"):
        put_in_place(paths)
    assert not paths.db.exists()


def test_the_changed_legacy_message_says_the_replica_may_be_newer(paths):
    with_legacy(paths)
    put_in_place(paths)
    paths.db.unlink()
    with_replica(paths)
    make_db(paths.data / "other.db", "x")
    (paths.data / "other.db").replace(paths.data / "scrap.db")
    with pytest.raises(InitError, match="may well be the newer copy"):
        put_in_place(paths)


def test_a_changed_legacy_database_is_not_overwritten_by_the_replica(paths):
    """A plain scrap restore into /data, by the old steps: the replica must not win."""
    with_legacy(paths)
    put_in_place(paths)
    paths.db.unlink()
    with_replica(paths)
    make_db(paths.data / "other.db", "x")
    (paths.data / "other.db").replace(paths.data / "scrap.db")
    with pytest.raises(InitError, match="has changed"):
        put_in_place(paths)
    assert not paths.db.exists()


def test_a_legacy_database_removed_later_is_fine(paths):
    with_legacy(paths)
    put_in_place(paths)
    paths.db.unlink()
    with_replica(paths)
    (paths.data / "scrap.db").unlink()
    assert "restored" in put_in_place(paths)


def test_a_database_written_there_on_a_new_install_counts_as_changed(paths):
    put_in_place(paths)  # new: no legacy file
    paths.db.unlink()
    with_replica(paths)
    with_legacy(paths)
    with pytest.raises(InitError, match="has changed"):
        put_in_place(paths)


# Rule 4: new, only if nothing says otherwise


def test_an_empty_legacy_file_is_no_stand_in_when_there_is_history(paths):
    Store(paths.data, paths.data / "scrap.db").migrate()  # made, no pages
    (paths.data / "files" / "ab").mkdir(parents=True)
    with pytest.raises(InitError, match="has been used"):
        put_in_place(paths)
    assert not paths.db.exists()


def test_a_zero_byte_legacy_file_is_no_stand_in(paths):
    (paths.data / "scrap.db").touch()
    (paths.backups / "20261104T033000Z").mkdir(parents=True)
    with pytest.raises(InitError, match="backup runs"):
        put_in_place(paths)


def test_an_empty_legacy_file_with_no_history_is_new(paths):
    Store(paths.data, paths.data / "scrap.db").migrate()
    assert "new" in put_in_place(paths)


def test_a_new_database(paths):
    assert "new" in put_in_place(paths)
    assert titles(paths.db) == []
    assert not paths.db.with_name("scrap.db.init").exists()
    assert json.loads((paths.data / dbinit.STATE).read_text())["how"] == "new"


def test_a_new_database_is_current(paths):
    put_in_place(paths)
    migrate(paths.db)  # nothing left to do, and no complaint


def test_files_but_no_database_fails_closed(paths):
    (paths.data / "files" / "ab").mkdir(parents=True)
    with pytest.raises(InitError, match="has been used"):
        put_in_place(paths)
    assert not paths.db.exists()


def test_an_empty_files_folder_is_new(paths):
    (paths.data / "files").mkdir()
    assert "new" in put_in_place(paths)


@pytest.mark.parametrize("run", ["20261104T033000Z", "monthly/20261001T035000Z"])
def test_backup_runs_but_no_database_fails_closed(paths, run):
    (paths.backups / run).mkdir(parents=True)
    with pytest.raises(InitError, match="backup runs"):
        put_in_place(paths)
    assert not paths.db.exists()


def test_other_things_in_the_backup_folder_are_not_history(paths):
    paths.backups.mkdir()
    (paths.backups / ".lock").touch()
    (paths.backups / "export").mkdir()
    assert "new" in put_in_place(paths)


def test_the_state_file_without_a_replica_fails_closed(paths):
    put_in_place(paths)
    paths.db.unlink()
    with pytest.raises(InitError, match="no replica"):
        put_in_place(paths)


def test_a_damaged_state_file_fails_closed(paths):
    (paths.data / dbinit.STATE).write_text("{")
    with pytest.raises(dbstate.StateError, match="not readable"):
        put_in_place(paths)


def test_the_override_gets_past_each_refusal_and_is_remembered(paths):
    paths.override = True
    (paths.data / "files" / "ab").mkdir(parents=True)
    said = put_in_place(paths)  # history
    assert "new" in said and "db-hold --clear" in said
    state = json.loads((paths.data / dbinit.STATE).read_text())
    assert state["override_at"] and "has been used" in state["override_why"]
    paths.db.unlink()
    paths.overridden.clear()
    assert "new" in put_in_place(paths)  # the state, no replica
    paths.db.unlink()
    paths.overridden.clear()
    with_legacy(paths)
    assert "brought" in put_in_place(paths)  # the state, no replica, so the old file


def test_the_override_with_nothing_to_override_records_nothing(paths):
    paths.override = True
    assert "WARNING" not in put_in_place(paths)
    assert "override_at" not in json.loads((paths.data / dbinit.STATE).read_text())


def test_leftovers_of_a_failed_start_are_cleared(paths):
    paths.db.parent.mkdir()
    (paths.db.parent / "scrap.db-wal").write_bytes(b"old wal")
    (paths.db.parent / "scrap.db.init").write_bytes(b"part")
    (paths.db.parent / ".scrap.db-litestream").mkdir()
    (paths.db.parent / "scrap.db.restoring").mkdir()
    assert "new" in put_in_place(paths)
    assert not (paths.db.parent / ".scrap.db-litestream").exists()
    assert not (paths.db.parent / "scrap.db.restoring").exists()
    assert titles(paths.db) == []


# A staged restore


def staged_store(paths):
    make_db(paths.data / dbinit.STAGED, "from backup")


def test_a_staged_restore_wins_and_retires_the_replica(paths):
    with_replica(paths, "newer but unwanted")
    staged_store(paths)
    said = put_in_place(paths)
    assert "staged" in said and "retired" in said
    assert titles(paths.db) == ["from backup"]
    assert not paths.replica.exists()
    assert not (paths.data / dbinit.STAGED).exists()
    retired = [p for p in paths.data.iterdir() if ".retired-" in p.name]
    assert len(retired) == 1 and (retired[0] / "fake.db").is_file()


def test_a_staged_restore_with_no_replica(paths):
    staged_store(paths)
    assert "staged" in put_in_place(paths)


def test_a_damaged_staged_restore_touches_nothing(paths):
    with_replica(paths)
    (paths.data / dbinit.STAGED).write_bytes(b"not a database" * 1000)
    with pytest.raises((ReplicaError, sqlite3.DatabaseError)):
        put_in_place(paths)
    assert paths.replica.is_dir() and not paths.db.exists()


def test_a_staged_restore_beside_a_live_database_stops_the_pod(paths):
    paths.db.parent.mkdir()
    make_db(paths.db, "live")
    staged_store(paths)
    with pytest.raises(InitError, match="Scale scrap to 0"):
        put_in_place(paths)
    assert titles(paths.db) == ["live"]
    assert (paths.data / dbinit.STAGED).is_file()


def test_the_replica_after_a_staged_restore_is_used_again(paths):
    with_replica(paths, "old")
    staged_store(paths)
    put_in_place(paths)
    paths.db.unlink()
    with_replica(paths, "made since the restore")
    assert "restored" in put_in_place(paths)
    assert titles(paths.db) == ["made since the restore"]


def test_a_staged_restore_older_than_the_replicas_writes_is_refused(paths):
    staged_store(paths)
    with_replica(paths)
    now = time.time()
    os.utime(paths.data / dbinit.STAGED, (now - 600, now - 600))
    os.utime(paths.replica / "fake.db", (now, now))
    with pytest.raises(InitError, match="went on running") as refused:
        put_in_place(paths)
    assert "touch" in str(refused.value)
    assert paths.replica.is_dir() and not paths.db.exists()
    os.utime(paths.data / dbinit.STAGED, (now + 5, now + 5))  # the way through it names
    assert "staged" in put_in_place(paths)


def test_a_staged_restore_starts_gc_holding(paths):
    staged_store(paths)
    put_in_place(paths)
    state = json.loads((paths.data / dbinit.STATE).read_text())
    assert state["restored_at"]


def test_restore_stage_refuses_beside_a_live_database(paths, tmp_path, monkeypatch):
    paths.db.parent.mkdir()
    paths.db.touch()
    monkeypatch.setenv("SCRAP_DB_PATH", str(paths.db))
    with_replica(paths)
    args = ["restore", str(tmp_path), "--stage", "--data-dir", str(paths.data)]
    with pytest.raises(SystemExit, match="scrap is running here"):
        main(args)


def test_restore_stage_without_litestream_says_so(tmp_path):
    with pytest.raises(SystemExit, match="no sign of one"):
        main(["restore", str(tmp_path), "--stage", "--data-dir", str(tmp_path / "d")])


# How far behind the replica is


def stamped(paths, behind):
    now = int(time.time() // 60)
    with_replica(paths)
    with closing(sqlite3.connect(paths.replica / "fake.db")) as conn:
        conn.execute(f"PRAGMA application_id = {now - behind}")
    dbstate.record_stamp(paths.data, now)


def test_a_replica_level_with_the_last_stamp_is_quiet(paths):
    stamped(paths, 0)
    said = put_in_place(paths)
    assert (
        "restored" in said and "stamp 0 minutes old" in said and "WARNING" not in said
    )
    assert not (paths.data / dbstate.HEALTH).exists()  # begins again


def test_a_replica_a_little_behind_warns(paths):
    stamped(paths, 15)
    said = put_in_place(paths)
    assert "restored" in said and "WARNING" in said and "15 minutes behind" in said


def test_a_replica_far_behind_refuses(paths):
    stamped(paths, 120)
    with pytest.raises(InitError, match="stalled"):
        put_in_place(paths)
    assert not paths.db.exists()
    assert dbstate.last_stamp(paths.data)  # still there for the next look
    paths.db.with_name("scrap.db.restoring").is_dir()


def test_the_override_goes_on_from_a_replica_far_behind_and_holds_gc(paths):
    stamped(paths, 120)
    paths.override = True
    assert "restored" in put_in_place(paths)
    assert json.loads((paths.data / dbinit.STATE).read_text())["override_at"]


def test_a_replica_with_no_stamp_though_one_was_written_refuses(paths):
    with_replica(paths)
    dbstate.record_stamp(paths.data, int(time.time() // 60))
    with pytest.raises(InitError, match="behind what was last written"):
        put_in_place(paths)


# Too big for the emptyDir


def test_a_legacy_file_over_half_the_emptydir_is_refused(paths):
    with_legacy(paths)
    paths.size_limit = (paths.data / "scrap.db").stat().st_size
    with pytest.raises(InitError, match="raise litestream.sizeLimit"):
        put_in_place(paths)
    assert not paths.db.exists()


def test_a_replica_over_half_the_emptydir_is_refused_even_with_the_override(paths):
    with_replica(paths)
    paths.size_limit = 1000
    paths.override = True
    with pytest.raises(InitError, match="raise litestream.sizeLimit"):
        put_in_place(paths)


def test_the_size_limit_comes_from_the_environment(paths, monkeypatch):
    monkeypatch.setenv("SCRAP_DB_PATH", str(paths.db))
    monkeypatch.setenv("SCRAP_DATA_DIR", str(paths.data))
    monkeypatch.setenv("SCRAP_LITESTREAM_REPLICA", str(paths.replica))
    monkeypatch.setenv("SCRAP_DB_SIZE_LIMIT", "1Ki")
    with_legacy(paths)
    with pytest.raises(SystemExit, match="raise litestream.sizeLimit"):
        main(["db-init"])


# The bad schedule that must stop the rollout


@pytest.mark.parametrize(
    "item",
    [
        {"schedule": "nope"},
        {"schedule": "@every 1h"},
        {"schedule": "* * * * 7"},
        {"schedule": "* * * * *", "timeZone": "No/Where"},
    ],
)
def test_db_init_refuses_a_bad_schedule(paths, monkeypatch, item):
    monkeypatch.setenv("SCRAP_DB_PATH", str(paths.db))
    monkeypatch.setenv("SCRAP_DATA_DIR", str(paths.data))
    monkeypatch.setenv("SCRAP_LITESTREAM_REPLICA", str(paths.replica))
    job = {"name": "gc", "timeoutSeconds": 1, "command": ["x"], **item}
    monkeypatch.setenv("SCRAP_SCHEDULE", json.dumps([job]))
    with pytest.raises(SystemExit, match="job gc"):
        main(["db-init"])
    assert not paths.db.exists()


def test_the_rendered_schedule_survives_helm_and_loads(paths):
    """The chart's own JSON, with its escaping, through load."""
    helm = shutil.which("helm")
    if not helm:
        pytest.skip("no helm")
    root = Path(__file__).parent.parent / "charts" / "scrap"
    out = subprocess.run(
        [
            helm,
            "template",
            "scrap",
            str(root),
            "-f",
            str(root / "ci/litestream-values.yaml"),
        ],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "KUBECONFIG": os.devnull},
    ).stdout
    found = []
    for doc in yaml.safe_load_all(out):
        if doc and doc["kind"] == "Deployment":
            spec = doc["spec"]["template"]["spec"]
            for c in spec["initContainers"] + spec["containers"]:
                for e in c.get("env", []):
                    if e["name"] == "SCRAP_SCHEDULE":
                        found.append(e["value"])
    assert len(found) == 2 and found[0] == found[1]
    jobs = load(found[0], strict=True)
    assert [j.name for j in jobs] == ["gc", "enrich-related", "enrich-topics"]
    gc = jobs[0]
    assert gc.command[:2] == ["/bin/sh", "-ec"]
    assert "COMPLETE" in gc.command[2] and "\\\n" in gc.command[2]
    assert not gc.pausable and jobs[1].pausable and jobs[2].pausable


# The commands


def test_scrap_db_init_reports_and_refuses(paths, monkeypatch, capsys):
    monkeypatch.setenv("SCRAP_DB_PATH", str(paths.db))
    monkeypatch.setenv("SCRAP_DATA_DIR", str(paths.data))
    monkeypatch.setenv("SCRAP_LITESTREAM_REPLICA", str(paths.replica))
    monkeypatch.setenv("SCRAP_BACKUPS", str(paths.backups))
    monkeypatch.delenv("SCRAP_DB_INIT_OVERRIDE", raising=False)
    (paths.data / "files" / "ab").mkdir(parents=True)
    with pytest.raises(SystemExit, match="has been used"):
        main(["db-init"])
    monkeypatch.setenv("SCRAP_DB_INIT_OVERRIDE", "on")
    main(["db-init"])
    assert "made a new database" in capsys.readouterr().out


def test_scrap_db_init_turns_a_failed_restore_into_an_exit(paths, monkeypatch):
    monkeypatch.setenv("SCRAP_DB_PATH", str(paths.db))
    monkeypatch.setenv("SCRAP_DATA_DIR", str(paths.data))
    monkeypatch.setenv("SCRAP_LITESTREAM_REPLICA", str(paths.replica))
    with_replica(paths)
    (paths.replica / "FAIL").touch()
    with pytest.raises(SystemExit, match="failed"):
        main(["db-init"])


def test_scrap_db_init_needs_its_settings(monkeypatch):
    monkeypatch.delenv("SCRAP_LITESTREAM_REPLICA", raising=False)
    with pytest.raises(SystemExit, match="is not set"):
        main(["db-init"])


def test_plain_restore_is_refused_beside_a_replica(tmp_path, monkeypatch):
    source = Store(tmp_path / "a")
    source.migrate()
    main(["backup", str(tmp_path / "bak"), "--data-dir", str(tmp_path / "a")])
    monkeypatch.setenv("SCRAP_LITESTREAM_REPLICA", str(tmp_path / "r"))
    with pytest.raises(SystemExit, match="--stage"):
        main(["restore", str(tmp_path / "bak"), "--data-dir", str(tmp_path / "b")])
    assert not (tmp_path / "b").exists()


def test_restore_stage_leaves_it_for_the_next_start(paths, tmp_path):
    source = Store(tmp_path / "a")
    source.migrate()
    make_db(tmp_path / "a" / "scrap.db", "from backup")
    main(["backup", str(tmp_path / "bak"), "--data-dir", str(tmp_path / "a")])
    with_replica(paths)
    args = ["restore", str(tmp_path / "bak"), "--stage", "--data-dir", str(paths.data)]
    main(args)
    assert titles(paths.data / dbinit.STAGED) == ["from backup"]
    assert not (paths.data / "scrap.db").exists()
    assert (paths.replica / "fake.db").is_file()  # for the start to deal with
    assert "staged" in put_in_place(paths)
    assert titles(paths.db) == ["from backup"]
