"""Backup runs hard-link unchanged blobs from the newest complete run (issue 570)."""

import errno
import hashlib
import os
import shutil
from pathlib import Path

import pytest

from scrap import backup_files
from scrap.__main__ import main
from scrap.backup import COMPLETE, backup, restore
from scrap.store import Store

DAY1, DAY2, DAY3 = "20261101T033000Z", "20261102T033000Z", "20261103T033000Z"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.delenv("SCRAP_DB_PATH", raising=False)
    store = Store(tmp_path / "data")
    store.migrate()
    return store


def put(store, data: bytes):
    """A blob in the store's files/, as the store lays them out."""
    path = store.blob_path(hashlib.sha256(data).hexdigest())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def files(run):
    return {p.relative_to(run): p for p in (run / "files").rglob("*") if p.is_file()}


def test_a_second_run_links_the_blobs_the_first_has(store, tmp_path):
    old = put(store, b"old photo")
    first = backup(store, tmp_path / "bak" / DAY1)
    assert (first.copied, first.linked, first.base) == (1, 0, None)
    new = put(store, b"new photo")
    second = backup(store, tmp_path / "bak" / DAY2)
    assert second.base == tmp_path / "bak" / DAY1
    assert (second.linked, second.linked_bytes) == (1, len(b"old photo"))
    assert (second.copied, second.copied_bytes) == (1, len(b"new photo"))
    one, two = files(tmp_path / "bak" / DAY1), files(tmp_path / "bak" / DAY2)
    rel = old.relative_to(store.dir)
    assert os.path.samefile(one[rel], two[rel])
    assert two[rel].stat().st_nlink == 2
    assert two[new.relative_to(store.dir)].stat().st_nlink == 1
    # The live store never shares a file with a backup
    assert old.stat().st_nlink == 1 and new.stat().st_nlink == 1
    assert (
        str(second) == "files: 1 copied (0.0 MB), 1 linked from " + DAY1 + " (0.0 MB)"
    )


def test_a_same_name_file_of_another_size_is_copied(store, tmp_path):
    blob = put(store, b"the bytes")
    backup(store, tmp_path / "bak" / DAY1)
    rel = blob.relative_to(store.dir)
    (tmp_path / "bak" / DAY1 / rel).write_bytes(b"damaged")  # not the size it should be
    counts = backup(store, tmp_path / "bak" / DAY2)
    assert (counts.linked, counts.copied) == (0, 1)
    assert (tmp_path / "bak" / DAY2 / rel).read_bytes() == b"the bytes"


@pytest.mark.parametrize(
    "code", [errno.EXDEV, errno.EPERM, errno.EMLINK, errno.ENOTSUP]
)
def test_a_link_that_fails_is_a_copy(store, tmp_path, monkeypatch, code):
    blob = put(store, b"photo")
    backup(store, tmp_path / "bak" / DAY1)

    def refuse(src, dst):
        raise OSError(code, os.strerror(code))

    monkeypatch.setattr(backup_files.os, "link", refuse)
    counts = backup(store, tmp_path / "bak" / DAY2)
    assert (counts.linked, counts.copied) == (0, 1)
    copy = tmp_path / "bak" / DAY2 / blob.relative_to(store.dir)
    assert copy.read_bytes() == b"photo" and copy.stat().st_nlink == 1


def test_an_incomplete_run_is_not_linked_from(store, tmp_path):
    put(store, b"photo")
    backup(store, tmp_path / "bak" / DAY1)
    backup(store, tmp_path / "bak" / DAY2)
    (tmp_path / "bak" / DAY2 / COMPLETE).unlink()  # a run that failed half way
    counts = backup(store, tmp_path / "bak" / DAY3)
    assert counts.base == tmp_path / "bak" / DAY1 and counts.linked == 1


def test_only_runs_named_like_runs_link(store, tmp_path):
    put(store, b"photo")
    backup(store, tmp_path / "bak" / DAY1)
    assert backup(store, tmp_path / "bak" / "by-hand").copied == 1
    shutil.copytree(tmp_path / "bak" / DAY1, tmp_path / "bak" / "not-a-run")
    shutil.rmtree(tmp_path / "bak" / DAY1)
    assert backup(store, tmp_path / "bak" / DAY2).base is None


def test_pruning_the_older_run_leaves_the_newer_whole(store, tmp_path):
    blob = put(store, b"photo")
    backup(store, tmp_path / "bak" / DAY1)
    backup(store, tmp_path / "bak" / DAY2)
    shutil.rmtree(tmp_path / "bak" / DAY1)  # as scrap-backup prune does
    kept = tmp_path / "bak" / DAY2 / blob.relative_to(store.dir)
    assert kept.read_bytes() == b"photo" and kept.stat().st_nlink == 1
    restore(tmp_path / "bak" / DAY2, Store(tmp_path / "new"))
    assert (tmp_path / "new" / blob.relative_to(store.dir)).read_bytes() == b"photo"


