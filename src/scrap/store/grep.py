"""grep: pages whose raw text matches a pattern (#474), a substring or a regex.

The full-text index keeps only words, stemmed, so it cannot find punctuation or an
exact string (`|---|`, `foo_bar(`, an IP address). This scans the stored text
itself: a page's title, its Markdown body and the current text read from its files
(derived 'ocr'). A query's filters and words narrow the pages first, in its order.
A few thousand pages scan in well under a second, so there is no index (ADR 40).

A regex is RE2's (google-re2): it matches in linear time and its compile memory is
bounded (max_mem), so no pattern can hang the server or exhaust its memory; it has
no backreferences or lookaround.
"""

import json
import time
from bisect import bisect_right
from typing import Any

import re2

from ..query import Query
from .errors import InvalidError
from .grouping import use_areas
from .helpers import checked_query
from .search import SearchMixin

MAX_PATTERN = 200  # characters of a grep pattern
MAX_MEM = 8 << 20  # bytes RE2 may use to compile one pattern
SECONDS = 2.0  # the whole scan's budget, checked before each search
WINDOW = 16 << 10  # bytes of text a search finds a match starting in
AHEAD = 4 << 10  # bytes past its window a search reads to finish a match
MAX_LINES = 5  # matching lines returned a page
MAX_COUNT = 1000  # matching lines counted a page: match_count stops there
LINE = 200  # characters of a matching line returned
BATCH = 50  # pages read from the database at a time


def compile_pattern(pattern: str, is_regex: bool) -> Any:
    """A grep pattern compiled by RE2: a case-insensitive substring, or a regex in
    which ^ and $ match at each line. Refused if empty, too long or not a valid
    regex (RE2's syntax: no backreferences or lookaround)."""
    if not pattern:
        raise InvalidError("grep is empty")
    if len(pattern) > MAX_PATTERN:
        raise InvalidError(f"grep is over {MAX_PATTERN} characters")
    options = re2.Options()
    options.max_mem = MAX_MEM
    options.log_errors = False
    options.never_capture = True  # only where a match starts is used
    if not is_regex:
        options.literal = True
        options.case_sensitive = False
    try:
        return re2.compile(pattern if not is_regex else "(?m)" + pattern, options)
    except re2.error as e:
        why = e.args[0] if e.args else "?"
        why = why.decode(errors="replace") if isinstance(why, bytes) else str(why)
        raise InvalidError(f"invalid regex: {why.replace('(?m)', '', 1)}") from None


