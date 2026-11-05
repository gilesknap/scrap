"""Five-field cron schedules, as a Kubernetes CronJob reads them, for scrap schedule."""

from collections.abc import Sequence
from datetime import datetime

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
FIELDS = ((0, 59, []), (0, 23, []), (1, 31, []), (1, 12, MONTHS), (0, 7, DAYS))


def _value(text: str, low: int, names: Sequence[str]) -> int:
    if text.lower() in names:
        return names.index(text.lower()) + low
    return int(text)


def _field(text: str, low: int, high: int, names: Sequence[str]) -> set[int]:
    found: set[int] = set()
    for part in text.split(","):
        span, _, step = part.partition("/")
        if span in ("*", "?"):
            start, end = low, high
        elif "-" in span:
            first, last = span.split("-", 1)
            start, end = _value(first, low, names), _value(last, low, names)
        else:
            start = _value(span, low, names)
            end = high if step else start
        by = int(step) if step else 1
        if not (low <= start <= end <= high) or by < 1:
            raise ValueError(f"out of range: {part!r}")
        found.update(range(start, end + 1, by))
    return found


class Cron:
    """A schedule. ValueError if it is not one."""

    def __init__(self, text: str):
        fields = NAMED.get(text.strip().lower(), text).split()
        if len(fields) != 5:
            raise ValueError(f"not a five-field schedule: {text!r}")
        try:
            sets = [_field(f, *spec) for f, spec in zip(fields, FIELDS, strict=True)]
        except ValueError as error:
            raise ValueError(f"not a schedule: {text!r}: {error}") from None
        self.minute, self.hour, self.day, self.month, self.weekday = sets
        if 7 in self.weekday:
            self.weekday = (self.weekday - {7}) | {0}
        # As cron: with both day fields restricted, either may match
        self.any_day = fields[2] in ("*", "?")
        self.any_weekday = fields[4] in ("*", "?")

    def matches(self, at: datetime) -> bool:
        if at.minute not in self.minute or at.hour not in self.hour:
            return False
        if at.month not in self.month:
            return False
        day = at.day in self.day
        weekday = (at.weekday() + 1) % 7 in self.weekday  # Python's Monday is 0
        if self.any_day or self.any_weekday:
            return day and weekday
        return day or weekday
