"""Replication watched, gc's safety limit and the state file (ADR 46)."""

import json
import os
import time
from contextlib import closing

import pytest

from scrap import dbstate, gc_guard, watch
from scrap.__main__ import main
from scrap.app import create_app
from scrap.dbstate import StateError
from scrap.gc import collect
from scrap.store import Store, connect
from scrap.watch import STALE_SECONDS, Watch

# The replica


@pytest.fixture
def setup(tmp_path, monkeypatch):
    said = []
    monkeypatch.setattr(watch, "notify", said.append)
    db = tmp_path / "local" / "scrap.db"
    db.parent.mkdir()
    data = tmp_path / "data"
    replica = data / "litestream" / "ltx" / "0"
    replica.mkdir(parents=True)
    return db, data, data / "litestream", said


def write(replica, seconds_old, name="a.ltx"):
    path = replica / "ltx" / "0" / name
    path.touch()
    at = time.time() - seconds_old
    os.utime(path, (at, at))


def old_watch(db, data, replica, **kw):
    """One that has been running long enough to judge."""
    return Watch(db, data, replica, started=time.time() - 2 * STALE_SECONDS, **kw)


def test_ok_while_writes_reach_the_replica(setup):
    db, data, replica, said = setup
    write(replica, 60)
    w = old_watch(db, data, replica)
    w.check()
    assert db.with_name(watch.OK_FILE).exists()
    assert said == []


def test_no_flapping_before_the_first_stamp_can_land(setup):
    db, data, replica, said = setup
    w = Watch(db, data, replica)  # just started, nothing in the replica yet
    w.check()
    assert db.with_name(watch.OK_FILE).exists()
    assert said == []


def test_a_stalled_replica_fails_readiness_and_says_so_once(setup, caplog):
    db, data, replica, said = setup
    write(replica, STALE_SECONDS + 60)
    w = old_watch(db, data, replica)
    assert db.with_name(watch.OK_FILE).exists()
    w.check()
    w.check()
    assert not db.with_name(watch.OK_FILE).exists()
    assert said == ["scrap: replication stalled; scrap stopped taking writes"]
    assert caplog.text.count("REPLICATION STALLED") == 1


def test_a_replica_that_recovers_comes_back(setup):
    db, data, replica, said = setup
    write(replica, STALE_SECONDS + 60)
    w = old_watch(db, data, replica)
    w.check()
    write(replica, 1, "b.ltx")
    w.check()
    assert db.with_name(watch.OK_FILE).exists()
    assert said[-1] == "scrap: replication is working again"


def test_a_tmp_file_is_not_a_write(setup):
    db, data, replica, said = setup
    write(replica, STALE_SECONDS + 60)
    write(replica, 1, "c.ltx.tmp")
    old_watch(db, data, replica).check()
    assert not db.with_name(watch.OK_FILE).exists()


def test_an_unreadable_replica_is_stalled_at_once(setup, monkeypatch):
    db, data, replica, said = setup
    w = Watch(db, data, replica)

    def broken(_):
        raise OSError(116, "Stale file handle")

    monkeypatch.setattr(watch, "newest_file", broken)
    w.check()
    assert not db.with_name(watch.OK_FILE).exists()
    assert "stalled" in said[0]


def test_the_probe_command_accepts_a_young_file_only(tmp_path):
    ok = tmp_path / watch.OK_FILE
    probe = f'test -n "$(find {ok} -mmin -5 2>/dev/null)"'
    assert os.system(probe) != 0  # missing
    ok.touch()
    assert os.system(probe) == 0
    at = time.time() - 600
    os.utime(ok, (at, at))
    assert os.system(probe) != 0


def test_size_warning_once(setup, caplog):
    db, data, replica, said = setup
    write(replica, 1)
    db.write_bytes(b"x" * 600)
    w = old_watch(db, data, replica, size_limit=1000)
    w.check()
    w.check()
    assert said == ["scrap: the database is over half of litestream.sizeLimit"]
    assert "raise litestream.sizeLimit" in caplog.text


def test_a_stamp_is_noted_for_the_next_start(setup):
    db, data, replica, _ = setup
    Watch(db, data, replica).stamped(1234)
    assert dbstate.last_stamp(data) == 1234


def test_a_stamp_that_cannot_be_noted_only_logs(setup, caplog):
    db, data, replica, _ = setup
    w = Watch(db, data / "nowhere", replica)
    w.stamped(1)
    assert "could not note the stamp" in caplog.text


# The state file


