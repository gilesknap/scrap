"""The spend ledger and its limits: every paid model call passes through here.

A call site asks admit() for a Ticket, in the transaction that records the call, before
it calls; claude.complete() refuses to run without one. admit() refuses when the call's
worst case would take the month past SCRAP_MONTHLY_CAP_USD (or the day is over
SCRAP_BUDGET_DAY_USD), and otherwise reserves that worst case in the `spend` table, so a
second caller sees it at once. settle(), in the transaction that records the result,
replaces the reservation with what the call cost. A row is settled once (an attempt id
is one call), and the table is append-only, so a purge or a retry never changes what
was spent. See docs/explanations/ingest.md.
"""

import json
import logging
import math
import os
import sqlite3
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

__all__ = [
    "RefusedError",
    "Ticket",
    "admit",
    "cost_microusd",
    "notify",
    "recover",
    "report",
    "settle",
    "summary",
    "unmetered",
]

log = logging.getLogger(__name__)

# Dollars per million tokens: input, output, cache write (5 min), cache read.
# SCRAP_PRICES adds or replaces models, e.g. {"claude-opus-5-5": [4, 20, 5, 0.2]}.
# A model missing from both is costed as DEAREST and its rows flagged 'unpriced'.
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5-5": (4.0, 20.0, 5.0, 0.2),
}
DEAREST = (10.0, 50.0, 12.5, 0.25)
MIN_OUTPUT = 1024  # a per-call ceiling that leaves fewer output tokens refuses the call
WARN_AT = 0.8  # of the monthly cap: one notice a month


class RefusedError(Exception):
    """admit() said no: reason is 'cap' (the month), 'budget' (the day) or 'ceiling'
    (one call could cost more than SCRAP_CALL_CAP_USD)."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class Ticket:
    """Leave to make one call: its attempt id, the max_tokens it must send (a per-call
    ceiling may lower it) and the worst case reserved for it, in micro-dollars."""

    attempt: str
    max_tokens: int
    estimate: int


def unmetered(max_tokens: int) -> Ticket:
    """A ticket outside any database: only `scrap ingest-once`, a manual test call."""
    return Ticket("unmetered", max_tokens, 0)


# ---- settings


def _usd(name: str, default: str) -> int:
    """A dollar setting in micro-dollars (0: none)."""
    value = os.environ.get(name, default) or "0"
    try:
        usd = float(value)
    except ValueError:
        usd = -1.0
    if not math.isfinite(usd) or usd < 0:
        raise SystemExit(f"{name} must be a number of dollars, not {value!r}")
    return round(usd * 1e6)


def monthly_cap() -> int:
    """SCRAP_MONTHLY_CAP_USD in micro-dollars; 0 means no cap."""
    return _usd("SCRAP_MONTHLY_CAP_USD", "20")


def day_budget() -> int:
    """SCRAP_BUDGET_DAY_USD in micro-dollars; 0 means no daily budget."""
    return _usd("SCRAP_BUDGET_DAY_USD", "3")


def call_ceiling() -> int:
    """SCRAP_CALL_CAP_USD in micro-dollars; 0 (the default) means none."""
    return _usd("SCRAP_CALL_CAP_USD", "0")


def prices() -> dict[str, tuple[float, float, float, float]]:
    """PRICES with SCRAP_PRICES applied."""
    raw = os.environ.get("SCRAP_PRICES")
    if not raw:
        return dict(PRICES)
    try:
        extra = json.loads(raw)
        table = {
            str(model): tuple(float(p) for p in four) for model, four in extra.items()
        }
        if not all(
            len(p) == 4 and all(math.isfinite(x) and x >= 0 for x in p)
            for p in table.values()
        ):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise SystemExit(
            "SCRAP_PRICES must be JSON like"
            ' {"model": [input, output, cache write, cache read]} in $ per Mtok'
        ) from None
    return {**PRICES, **table}  # type: ignore[dict-item]


def check_settings() -> None:
    """Fail at start, not at the first call, on a malformed setting."""
    for check in (monthly_cap, day_budget, call_ceiling, prices):
        check()


def price(model: str) -> tuple[tuple[float, float, float, float], bool]:
    """A model's prices, and whether it is in the table (else DEAREST)."""
    table = prices()
    return (table[model], True) if model in table else (DEAREST, False)


def cost_microusd(model: str, usage: dict[str, Any]) -> int:
    """What a call cost, in millionths of a dollar, from its usage block."""
    (p_in, p_out, write, read), _ = price(model)
    total = (
        (usage.get("input_tokens") or 0) * p_in
        + (usage.get("output_tokens") or 0) * p_out
        + (usage.get("cache_creation_input_tokens") or 0) * write
        + (usage.get("cache_read_input_tokens") or 0) * read
    )
    return math.ceil(total)  # tokens x $/Mtok = micro-dollars


