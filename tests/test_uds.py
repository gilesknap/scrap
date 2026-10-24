import fcntl
import os
import socket
import stat
import subprocess
import sys
import time

import pytest

from scrap.__main__ import main
from scrap.uds import UdsError, bind


def mode(path):
    return stat.S_IMODE(path.lstat().st_mode)


def test_socket_is_600_in_a_new_700_folder(tmp_path):
    path = tmp_path / "run" / "scrap.sock"
    with bind(path):
        assert stat.S_ISSOCK(path.lstat().st_mode)
        assert mode(path) == 0o600
        assert mode(path.parent) == 0o700


def test_stale_socket_is_replaced(tmp_path):
    (tmp_path / "run").mkdir(mode=0o700)
    path = tmp_path / "run" / "scrap.sock"
    with socket.socket(socket.AF_UNIX) as old:
        old.bind(str(path))  # left behind: nobody listens on it any more
    with bind(path) as sock, socket.socket(socket.AF_UNIX) as client:
        client.connect(str(path))
        sock.accept()[0].close()


def test_socket_in_use_is_refused(tmp_path):
    path = tmp_path / "run" / "scrap.sock"
    with bind(path), pytest.raises(UdsError, match="in use"):
        bind(path)


def test_busy_live_socket_is_never_removed(tmp_path):
    """A listener whose queue is full does not answer, but it is not stale."""
    (tmp_path / "run").mkdir(mode=0o700)
    path = tmp_path / "run" / "scrap.sock"
    with socket.socket(socket.AF_UNIX) as live:
        live.bind(str(path))
        live.listen(0)
        waiting = []
        try:
            while True:  # fill the queue without accepting
                client = socket.socket(socket.AF_UNIX)
                client.setblocking(False)
                waiting.append(client)
                client.connect(str(path))
        except BlockingIOError:
            pass
        try:
            with pytest.raises(UdsError, match="may be in use"):
                bind(path)
        finally:
            for client in waiting:
                client.close()
        assert stat.S_ISSOCK(path.lstat().st_mode)
        assert live.getsockname() == str(path)


def test_setup_by_another_process_is_refused(tmp_path):
    (tmp_path / "run").mkdir(mode=0o700)
    path = tmp_path / "run" / "scrap.sock"
    with open(tmp_path / "run" / ".scrap.sock.lock", "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        with pytest.raises(UdsError, match="another process"):
            bind(path)
    assert not path.exists()


def test_too_long_path_is_refused_before_making_anything(tmp_path):
    folder = tmp_path / ("d" * 120)
    with pytest.raises(UdsError, match="longer than 107 bytes"):
        bind(folder / "scrap.sock")
    assert not folder.exists()


def test_folder_that_cannot_be_made_is_an_error(tmp_path):
    (tmp_path / "file").write_text("")
    with pytest.raises(UdsError, match="cannot make"):
        bind(tmp_path / "file" / "run" / "scrap.sock")


def test_symlinked_folder_is_refused(tmp_path):
    (tmp_path / "real").mkdir(mode=0o700)
    (tmp_path / "run").symlink_to(tmp_path / "real")
    with pytest.raises(UdsError, match="not a folder"):
        bind(tmp_path / "run" / "scrap.sock")
    assert list((tmp_path / "real").iterdir()) == []


def test_symlink_at_the_socket_path_is_refused_and_kept(tmp_path):
    (tmp_path / "run").mkdir(mode=0o700)
    path = tmp_path / "run" / "scrap.sock"
    path.symlink_to(tmp_path / "elsewhere.sock")
    with pytest.raises(UdsError, match="not a socket"):
        bind(path)
    assert path.is_symlink()


def test_non_socket_is_refused_and_kept(tmp_path):
    (tmp_path / "run").mkdir(mode=0o700)
    path = tmp_path / "run" / "scrap.sock"
    path.write_text("mine")
    with pytest.raises(UdsError, match="not a socket"):
        bind(path)
    assert path.read_text() == "mine"


def test_folder_open_to_others_is_refused(tmp_path):
    (tmp_path / "run").mkdir(mode=0o755)
    os.chmod(tmp_path / "run", 0o755)
    with pytest.raises(UdsError, match="open to other users"):
        bind(tmp_path / "run" / "scrap.sock")
    assert not (tmp_path / "run" / "scrap.sock").exists()


@pytest.mark.parametrize("extra", [["--host", "0.0.0.0"], ["--port", "9000"]])
def test_uds_with_host_or_port_is_an_error(tmp_path, monkeypatch, capsys, extra):
    monkeypatch.setattr("uvicorn.run", lambda *a, **kw: pytest.fail("ran uvicorn"))
    with pytest.raises(SystemExit) as exit:
        main(["serve", "--uds", str(tmp_path / "run" / "scrap.sock"), *extra])
    assert exit.value.code == 2
    assert "drop --host/--port" in capsys.readouterr().err
    assert not (tmp_path / "run").exists()


def test_serve_defaults_to_loopback_tcp(monkeypatch):
    calls = []
    monkeypatch.setattr("uvicorn.run", lambda *a, **kw: calls.append(kw))
    main(["serve"])
    assert calls == [{"factory": True, "host": "127.0.0.1", "port": 8000}]


def test_app_answers_over_the_socket(tmp_path):
    path = tmp_path / "run" / "scrap.sock"
    cmd = [sys.executable, "-m", "scrap", "serve", "--uds", str(path)]
    cmd += ["--data-dir", str(tmp_path / "data")]
    with subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True) as server:
        try:
            client = socket.socket(socket.AF_UNIX)
            deadline = time.monotonic() + 60  # a slow CI runner
            while True:
                try:
                    client.connect(str(path))
                    break
                except OSError:
                    if server.poll() is not None:
                        pytest.fail(server.communicate()[1])
                    if time.monotonic() > deadline:
                        pytest.fail("scrap did not listen on the socket")
                    time.sleep(0.1)
            with client:
                client.sendall(b"GET /healthz HTTP/1.1\r\nHost: x\r\n\r\n")
                reply = client.recv(4096)
            assert reply.startswith(b"HTTP/1.1 200")
            assert mode(path) == 0o600
        finally:
            server.terminate()
            server.communicate(timeout=10)