def test_restore_copies_out_of_a_run_never_links(store, tmp_path):
    blob = put(store, b"photo")
    backup(store, tmp_path / "bak" / DAY1)
    backup(store, tmp_path / "bak" / DAY2)
    restore(tmp_path / "bak" / DAY2, Store(tmp_path / "new"))
    restored = tmp_path / "new" / blob.relative_to(store.dir)
    assert restored.stat().st_nlink == 1
    restored.write_bytes(b"changed")  # nothing a restored store does reaches a backup
    assert (tmp_path / "bak" / DAY2 / blob.relative_to(store.dir)).read_bytes() == (
        b"photo"
    )


def test_monthly_and_daily_runs_link_from_each_other(store, tmp_path):
    put(store, b"photo")
    backup(store, tmp_path / "bak" / DAY1)
    monthly = backup(store, tmp_path / "bak" / "monthly" / DAY2)
    assert monthly.base == tmp_path / "bak" / DAY1 and monthly.linked == 1
    shutil.rmtree(tmp_path / "bak" / DAY1)
    daily = backup(store, tmp_path / "bak" / DAY3)
    assert daily.base == tmp_path / "bak" / "monthly" / DAY2 and daily.linked == 1


def test_a_re_run_into_the_same_run_does_not_link_from_itself(store, tmp_path):
    put(store, b"photo")
    backup(store, tmp_path / "bak" / DAY1)
    again = backup(store, tmp_path / "bak" / DAY1)  # its files are there already
    assert (again.base, again.linked, again.copied) == (None, 0, 0)


def test_the_cli_says_what_it_linked_and_copied(store, tmp_path, capsys):
    put(store, b"photo")
    args = ["backup", "--data-dir", str(store.dir)]
    main([*args, str(tmp_path / "bak" / DAY1)])
    assert capsys.readouterr().out == "files: 1 copied (0.0 MB)\n"
    main([*args, str(tmp_path / "bak" / DAY2)])
    out = capsys.readouterr().out
    assert out == f"files: 0 copied (0.0 MB), 1 linked from {DAY1} (0.0 MB)\n"


def test_a_damaged_blob_of_the_same_size_is_copied_afresh(store, tmp_path, caplog):
    blob = put(store, b"the bytes")
    backup(store, tmp_path / "bak" / DAY1)
    bad = tmp_path / "bak" / DAY1 / blob.relative_to(store.dir)
    bad.write_bytes(b"bit rot!!")  # the same size, other bytes
    with caplog.at_level("WARNING"):
        counts = backup(store, tmp_path / "bak" / DAY2)
    assert (counts.linked, counts.copied, counts.damaged) == (0, 1, 1)
    good = tmp_path / "bak" / DAY2 / blob.relative_to(store.dir)
    assert good.read_bytes() == b"the bytes" and good.stat().st_nlink == 1
    assert str(bad) in caplog.text and "does not match its name" in caplog.text
    assert str(counts).endswith(", 1 damaged there copied afresh")


def test_a_file_another_user_owns_is_copied(store, tmp_path, monkeypatch):
    put(store, b"photo")
    backup(store, tmp_path / "bak" / DAY1)
    monkeypatch.setattr(
        backup_files.os, "getuid", lambda: os.stat(store.dir).st_uid + 1
    )
    counts = backup(store, tmp_path / "bak" / DAY2)
    assert (counts.linked, counts.copied) == (0, 1)


@pytest.mark.parametrize("which", ["files", "folder"])
def test_a_base_with_a_symlinked_folder_is_not_linked_from(store, tmp_path, which):
    blob = put(store, b"photo")
    backup(store, tmp_path / "bak" / DAY1)
    real = tmp_path / "bak" / DAY1 / "files"
    if which == "folder":
        real = real / blob.parent.name
    real.rename(tmp_path / "elsewhere")
    real.symlink_to(tmp_path / "elsewhere")
    counts = backup(store, tmp_path / "bak" / DAY2)
    assert counts.base == tmp_path / "bak" / DAY1
    assert (counts.linked, counts.copied) == (0, 1)


def test_a_symlinked_run_is_not_a_base(store, tmp_path):
    put(store, b"photo")
    backup(store, tmp_path / "bak" / DAY1)
    backup(store, tmp_path / "other" / DAY2)
    (tmp_path / "bak" / DAY2).symlink_to(tmp_path / "other" / DAY2)
    assert backup(store, tmp_path / "bak" / DAY3).base == tmp_path / "bak" / DAY1


def test_a_copy_cut_short_leaves_nothing_a_re_run_would_skip(
    store, tmp_path, monkeypatch
):
    blob = put(store, b"photo")
    real = backup_files.shutil.copy2

    def cut_short(src, dst):
        Path(dst).write_bytes(b"ph")
        raise KeyboardInterrupt

    monkeypatch.setattr(backup_files.shutil, "copy2", cut_short)
    with pytest.raises(KeyboardInterrupt):
        backup(store, tmp_path / "bak" / DAY1)
    folder = tmp_path / "bak" / DAY1 / blob.relative_to(store.dir).parent
    assert list(folder.iterdir()) == []
    monkeypatch.setattr(backup_files.shutil, "copy2", real)
    backup(store, tmp_path / "bak" / DAY1)
    assert (folder / blob.name).read_bytes() == b"photo"