@pytest.mark.parametrize("text", ["{", "{}", "[]", "1", '{"at": "x"}'])
def test_a_state_file_that_is_not_ours_is_an_error(tmp_path, text):
    (tmp_path / dbstate.STATE).write_text(text)
    with pytest.raises(StateError, match="not readable"):
        dbstate.read_state(tmp_path)


@pytest.mark.parametrize(
    "text", ["2Gi 2147483648", "500Mi 524288000", "1G 1000000000", "7 7"]
)
def test_parse_size(text):
    given, want = text.split()
    assert dbstate.parse_size(given) == int(want)


def test_parse_size_refuses():
    with pytest.raises(ValueError):
        dbstate.parse_size("lots")


def test_a_damaged_health_note_is_only_unknown(tmp_path):
    for text in ("{", "[]", '{"last_stamp": "x"}'):
        (tmp_path / dbstate.HEALTH).write_text(text)
        assert dbstate.last_stamp(tmp_path) is None


# Off Litestream with the marker there: the old file must not be served


@pytest.fixture
def was_litestream(tmp_path, monkeypatch):
    monkeypatch.delenv("SCRAP_DB_PATH", raising=False)
    store = Store(tmp_path)
    store.migrate()
    dbstate.write_state(tmp_path, "legacy")
    return store


def test_the_app_refuses_the_old_database(was_litestream, tmp_path):
    with pytest.raises(StateError, match="old copy"):
        create_app(tmp_path)


def test_gc_refuses_the_old_database(was_litestream, tmp_path, capsys):
    with pytest.raises(SystemExit, match="old copy"):
        main(["gc", "--delete", "--data-dir", str(tmp_path)])
    with pytest.raises(SystemExit, match="old copy"):
        main(["gc", "--data-dir", str(tmp_path)])


def test_gc_report_still_reads(was_litestream, tmp_path, capsys):
    main(["gc", "--report", "--data-dir", str(tmp_path)])
    assert capsys.readouterr().out


def test_restore_force_is_the_way_off(was_litestream, tmp_path, capsys):
    source = Store(tmp_path / "a")
    source.migrate()
    bak = tmp_path / "bak"
    main(["backup", str(bak), "--data-dir", str(tmp_path / "a")])
    dbstate.record_stamp(tmp_path, 1)
    main(["restore", str(bak), "--force", "--data-dir", str(tmp_path)])
    assert not (tmp_path / dbstate.STATE).exists()
    assert not (tmp_path / dbstate.HEALTH).exists()
    create_app(tmp_path)  # starts now


def test_no_marker_no_change(tmp_path, monkeypatch):
    monkeypatch.delenv("SCRAP_DB_PATH", raising=False)
    create_app(tmp_path)


def test_with_the_setting_the_marker_is_normal(tmp_path, monkeypatch):
    monkeypatch.setenv("SCRAP_DB_PATH", str(tmp_path / "local" / "scrap.db"))
    dbstate.write_state(tmp_path, "new")
    create_app(tmp_path)


# gc's safety limit


def add_files(store, count, age_days=10):
    """Files on disk nothing refers to, old enough for gc."""
    at = time.time() - age_days * 86400
    for n in range(count):
        path = store.blob_path(f"{n:064x}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        os.utime(path, (at, at))


def add_capture(store, n=0):
    """A capture and its file, in use."""
    sha = f"{n + 5000:064x}"
    path = store.blob_path(sha)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"y")
    with closing(connect(store.db)) as conn:
        now = "2026-01-01T00:00:00Z"
        conn.execute(
            "INSERT INTO page(id, slug, title, created_at, updated_at)"
            f" VALUES ('p{n}', 'p{n}', 'p', '{now}', '{now}')"
        )
        conn.execute(
            "INSERT INTO blob(sha256, mime, size, created_at)"
            " VALUES (?, 'text/plain', 1, ?)",
            (sha, now),
        )
        conn.execute(
            "INSERT INTO capture(id, page_id, kind, source, author, created_at,"
            " received_at)"
            f" VALUES ('c{n}', 'p{n}', 'note', 'pwa', 'x', '{now}', '{now}')"
        )
        conn.execute(
            "INSERT INTO capture_blob(capture_id, sha256, ord) VALUES (?, ?, 0)",
            (f"c{n}", sha),
        )
    return sha


@pytest.fixture
def replicated(tmp_path, monkeypatch):
    monkeypatch.delenv("SCRAP_DB_PATH", raising=False)
    store = Store(tmp_path / "data", tmp_path / "local" / "scrap.db")
    store.migrate()
    return store