needs_non_root = pytest.mark.skipif(
    os.geteuid() == 0, reason="root ignores directory permissions"
)


@needs_non_root
def test_folder_without_write_permission_is_an_error(tmp_path):
    (tmp_path / "run").mkdir(mode=0o500)
    with pytest.raises(UdsError, match=r"cannot open .*\.scrap\.sock\.lock"):
        bind(tmp_path / "run" / "scrap.sock")


def test_lock_path_that_is_a_folder_is_an_error(tmp_path):
    (tmp_path / "run").mkdir(mode=0o700)
    (tmp_path / "run" / ".scrap.sock.lock").mkdir()
    with pytest.raises(UdsError, match=r"cannot open .*\.scrap\.sock\.lock"):
        bind(tmp_path / "run" / "scrap.sock")


def test_symlinked_lock_is_not_followed(tmp_path):
    (tmp_path / "run").mkdir(mode=0o700)
    target = tmp_path / "elsewhere"
    (tmp_path / "run" / ".scrap.sock.lock").symlink_to(target)
    with pytest.raises(UdsError, match="symbolic link"):
        bind(tmp_path / "run" / "scrap.sock")
    assert not target.exists()


@needs_non_root
def test_stale_socket_that_cannot_be_removed_is_an_error(tmp_path):
    folder = tmp_path / "run"
    folder.mkdir(mode=0o700)
    path = folder / "scrap.sock"
    (folder / ".scrap.sock.lock").touch()  # so the lock opens in a read-only folder
    with socket.socket(socket.AF_UNIX) as old:
        old.bind(str(path))
    folder.chmod(0o500)
    try:
        with pytest.raises(UdsError, match="cannot remove the old socket"):
            bind(path)
    finally:
        folder.chmod(0o700)
    assert stat.S_ISSOCK(path.lstat().st_mode)


def test_chmod_failure_is_an_error_and_leaves_no_socket(tmp_path, monkeypatch):
    def refuse(path, mode):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr("scrap.uds.os.chmod", refuse)
    path = tmp_path / "run" / "scrap.sock"
    with pytest.raises(UdsError, match="cannot set the mode"):
        bind(path)
    assert not path.exists()


def test_lock_error_reaches_serve_as_a_message(tmp_path, monkeypatch):
    monkeypatch.setattr("uvicorn.run", lambda *a, **kw: pytest.fail("ran uvicorn"))
    (tmp_path / "run").mkdir(mode=0o700)
    (tmp_path / "run" / ".scrap.sock.lock").mkdir()
    with pytest.raises(SystemExit) as exit:
        main(["serve", "--uds", str(tmp_path / "run" / "scrap.sock")])
    assert str(exit.value).startswith("scrap serve: cannot open")
