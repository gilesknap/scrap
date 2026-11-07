"""Five-field cron schedules, read as a Kubernetes CronJob reads them (robfig/cron v3's
ParseStandard, with its starBit rule for the two day fields), for scrap schedule.

Refused here though robfig takes them, so a bad schedule fails at install rather than
differing later: @every, a sign on a number (+5).
"""

import re
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

__all__ = ["Cron"]

NAMED = {
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}
MONTHS = "jan feb mar apr may jun jul aug sep oct nov dec".split()
DAYS = "sun mon tue wed thu fri sat".split()
# Each field's lowest and highest value, and its names (from the lowest)
FIELDS = ((0, 59, []), (0, 23, []), (1, 31, []), (1, 12, MONTHS), (0, 6, DAYS))
DIGITS = re.compile(r"[0-9]+")  # ASCII: not int()'s 1_0, +5 or other scripts' digits
SEARCH = timedelta(days=5 * 366)  # how far times() looks: past any leap day


def _number(text: str) -> int:
    if not DIGITS.fullmatch(text):
        raise ValueError(f"not a number: {text!r}")
    return int(text)


def _value(text: str, low: int, names: Sequence[str]) -> int:
    if text.lower() in names:
        return names.index(text.lower()) + low
    return _number(text)


def _part(
    part: str, low: int, high: int, names: Sequence[str]
) -> tuple[set[int], bool]:
    """One comma-separated part: its values, and whether it counts as a star: a `*` or
    `?` with no step over 1."""
    pieces = part.split("/")
    if len(pieces) > 2:
        raise ValueError(f"too many slashes: {part!r}")
    ends = pieces[0].split("-")
    star = ends[0] in ("*", "?")
    if star:
        start, end = low, high
    else:
        if len(ends) > 2:
            raise ValueError(f"too many hyphens: {part!r}")
        start = _value(ends[0], low, names)
        end = _value(ends[1], low, names) if len(ends) == 2 else start
    by = 1
    if len(pieces) == 2:
        by = _number(pieces[1])
        if len(ends) == 1:  # N/step means N-max/step
            end = high
        if by > 1:
            star = False
    if start < low or end > high or start > end or by == 0:
        raise ValueError(f"out of range: {part!r}")
    return set(range(start, end + 1, by)), star


def _field(
    text: str, low: int, high: int, names: Sequence[str]
) -> tuple[set[int], bool]:
    found: set[int] = set()
    star = False
    for part in text.split(","):
        if part:  # as robfig: empty parts are dropped, so 1,,2 is 1,2
            values, part_star = _part(part, low, high, names)
            found |= values
            star = star or part_star
    return found, star


class Cron:
    """A schedule. ValueError if it is not one."""

    def __init__(self, text: str):
        self.text = text
        fields = NAMED.get(text, text).split()
        if text.startswith("@") and text not in NAMED:
            raise ValueError(f"not a schedule this supports: {text!r}")
        if len(fields) != 5:
            raise ValueError(f"not a five-field schedule: {text!r}")
        try:
            parts = [_field(f, *spec) for f, spec in zip(fields, FIELDS, strict=True)]
        except ValueError as error:
            raise ValueError(f"not a schedule: {text!r}: {error}") from None
        self.minute, self.hour = parts[0][0], parts[1][0]
        self.day, self.any_day = parts[2]
        self.month = parts[3][0]
        self.weekday, self.any_weekday = parts[4]

    def matches(self, at: datetime) -> bool:
        return at.minute in self.minute and self._hour(at)

    def _hour(self, at: datetime) -> bool:
        """Whether it fires at all in at's hour."""
        if at.hour not in self.hour or at.month not in self.month:
            return False
        day = at.day in self.day
        weekday = (at.weekday() + 1) % 7 in self.weekday  # Python's Monday is 0
        if self.any_day or self.any_weekday:
            return day and weekday
        return day or weekday

    def times(
        self, start: datetime, zone: ZoneInfo | None = None, back: bool = False
    ) -> Iterator[datetime]:
        """The minutes it fires at, in UTC, walking real time as scrap schedule does:
        after start (aware), or with back at or before it, newest first. The schedule
        is read in zone (None: UTC). Stops SEARCH from start."""
        at = start.astimezone(UTC).replace(second=0, microsecond=0)
        step = timedelta(minutes=-1 if back else 1)
        if not back:
            at += step
        end = start - SEARCH if back else start + SEARCH
        while (at >= end) if back else (at <= end):
            local = at.astimezone(zone) if zone else at
            if not self._hour(
                local
            ):  # on to the next hour, or back to the last one's end
                skip = -(local.minute + 1) if back else 60 - local.minute
                at += timedelta(minutes=skip)
                continue
            if local.minute in self.minute:
                yield at
            at += step
