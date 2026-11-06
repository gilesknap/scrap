"""The commands only a Litestream install uses (ADR 46): db-init, schedule, db-hold."""

import os
from argparse import Namespace
from pathlib import Path
from typing import Any

__all__ = ["add_parsers", "run"]


def add_parsers(subparsers: Any, common: Any) -> None:
    subparsers.add_parser(
        "db-init",
        help="Before scrap starts with Litestream: put the database in place, or fail"
        " (the init container; ADR 46). Settings from the environment",
    )
    sched = subparsers.add_parser(
        "schedule",
        help="Run the jobs in $SCRAP_SCHEDULE on their schedules, beside the service"
        " (the pod's jobs container, with Litestream; ADR 46)",
    )
    sched.add_argument("--run", metavar="JOB", help="Run this job once, now, and stop")
    hold = subparsers.add_parser(
        "db-hold",
        parents=[common],
        help="Say what is keeping scrap gc to counting only on a Litestream install"
        " (an override used, a restore taken up); --clear once you have looked",
    )
    hold.add_argument("--clear", action="store_true", help="Let gc delete again")


def run(parsed: Namespace) -> bool:
    """Run one of them; False if parsed.command is not one."""
    if parsed.command == "db-init":
        from .dbinit import from_env

        print(f"scrap db-init: {from_env()}")
    elif parsed.command == "schedule":
        from .schedule import from_env as schedule

        schedule(parsed.run)
    elif parsed.command == "db-hold":
        from .dbstate import StateError, clear_hold, read_state

        data_dir = parsed.data_dir or Path(os.environ.get("SCRAP_DATA_DIR", "data"))
        try:
            print(clear_hold(data_dir) if parsed.clear else read_state(data_dir))
        except StateError as error:
            raise SystemExit(f"scrap db-hold: {error}") from None
    else:
        return False
    return True