def run_guarded(store, delete=True, allow=False):
    return gc_guard.guarded(store, delete, allow, 24.0, 30.0)


def blobs(store):
    return [p for p in store.files.rglob("*") if p.is_file()]


def test_no_captures_but_files_counts_only(replicated):
    add_files(replicated, 3)
    report, hold = run_guarded(replicated)
    assert hold and "no captures" in hold.why and hold.fails
    assert not report.deleted and len(blobs(replicated)) == 3


def test_too_much_unused_counts_only(replicated):
    add_capture(replicated)
    add_files(replicated, gc_guard.MIN_UNUSED)
    report, hold = run_guarded(replicated)
    assert hold and "over the limit" in hold.why
    assert len(blobs(replicated)) == gc_guard.MIN_UNUSED + 1


def test_allow_large_goes_ahead(replicated):
    add_capture(replicated)
    add_files(replicated, gc_guard.MIN_UNUSED)
    report, hold = run_guarded(replicated, allow=True)
    assert hold is None and report.deleted
    assert len(blobs(replicated)) == 1


def test_below_the_floor_deletes(replicated):
    add_capture(replicated)
    add_files(replicated, gc_guard.MIN_UNUSED - 1)
    report, hold = run_guarded(replicated)
    assert hold is None and report.deleted
    assert len(blobs(replicated)) == 1


def test_a_small_share_deletes(replicated):
    for n in range(60):
        add_capture(replicated, n)
    add_files(replicated, gc_guard.MIN_UNUSED)
    report, hold = run_guarded(replicated)
    assert hold is None and report.deleted


def test_an_override_holds_until_cleared_even_with_allow_large(replicated, capsys):
    data = replicated.dir
    dbstate.write_state(data, "replica", override_at="2026-11-05T00:00:00+00:00")
    add_capture(replicated)
    add_files(replicated, 1)
    _, hold = run_guarded(replicated, allow=True)
    assert hold and "db-hold --clear" in hold.why and hold.fails
    assert len(blobs(replicated)) == 2
    main(["db-hold", "--data-dir", str(data)])
    assert "override_at" in capsys.readouterr().out
    main(["db-hold", "--clear", "--data-dir", str(data)])
    assert "gc may delete again" in capsys.readouterr().out
    _, hold = run_guarded(replicated)
    assert hold is None
    assert len(blobs(replicated)) == 1
    main(["db-hold", "--clear", "--data-dir", str(data)])
    assert "nothing is holding" in capsys.readouterr().out


def test_a_recent_restore_holds_quietly_then_lets_go(replicated):
    data = replicated.dir
    dbstate.write_state(data, "staged restore", restored_at=dbstate.now_iso())
    add_capture(replicated)
    add_files(replicated, 1)
    _, hold = run_guarded(replicated)
    assert hold and "restore was taken up" in hold.why and not hold.fails
    state = json.loads((data / dbstate.STATE).read_text())
    state["restored_at"] = "2020-01-01T00:00:00+00:00"
    (data / dbstate.STATE).write_text(json.dumps(state))
    _, hold = run_guarded(replicated)
    assert hold is None


def test_a_damaged_state_file_holds(replicated):
    (replicated.dir / dbstate.STATE).write_text("{")
    _, hold = run_guarded(replicated)
    assert hold and "not readable" in hold.why


def test_a_dry_run_is_never_held(replicated):
    add_files(replicated, 3)
    _, hold = run_guarded(replicated, delete=False)
    assert hold is None


def test_without_litestream_gc_is_as_it_was(tmp_path, monkeypatch):
    monkeypatch.delenv("SCRAP_DB_PATH", raising=False)
    store = Store(tmp_path)
    store.migrate()
    add_files(store, 20)
    report, hold = run_guarded(store)
    assert hold is None and report.deleted and blobs(store) == []


def test_the_cli_fails_on_a_hold_and_prints_why(replicated, monkeypatch, capsys):
    monkeypatch.setenv("SCRAP_DB_PATH", str(replicated.db))
    add_files(replicated, 3)
    with pytest.raises(SystemExit) as stopped:
        main(
            [
                "gc",
                "--delete",
                "--data-dir",
                str(replicated.dir),
                "--db-path",
                str(replicated.db),
            ]
        )
    assert stopped.value.code == 1
    assert "no captures" in capsys.readouterr().err


def test_collect_itself_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.delenv("SCRAP_DB_PATH", raising=False)
    store = Store(tmp_path)
    store.migrate()
    assert collect(store, False, 24.0, 30.0).deleted is False
