"""The search box's syntax (#84): words, "phrases", -word or !word (NOT), the filters
kind:, tag:, is:, after:, before:, date:, has:, image:, media:, later:, due: and
priority:, sort: and group:.
One pass over the text (the only regular expressions match one character), so no input
can make parsing take more than linear time."""

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

__all__ = [
    "Term", "Filter", "Query", "parse", "bound", "due", "KEYS", "SORTS", "PRIORITIES",
    "GROUPS", "MEDIA", "SUBTYPES", "subtype_of",
]  # fmt: skip

KEYS = (
    "kind", "tag", "is", "after", "before", "date", "has", "image", "media", "later",
    "due", "priority", "sort", "group",
)  # fmt: skip
# sort:K orders the results by K, the way it goes by default (True: highest first);
# -sort:K the other way. The store maps each to SQL (store.SORT_SQL): a new one slots in
# as a name here and a column there. due: soonest first; priority: high first; pages
# with none (and pages that are not todos) come last either way.
SORTS = {
    "updated": True, "created": True, "title": False, "due": False, "priority": True,
}  # fmt: skip
# group:G puts the results in sections, in the order they are shown (the PWA draws them;
# the server orders by the section first, so a page of results never splits one):
# letter (A-Z by title), tag (by sub-tag of the tag: filtered by), type (a Later's
# subtype), now (the Todos screen's ranking), due (by when due) and area (topic pages by
# their area, as GET /api/topics has them). The last one counts;
# group:none, or any other value, means none.
GROUPS = ("letter", "tag", "type", "now", "due", "area")
# A Later's medium (fields.media_type) and, derived from it, what it is for
# (fields.subtype): media:book finds a book, later:watch a film, show or video
SUBTYPES = ("read", "watch", "listen", "play")
MEDIA = {
    "book": "read", "article": "read", "film": "watch", "tv": "watch",
    "video": "watch", "podcast": "listen", "music": "listen", "game": "play",
}  # fmt: skip
# A todo's priorities, highest first (the page.priority column's CHECK has them too)
PRIORITIES = ("high", "medium", "low")
# due:D compares a todo's due day with D: a date, or one of these days from today
DAYS_FROM_TODAY = {"yesterday": -1, "today": 0, "tomorrow": 1}
COMPARE = ("<=", ">=", "<", ">", "=")  # longest first
DAYS = {"d": 1, "w": 7, "m": 30, "y": 365}  # after:2w, before:1y
MAX_AGO = 100  # 100y at most
END = "~"  # after every ISO 8601 timestamp, as text
WORD = re.compile(r"[^\W_]")  # a letter or digit: something FTS indexes (one character)
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
MAX_TERMS = 64  # every term adds a subquery; only abuse gets here
MAX_FILTERS = 64
NOT = "-!"


@dataclass(frozen=True)
class Term:
    text: str  # no double quotes in it
    phrase: bool = False
    neg: bool = False


@dataclass(frozen=True)
class Filter:
    key: str  # one of KEYS
    value: str  # lower case
    neg: bool
    token: str  # as typed, so the PWA can take it out of the query again


@dataclass
class Query:
    terms: list[Term] = field(default_factory=list)
    filters: list[Filter] = field(default_factory=list)
    # Terms and filters past MAX_TERMS and MAX_FILTERS, left out. The store refuses such
    # a query (a NOT word or -tag: left out would show more pages than asked for).
    dropped: int = 0

    @property
    def sort(self) -> tuple[str, bool] | None:
        """The order asked for, and whether highest first: the last sort: with a known
        value (another is ignored). None: the default (best match, or newest)."""
        for f in reversed(self.filters):
            if f.key == "sort" and f.value in SORTS:
                return f.value, SORTS[f.value] != f.neg
        return None

    @property
    def group(self) -> str | None:
        """The grouping asked for: the last group: with a known value (GROUPS)."""
        for f in reversed(self.filters):
            if f.key == "group" and not f.neg:
                return f.value if f.value in GROUPS else None
        return None

    @property
    def positive(self) -> list[Term]:
        return [t for t in self.terms if not t.neg]

    @property
    def negative(self) -> list[Term]:
        return [t for t in self.terms if t.neg]

    def fts(self, term: Term) -> str:
        """A term as an FTS5 string: a word as a prefix (what is typed so far, or the
        start of a longer word: vsc finds vscode), wherever it stands in the query; a
        NOT word and a phrase exactly."""
        star = "" if term.neg or term.phrase else "*"
        return f'"{term.text}"{star}'