def worst_case(model: str, input_tokens: int, max_tokens: int) -> int:
    """The most a call can cost: every input token at the dearer of input and cache
    write, and every allowed output token."""
    (p_in, p_out, write, _), _ = price(model)
    return math.ceil(input_tokens * max(p_in, write) + max_tokens * p_out)


# ---- time (UTC)


def month_of(stamp: str) -> str:
    return stamp[:7]


def month_start(stamp: str) -> str:
    return stamp[:7] + "-01T00:00:00.000Z"


def next_month(stamp: str) -> str:
    year, month = int(stamp[:4]), int(stamp[5:7])
    t = datetime(year + month // 12, month % 12 + 1, 1, tzinfo=UTC)
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def day_start(stamp: str) -> str:
    return stamp[:10] + "T00:00:00.000Z"


def spent(conn: sqlite3.Connection, since: str, until: str | None = None) -> int:
    """Micro-dollars counted for calls admitted in [since, until): settled costs and
    the worst case of calls still in flight."""
    return conn.execute(
        "SELECT coalesce(sum(cost_microusd), 0) FROM spend WHERE at >= ? AND at < ?",
        (since, until or "9999"),
    ).fetchone()[0]


# ---- the choke point


def admit(
    conn: sqlite3.Connection,
    *,
    attempt: str,
    purpose: str,
    model: str,
    input_tokens: int,
    max_tokens: int,
    stamp: str,
    run_id: int | None = None,
) -> Ticket:
    """Reserve a call's worst case, or raise RefusedError. Call it inside BEGIN
    IMMEDIATE (store.transaction), so two callers cannot both take the last of the cap.
    An attempt admitted already gets its ticket back and nothing more is reserved."""
    if not conn.in_transaction:
        raise RuntimeError("admit() needs a write transaction")
    row = conn.execute(
        "SELECT estimate_microusd, cost_microusd FROM spend WHERE attempt = ?",
        (attempt,),
    ).fetchone()
    if row is not None:
        return Ticket(attempt, max_tokens, row[0])
    estimate = worst_case(model, input_tokens, max_tokens)
    ceiling = call_ceiling()
    if ceiling and estimate > ceiling:
        (p_in, p_out, write, _), _ = price(model)
        fit = int((ceiling - input_tokens * max(p_in, write)) // p_out)
        if fit < MIN_OUTPUT:
            raise RefusedError(
                "ceiling",
                f"one call could cost more than the ${ceiling / 1e6:.2f} per-call cap",
            )
        max_tokens = min(max_tokens, fit)
        estimate = worst_case(model, input_tokens, max_tokens)
    cap, budget = monthly_cap(), day_budget()
    if cap:
        month = spent(conn, month_start(stamp))
        if month + estimate > cap:
            raise RefusedError(
                "cap", f"this month's spend has reached the ${cap / 1e6:.2f} cap"
            )
    if budget and spent(conn, day_start(stamp)) >= budget:
        raise RefusedError("budget", "today's budget is spent")
    conn.execute(
        "INSERT INTO spend (attempt, purpose, model, run_id, state, estimate_microusd,"
        " cost_microusd, at) VALUES (?, ?, ?, ?, 'reserved', ?, ?, ?)",
        (attempt, purpose, model, run_id, estimate, estimate, stamp),
    )
    return Ticket(attempt, max_tokens, estimate)


def settle(
    conn: sqlite3.Connection,
    attempt: str,
    stamp: str,
    *,
    model: str | None = None,
    usage: dict[str, Any] | None = None,
    billed: bool = True,
) -> list[str]:
    """Record what a call cost, in the transaction that records its result: from its
    usage; with no usage, nothing if it surely was not billed (billed=False: refused
    before any work), else its reserved worst case, flagged 'estimated'. A second
    settle of an attempt changes nothing. Returns the notices now due (see due())."""
    row = conn.execute(
        "SELECT model, estimate_microusd FROM spend"
        " WHERE attempt = ? AND state = 'reserved'",
        (attempt,),
    ).fetchone()
    if row is None:
        return []  # settled already, or never admitted (unmetered)
    model = model or str(row["model"])
    if usage is not None:
        _, known = price(model)
        cost, flag = cost_microusd(model, usage), None if known else "unpriced"
    elif billed:
        cost, flag, usage = row["estimate_microusd"], "estimated", {}
    else:
        cost, flag, usage = 0, None, {}
    conn.execute(
        "UPDATE spend SET state = 'settled', model = ?, cost_microusd = ?, flag = ?,"
        " input_tokens = ?, output_tokens = ?, cache_write_tokens = ?,"
        " cache_read_tokens = ?, settled_at = ?"
        " WHERE attempt = ? AND state = 'reserved'",
        (
            model,
            cost,
            flag,
            usage.get("input_tokens") or 0,
            usage.get("output_tokens") or 0,
            usage.get("cache_creation_input_tokens") or 0,
            usage.get("cache_read_input_tokens") or 0,
            stamp,
            attempt,
        ),
    )
    return due(conn, stamp)


def recover(conn: sqlite3.Connection, stamp: str, attempts: list[str]) -> list[str]:
    """Settle these reservations (calls whose answer was lost: a crash, a shutdown)
    at their worst case, flagged: they may have been billed. Returns the notices due."""
    levels: list[str] = []
    for attempt in attempts:
        levels += [x for x in settle(conn, attempt, stamp) if x not in levels]
    return levels


def due(conn: sqlite3.Connection, stamp: str, *, capped: bool = False) -> list[str]:
    """The notices to send now, each recorded so it is sent once a month: 'warn' when
    the month's spend reaches 80% of the cap, 'cap' when it reaches the cap (or a
    call was refused for it: capped)."""
    cap = monthly_cap()
    if not cap:
        return []
    month = spent(conn, month_start(stamp))
    levels = [("warn", month >= WARN_AT * cap), ("cap", capped or month >= cap)]
    new = []
    for level, reached in levels:
        if (
            reached
            and conn.execute(
                "INSERT INTO spend_notice VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
                (month_of(stamp), level, stamp),
            ).rowcount
        ):
            new.append(level)
    return new


def notify(levels: list[str]) -> None:
    """Send the notices due (after their transaction commits): fixed text, amounts
    only."""
    url = os.environ.get("SCRAP_NOTIFY_URL")
    if not url or not levels:
        return
    cap = monthly_cap() / 1e6
    for level in levels:
        if level == "warn":
            message = (
                f"scrap: Claude spend this month passed 80% of the ${cap:.2f} cap."
            )
        else:
            message = (
                f"scrap: Claude ingest paused: this month's spend reached the"
                f" ${cap:.2f} cap. Photos stay queued until next month or a higher cap."
            )
        post(url, message)


def post(url: str, message: str) -> None:
    try:
        urllib.request.urlopen(url, message.encode(), timeout=10).close()
    except Exception as error:  # noqa: BLE001  a lost notice must not stop the worker
        log.warning("notification failed (%s)", type(error).__name__)


# ---- reading it


def summary(conn: sqlite3.Connection, stamp: str) -> dict[str, Any]:
    """Spend today and this month (UTC), and the limits, for GET /api/ingest."""
    cap, budget = monthly_cap(), day_budget()
    month = spent(conn, month_start(stamp))
    return {
        "spent_today_usd": spent(conn, day_start(stamp)) / 1e6,
        "spent_month_usd": month / 1e6,
        "monthly_cap_usd": cap / 1e6 if cap else None,
        "budget_day_usd": budget / 1e6 if budget else None,
        "capped": bool(cap) and month >= cap,
    }


def report(conn: sqlite3.Connection, month: str) -> str:
    """`scrap spend`: a month's spend by day and model, as text."""
    start = month + "-01T00:00:00.000Z"
    rows = conn.execute(
        "SELECT substr(at, 1, 10) AS day, model, count(*) AS calls,"
        " sum(cost_microusd) AS cost, sum(state = 'reserved') AS open,"
        " sum(flag IS NOT NULL) AS flagged FROM spend WHERE at >= ? AND at < ?"
        " GROUP BY day, model ORDER BY day, model",
        (start, next_month(start)),
    ).fetchall()
    cap = monthly_cap()
    lines = [f"Claude spend, {month} (UTC)"]
    if rows:
        width = max(len("model"), *(len(r["model"]) for r in rows))
        lines.append(f"{'day':<10}  {'model':<{width}}  {'calls':>5}  {'cost':>9}")
        for r in rows:
            note = " (in flight)" if r["open"] else ""
            note += f" ({r['flagged']} estimated or unpriced)" if r["flagged"] else ""
            lines.append(
                f"{r['day']:<10}  {r['model']:<{width}}  {r['calls']:>5}"
                f"  ${r['cost'] / 1e6:>8.4f}{note}"
            )
    by_model: dict[str, int] = {}
    for r in rows:
        by_model[r["model"]] = by_model.get(r["model"], 0) + r["cost"]
    for model, cost in sorted(by_model.items()):
        lines.append(f"{model}: ${cost / 1e6:.4f}")
    total = sum(by_model.values())
    of_cap = f" of the ${cap / 1e6:.2f} cap ({total / cap:.0%})" if cap else " (no cap)"
    calls = sum(r["calls"] for r in rows)
    lines.append(f"total: ${total / 1e6:.4f}{of_cap}, {calls} calls")
    return "\n".join(lines)
