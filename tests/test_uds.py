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
            for _ in range(100):
                try:
                    client.connect(str(path))
                    break
                except OSError:
                    if server.poll() is not None:
                        pytest.fail(server.communicate()[1])
                    time.sleep(0.1)
            else:
                pytest.fail("scrap did not listen on the socket")
            with client:
                client.sendall(b"GET /healthz HTTP/1.1\r\nHost: x\r\n\r\n")
                reply = client.recv(4096)
            assert reply.startswith(b"HTTP/1.1 200")
            assert mode(path) == 0o600
        finally:
            server.terminate()
            server.communicate(timeout=10)
