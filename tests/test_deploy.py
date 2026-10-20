import os
import subprocess
import time
from pathlib import Path

DEPLOY = Path(__file__).parents[1] / "deploy"


def test_backup_retention():
    """deploy/test-retention.sh checks the backup pruning in deploy/scrap-backup."""
    result = subprocess.run(
        [DEPLOY / "test-retention.sh"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _gc_run(tmp_path, backups_age_min=None):
    """deploy/scrap-gc with a fake podman that records its arguments."""
    tmp_path.mkdir()
    fake = tmp_path / "bin"
    fake.mkdir(exist_ok=True)
    (fake / "podman").write_text(f'#!/bin/sh\necho "$@" > {tmp_path}/args\n')
    (fake / "podman").chmod(0o755)
    backups = tmp_path / "backups"
    backups.mkdir(exist_ok=True)
    if backups_age_min is not None:
        run = backups / "20261019T033000Z"
        run.mkdir()
        t = time.time() - backups_age_min * 60
        os.utime(run, (t, t))
    env = {
        **os.environ,
        "PATH": f"{fake}:{os.environ['PATH']}",
        "SCRAP_BACKUPS": str(backups),
        "SCRAP_DATA": str(tmp_path / "data"),
        "SCRAP_IMAGE": "localhost/scrap:test",
    }
    result = subprocess.run(
        [DEPLOY / "scrap-gc"], env=env, capture_output=True, text=True
    )
    return result, (tmp_path / "args").read_text()


def test_gc_deletes_only_after_a_recent_backup(tmp_path):
    result, args = _gc_run(tmp_path / "a", backups_age_min=60)
    assert result.returncode == 0, result.stderr
    assert args.split()[-4:] == ["gc", "--delete", "--grace-hours", "24"]
    assert "--network=none" in args.split()


def test_gc_waits_for_a_backup_and_skips_missed_nights():
    service = (DEPLOY / "scrap-gc.service").read_text()
    timer = (DEPLOY / "scrap-gc.timer").read_text()
    assert "After=scrap-backup.service" in service.splitlines()
    assert "Persistent=false" in timer.splitlines()
    backup = (DEPLOY / "scrap-backup").read_text()
    assert "--network=none" in backup


def test_gc_without_a_recent_backup_only_counts_and_fails(tmp_path):
    for case, age in (("old", 27 * 60), ("none", None)):
        result, args = _gc_run(tmp_path / case, backups_age_min=age)
        assert result.returncode == 1
        assert "--dry-run" in args.split() and "--delete" not in args.split()
        assert "No backup in the last 26 hours" in result.stderr