def clip(line: str, at: int) -> str:
    """A line cut to about LINE characters around position at (a match's start)."""
    if len(line) <= LINE:
        return line
    start = max(0, min(at - LINE // 4, len(line) - LINE))
    out = line[start : start + LINE]
    return ("…" if start else "") + out + ("…" if start + LINE < len(line) else "")


def late(deadline: float) -> None:
    """Refuse a scan past its budget."""
    if time.monotonic() > deadline:
        raise InvalidError(f"grep took over {SECONDS:g} seconds: narrow the query")


def scan(
    pat: Any, text: str, where: dict[str, Any], deadline: float
) -> tuple[list[dict[str, Any]], int]:
    """The lines of text a pattern matches (those a match starts on, matches not
    overlapping): the first MAX_LINES as {**where, line (1-based), text}, and how
    many, up to MAX_COUNT. The text is searched in windows of WINDOW bytes: a
    search takes the first match starting in its window, reading up to AHEAD bytes
    past it to finish one, and the next starts after the match (or its line), else
    at the next window. So each byte is read about once and one search costs at
    most WINDOW + AHEAD bytes; a match running more than AHEAD past its window's
    end may be missed or cut short. The deadline is checked before every search."""
    data = text.encode()  # RE2 works in UTF-8: once, not per search
    if not data:
        return [], 0
    end = len(data) - 1 if data.endswith(b"\n") else len(data)  # no line after it
    starts: list[int] = []  # each line's offset, once there is a match
    found: list[dict[str, Any]] = []
    count, pos = 0, 0
    while count < MAX_COUNT and pos <= end:
        late(deadline)
        stop = min(pos + WINDOW, len(data))
        while stop < len(data) and data[stop] & 0xC0 == 0x80:
            stop += 1  # not inside a character
        m = pat.search(data, pos, min(stop + AHEAD, len(data)))
        if m is None or m.start() > min(stop, end):
            if stop >= len(data):
                break
            pos = stop  # the next window
            continue
        if not starts:
            starts = [0]
            i = data.find(b"\n")
            while i >= 0:
                starts.append(i + 1)
                i = data.find(b"\n", i + 1)
        n = bisect_right(starts, m.start())
        count += 1
        begin = starts[n - 1]
        line_end = starts[n] - 1 if n < len(starts) else len(data)
        if len(found) < MAX_LINES:
            line = data[begin:line_end].decode(errors="replace")
            at = len(data[begin : m.start()].decode(errors="replace"))
            found.append({**where, "line": n, "text": clip(line, at)})
        pos = max(line_end + 1, m.end())
    return found, count


class GrepMixin(SearchMixin):
    def grep(
        self, query: str, pattern: str, is_regex: bool, limit: int, offset: int = 0
    ) -> list[dict[str, Any]]:
        """The pages a query finds (in its order; not in the trash; an empty query:
        every page, newest changed first) whose title, body or files' current text
        a pattern matches: search's rows, each with matches (its first matching
        lines, each with in: title, body or file, and a file's sha256) and
        match_count (matching lines, at most MAX_COUNT). Refused (InvalidError) for
        a bad pattern, or a scan over SECONDS."""
        pat = compile_pattern(pattern, is_regex)
        query = query or "sort:updated"
        q = checked_query(query)
        if not q.terms and not q.filters:  # as search: nothing to look for
            return []
        deadline = time.monotonic() + SECONDS
        found: dict[str, tuple[list[dict[str, Any]], int]] = {}
        ids = self._grep_order(q)
        for i in range(0, len(ids), BATCH):
            late(deadline)
            for page_id, texts in self._texts(ids[i : i + BATCH]):
                lines: list[dict[str, Any]] = []
                count = 0
                for where, text in texts:
                    got, n = scan(pat, text, where, deadline)
                    lines += got
                    count += n
                if count:
                    found[page_id] = lines[:MAX_LINES], min(count, MAX_COUNT)
                    if len(found) == offset + limit:
                        break
            if len(found) == offset + limit:
                break
        hits = list(found)[offset:]
        if not hits:
            return []
        rows = {r["id"]: r for r in self.search(query, len(hits), 0, hits)}
        return [
            rows[i] | {"matches": found[i][0], "match_count": found[i][1]}
            for i in hits
            if i in rows  # unless it went to the trash meanwhile
        ]

    def _grep_order(self, q: Query) -> list[str]:
        """The ids of the pages a query finds, in search's order."""
        where, args = self._where(q)
        order, section_args = self._order(q)
        with self.connect() as conn:
            if q.group == "area":
                use_areas(conn)
            if q.positive:  # ranked: a page at its best chunk, once
                rows = self._ranked(
                    conn, q, where, [*args, *section_args], order, "p.id"
                )
                return list(dict.fromkeys(r[0] for r in rows))
            return [r[0] for r in conn.execute(
                f"SELECT p.id FROM page p WHERE {where}"
                f" ORDER BY {order}p.updated_at DESC, p.id DESC",
                (*args, *section_args),
            )]  # fmt: skip

    def _texts(
        self, ids: list[str]
    ) -> list[tuple[str, list[tuple[dict[str, Any], str]]]]:
        """Each page's texts to scan, in the order of ids: its title, body and the
        current text read from each of its files (oldest capture first)."""
        out: dict[str, list[tuple[dict[str, Any], str]]] = {}
        pages = "(SELECT value FROM json_each(?))"
        with self.connect() as conn:
            for page_id, title, body in conn.execute(
                f"SELECT id, title, body FROM page WHERE id IN {pages}"
                " AND deleted_at IS NULL",
                (json.dumps(ids),),
            ):
                out[page_id] = [({"in": "title"}, title), ({"in": "body"}, body)]
            for page_id, sha, text in conn.execute(
                "SELECT c.page_id, d.source_sha256, d.text FROM derived d"
                " JOIN capture c ON c.id = d.capture_id"
                f" WHERE c.page_id IN {pages} AND d.kind = 'ocr'"
                " AND d.superseded_at IS NULL AND coalesce(d.text, '') <> ''"
                " ORDER BY c.received_at, d.id",
                (json.dumps(ids),),
            ):
                if page_id in out:
                    out[page_id].append(({"in": "file", "sha256": sha}, text))
        return [(i, out[i]) for i in ids if i in out]
