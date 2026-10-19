import subprocess
from pathlib import Path

DEPLOY = Path(__file__).parents[1] / "deploy"


def test_backup_retention():
    """deploy/test-retention.sh checks the backup pruning in deploy/scrap-backup."""
    result = subprocess.run(
        [DEPLOY / "test-retention.sh"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
