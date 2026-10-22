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
    assert f"{tmp_path / 'a' / 'data'}:/data:z" in args.split()


def test_gc_waits_for_a_backup_and_skips_missed_nights():
    service = (DEPLOY / "scrap-gc.service").read_text()
    timer = (DEPLOY / "scrap-gc.timer").read_text()
    assert "After=scrap-backup.service" in service.splitlines()
    assert "Persistent=false" in timer.splitlines()
    backup = (DEPLOY / "scrap-backup").read_text()
    assert "--network=none" in backup
    assert '--volume "$SCRAP_DATA:/data:z"' in backup


def test_gc_without_a_recent_backup_only_counts_and_fails(tmp_path):
    for case, age in (("old", 27 * 60), ("none", None)):
        result, args = _gc_run(tmp_path / case, backups_age_min=age)
        assert result.returncode == 1
        assert "--dry-run" in args.split() and "--delete" not in args.split()
        assert "No backup in the last 26 hours" in result.stderr


def _fake(bin_dir, name, script):
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / name).write_text(f"#!/bin/sh\n{script}\n")
    (bin_dir / name).chmod(0o755)


def _run_scrap(tmp_path, **settings):
    """deploy/scrap-run with a fake podman; returns (result, podman args)."""
    _fake(tmp_path / "bin", "podman", f'echo "$@" > {tmp_path}/args')
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith("SCRAP_")},
        "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}",
        "SCRAP_DATA": str(tmp_path / "data"),
        "SCRAP_IMAGE": "localhost/scrap:test",
        "SCRAP_MEMORY_MAX": "1g",
        "SCRAP_PORT": "8790",
        "RUNTIME_DIRECTORY": "/run/user/1000/scrap",
        **settings,
    }
    result = subprocess.run(
        [DEPLOY / "scrap-run"], env=env, capture_output=True, text=True
    )
    args = tmp_path / "args"
    return result, args.read_text().split() if args.exists() else []


def test_socket_mode_publishes_no_port(tmp_path):
    result, args = _run_scrap(tmp_path, SCRAP_LISTEN="socket")
    assert result.returncode == 0, result.stderr
    assert "--publish" not in args
    assert f"{tmp_path / 'data'}:/data:z" in args
    assert "/run/user/1000/scrap:/run/scrap:z" in args
    assert args[-3:] == ["serve", "--uds", "/run/scrap/scrap.sock"]


def test_tcp_mode_publishes_only_on_loopback(tmp_path):
    for case, settings in (("tcp", {"SCRAP_LISTEN": "tcp"}), ("unset", {})):
        result, args = _run_scrap(tmp_path / case, **settings)
        assert result.returncode == 0, result.stderr
        published = [args[i + 1] for i, a in enumerate(args) if a == "--publish"]
        assert published == ["127.0.0.1:8790:8000"]
        assert "--uds" not in args


def test_unknown_listen_mode_starts_nothing(tmp_path):
    result, args = _run_scrap(tmp_path, SCRAP_LISTEN="Socket")
    assert result.returncode == 1 and args == []
    assert "must be socket or tcp" in result.stderr


def test_unit_keeps_the_socket_folder_private():
    unit = (DEPLOY / "scrap.service").read_text()
    assert "RuntimeDirectoryMode=0700" in unit.splitlines()
    assert "--publish" not in unit


def _install(tmp_path, env_file=None):
    """deploy/install.sh with fakes for systemctl, loginctl and podman (no image,
    so it stops before starting anything)."""
    home = tmp_path / "home"
    conf = home / ".config" / "scrap"
    conf.mkdir(parents=True, exist_ok=True)
    if env_file is not None:
        (conf / "env").write_text(env_file)
    bin_dir = tmp_path / "bin"
    _fake(bin_dir, "systemctl", "exit 0")
    _fake(bin_dir, "loginctl", "echo yes")
    _fake(bin_dir, "podman", "exit 1")
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HOME": str(home),
        "XDG_RUNTIME_DIR": "/run/user/1000",
    }
    result = subprocess.run(
        [DEPLOY / "install.sh"], env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    return result, (conf / "env").read_text()


def test_new_install_listens_on_the_socket(tmp_path):
    result, env = _install(tmp_path)
    assert "SCRAP_LISTEN=socket" in env.splitlines()
    assert "any local user can reach" not in result.stderr
    result, again = _install(tmp_path)  # a re-run keeps the file
    assert again == env


def test_reinstall_with_an_old_env_file_stays_on_tcp(tmp_path):
    old = "SCRAP_IMAGE=localhost/scrap:dev\nSCRAP_PORT=8791\n"
    result, env = _install(tmp_path, old)
    assert env == old
    assert "port 8791 on 127.0.0.1, which any local user can reach" in result.stderr
    assert "SCRAP_LISTEN=socket" in result.stderr
    # scrap-run is installed; that it takes the missing setting as tcp is
    # test_tcp_mode_publishes_only_on_loopback's "unset" case
    assert (tmp_path / "home" / ".local" / "lib" / "scrap" / "scrap-run").exists()


def test_install_reads_the_env_file_as_systemd_does(tmp_path):
    for case, line in (
        ("quoted", 'SCRAP_LISTEN="socket"'),
        ("spaces", "SCRAP_LISTEN=socket  "),
    ):
        result, _ = _install(tmp_path / case, f"SCRAP_IMAGE=x\n{line}\n")
        assert "any local user can reach" not in result.stderr, case
    result, _ = _install(tmp_path / "bare", "SCRAP_IMAGE=x\n")
    assert "port 8790 on 127.0.0.1" in result.stderr  # scrap-run's default port


def test_install_copies_and_gates_the_related_timer(tmp_path):
    result, _ = _install(tmp_path)  # no image: it stops before enabling timers
    units = tmp_path / "home" / ".config" / "systemd" / "user"
    for name in ("scrap-enrich-related.service", "scrap-enrich-related.timer"):
        assert (units / name).read_text() == (DEPLOY / name).read_text()
    script = (DEPLOY / "install.sh").read_text()
    assert "enrich --help 2>/dev/null | grep -q -- --related" in script
    assert "enable --now scrap-enrich-related.timer" in script


def test_related_timer_runs_in_the_service_container_once_a_night():
    service = (DEPLOY / "scrap-enrich-related.service").read_text()
    timer = (DEPLOY / "scrap-enrich-related.timer").read_text()
    assert "ExecStart=/usr/bin/podman exec scrap scrap enrich --related" in service
    assert "Type=oneshot" in service and "Restart=" not in service  # no flapping
    assert "Requisite=scrap.service" in service
    assert "OnCalendar=*-*-* 03:41:00" in timer