def parse(text: str) -> Query:
    """The terms and filters of a query. Space between terms means AND."""
    s = CONTROL.sub(" ", text)
    n = len(s)
    q = Query()
    seen: set[Term] = set()
    i = 0
    while i < n:
        if s[i].isspace():
            i += 1
            continue
        start = i
        neg = s[i] in NOT
        if neg:
            i += 1
        if i < n and s[i] == '"':  # a phrase, to the next quote (or the end)
            end = s.find('"', i + 1)
            end = n if end < 0 else end
            body, i = s[i + 1 : end], end + 1
            add(q, seen, Term(" ".join(body.split()), True, neg))
            continue
        j = i
        while j < n and not s[j].isspace() and s[j] != '"':
            j += 1
        word = s[i:j]
        key, colon, value = word.partition(":")
        key = key.lower()
        if colon and key in KEYS:
            if not value and j < n and s[j] == '"':  # key:"a value with spaces"
                end = s.find('"', j + 1)
                end = n if end < 0 else end
                value, j = s[j + 1 : end], end + 1
            i = j
            value = " ".join(value.split()).lower()
            if value and len(q.filters) < MAX_FILTERS:
                q.filters.append(Filter(key, value, neg, s[start:i]))
            elif value:
                q.dropped += 1
            continue
        i = j
        add(q, seen, Term(word, False, neg))
    return q


def add(q: Query, seen: set[Term], term: Term) -> bool:
    """Keep a term FTS can match (a letter or digit in it), once, at most MAX_TERMS (the
    rest are counted in q.dropped)."""
    if not WORD.search(term.text) or term in seen:
        return False
    if len(q.terms) >= MAX_TERMS:
        q.dropped += 1
        return False
    seen.add(term)
    q.terms.append(term)
    return True


def bound(key: str, value: str, now: datetime | None = None) -> str | None:
    """Where after:value or before:value cuts, as a timestamp string to compare with a
    page's (UTC, ISO 8601): a date (a UTC day, both ends included: after:D from its
    start, before:D to its end) or a time ago (1d, 2w, 1m = 30 days, 1y = 365 days; 1
    if no number). None if the value is neither."""
    if len(value) == 10 and value[4] == "-" and value[7] == "-":
        try:
            day = date.fromisoformat(value)
            return (day + timedelta(days=key == "before")).isoformat()
        except ValueError:
            return None
        except OverflowError:  # before:9999-12-31: to the end of time
            return END
    count, unit = value[:-1] or "1", value[-1:]
    if (
        unit not in DAYS
        or not (count.isascii() and count.isdigit() and len(count) <= 3)
        or not 0 < int(count) <= MAX_AGO
    ):
        return None
    ago = (now or datetime.now(UTC)) - timedelta(days=int(count) * DAYS[unit])
    return ago.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def day(value: str) -> date | None:
    """A calendar day as YYYY-MM-DD (a due date's form), else None."""
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def due(value: str, today: date | None = None) -> tuple[str, str | None] | None:
    """What due:value asks of a todo's due day: (an operator, a YYYY-MM-DD day), or
    ("none", None) for due:none (no due date). The value is an optional <, <=, >, >=
    or =, then a date, today, tomorrow or yesterday as the server's own calendar has
    them (its local time zone, TZ), or days from today (7d, 2w, 1m = 30 days, 1y = 365
    days; 1 to 100): due:<today is overdue, due:<=7d is within a week. None if it is
    none of them."""
    if value == "none":
        return "none", None
    op = next((c for c in COMPARE if value.startswith(c)), "=")
    rest = value[len(op) :] if value.startswith(op) else value
    if rest in DAYS_FROM_TODAY:
        when = (today or date.today()) + timedelta(days=DAYS_FROM_TODAY[rest])
        return op, when.isoformat()
    when = day(rest)
    if when is None:  # days from today, as after: has them: 7d, 2w, 1m, 1y
        count, unit = rest[:-1] or "1", rest[-1:]
        if (
            unit not in DAYS
            or not (count.isascii() and count.isdigit() and len(count) <= 3)
            or not 0 < int(count) <= MAX_AGO
        ):
            return None
        when = (today or date.today()) + timedelta(days=int(count) * DAYS[unit])
    return op, when.isoformat()


def subtype_of(media_type: object) -> str:
    """What a Later is for, from its medium: read when it has none or an unknown one."""
    return MEDIA.get(str(media_type), "read")
