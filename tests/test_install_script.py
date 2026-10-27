"""commands/install.sh installs the commands of the ref it was released at (M3, #238):
the release job rewrites its `default_ref=main` line to the tag."""

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "commands" / "install.sh"


def run(script: Path, tmp_path: Path, **env: str) -> str:
    """Run the script with a curl that records the URL and a tar that does nothing."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "curl").write_text(f'#!/bin/sh\necho "$@" >> {tmp_path}/urls\n')
    (bin_dir / "tar").write_text("#!/bin/sh\ncat >/dev/null\n")
    for tool in ("curl", "tar"):
        (bin_dir / tool).chmod(0o755)
    cmds = tmp_path / "cmds"
    path = f"{bin_dir}:/usr/bin:/bin"
    subprocess.run(
        ["sh", str(script)],
        env={"PATH": path, "CLAUDE_COMMANDS_DIR": str(cmds), "HOME": str(tmp_path)}
        | env,
        capture_output=True,
        text=True,
        check=False,
    )
    return (tmp_path / "urls").read_text()


def test_from_the_repo_it_installs_main(tmp_path):
    assert run(SCRIPT, tmp_path).strip().endswith("/archive/main.tar.gz")


def test_the_release_rewrite_pins_the_tag(tmp_path):
    """The sed and check of .github/workflows/_release.yml, as written there."""
    pinned = tmp_path / "install.sh"
    release = (SCRIPT.parents[1] / ".github/workflows/_release.yml").read_text()
    sed = next(
        line.strip() for line in release.splitlines() if line.strip().startswith("sed ")
    )
    sed = sed.replace("repo/commands/install.sh", str(SCRIPT)).replace(
        "> install.sh", f"> {pinned}"
    )
    done = subprocess.run(
        ["sh", "-c", sed.replace('\\$"', '$"')],
        env={"GITHUB_REF_NAME": "1.2.3", "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
    assert "\ndefault_ref=1.2.3\n" in pinned.read_text()
    assert run(pinned, tmp_path).strip().endswith("/archive/1.2.3.tar.gz")


def test_scrap_ref_overrides(tmp_path):
    assert run(SCRIPT, tmp_path, SCRAP_REF="x").strip().endswith("/archive/x.tar.gz")
