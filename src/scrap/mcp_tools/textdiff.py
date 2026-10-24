"""Text edits and the unified diff an edit returns (edit_page, revert_text)."""

import difflib
from collections.abc import Iterator
from typing import Any

from ..store import MAX_PAGE, InvalidError, too_big
from .limits import CONTEXT, DIFF_WORK, MAX_DIFF


def overlapping(body: str, old: str) -> bool:
    """Whether two occurrences of old in body overlap ("aa" twice in "aaa"). Linear:
    an occurrence the leftmost-first scan (str.count's) skips starts inside a match
    it took, so each match's own span is searched once, and the spans are disjoint.
    """
    size = len(old)
    if size < 2:
        return False
    at = body.find(old)
    while at != -1:
        if body.find(old, at + 1, at + 2 * size - 1) != -1:
            return True
        at = body.find(old, at + size)
    return False


def replaced(body: str, old: str, new: str, every: bool) -> tuple[str, int]:
    """body with old, which must occur in it exactly once (or, with every, any number
    of times, none overlapping), replaced by new, and how many times. Refused
    (InvalidError) if not, or if the result would be over MAX_PAGE bytes: that is
    worked out from the count before anything is built, so no call can make a huge
    string. Linear in the body's length, whatever old is: this runs while the
    database's write lock is held."""
    n = body.count(old)  # non-overlapping
    if n == 0:
        raise InvalidError(
            "old is not in the page's body: read the page again and copy the text"
            " exactly (nothing was saved)"
        )
    if n > 1 and not every:
        raise InvalidError(
            f"old occurs {n} times in the body: give more of the text around it so it"
            " occurs once, or replace_all (nothing was saved)"
        )
    if overlapping(body, old):
        raise InvalidError(
            "old occurs in the body overlapping itself (as aa does twice in aaa): give"
            " more of the text around it so it occurs once (nothing was saved)"
        )
    size = len(body.encode()) + n * (len(new.encode()) - len(old.encode()))
    if size > MAX_PAGE:
        raise InvalidError(f"{too_big(size)} (nothing was saved)")
    return body.replace(old, new), n


def emptied(before: str, after: str, allow_empty: bool) -> None:
    """Refuse leaving a page's body with nothing in it, unless allow_empty."""
    if not allow_empty and before.strip() and not after.strip():
        raise InvalidError(
            "this would leave the page's body empty: give allow_empty if the user"
            " asked for that (nothing was saved)"
        )


def split_lines(value: str) -> list[str]:
    """Lines of a text, each keeping its \\n, split on \\n only (str.splitlines also
    splits on form feed, U+2028 and the like, which a diff reader does not)."""
    lines = [x + "\n" for x in value.split("\n")]
    lines[-1] = lines[-1][:-1]
    return lines if lines[-1] else lines[:-1]


class _WholeFileMatcher(difflib.SequenceMatcher):
    """Compares only the lines between the common start (top) and end of a and b,
    but reports opcodes for the whole files, so get_grouped_opcodes sees the common
    start and end as equal runs and gives each hunk its full context."""

    def __init__(self, a: list[str], b: list[str], top: int, end: int):
        super().__init__(None, a[top : len(a) - end], b[top : len(b) - end])
        self._a_len, self._b_len, self._top, self._end = len(a), len(b), top, end

    def get_opcodes(self) -> list[Any]:
        top, end = self._top, self._end
        codes: list[Any] = [("equal", 0, top, 0, top)] if top else []
        codes += [
            (tag, i1 + top, i2 + top, j1 + top, j2 + top)
            for tag, i1, i2, j1, j2 in super().get_opcodes()
        ]
        if end:
            a_end, b_end = self._a_len - end, self._b_len - end
            codes.append(("equal", a_end, self._a_len, b_end, self._b_len))
        return codes


def unified(slug: str, rev: int, before: str, after: str) -> tuple[str, bool]:
    """A unified diff of a page's text, and whether it was cut at MAX_DIFF. difflib
    is quadratic in the worst case, so it compares only the lines between the
    common start and end; the common start and end are added as equal runs, so each
    hunk has its full context (a patch tool reads a hunk with less trailing than
    leading context as ending the file). If the lines between are many, the diff is
    one hunk replacing them all. The result can differ from the diff difflib makes
    of the whole text where repeated lines let it match them differently."""
    a, b = split_lines(before), split_lines(after)
    if a == b:
        return "", False
    top, most = 0, min(len(a), len(b))
    while top < most and a[top] == b[top]:
        top += 1
    end = 0
    while end < most - top and a[-1 - end] == b[-1 - end]:
        end += 1
    head = [f"--- {slug} (rev {rev})\n", f"+++ {slug} (edited)\n"]
    if (len(a) - top - end) * (len(b) - top - end) <= DIFF_WORK:
        matcher = _WholeFileMatcher(a, b, top, end)
        lines = head
        for group in matcher.get_grouped_opcodes(CONTEXT):
            first, last = group[0], group[-1]
            lines.append(
                f"@@ -{span(first[1], last[2])} +{span(first[3], last[4])} @@\n"
            )
            for tag, i1, i2, j1, j2 in group:
                if tag == "equal":
                    lines += (" " + x for x in a[i1:i2])
                    continue
                if tag in ("replace", "delete"):
                    lines += ("-" + x for x in a[i1:i2])
                if tag in ("replace", "insert"):
                    lines += ("+" + x for x in b[j1:j2])
    else:  # one hunk: its context, then every line between removed, then added
        start, tail = max(top - CONTEXT, 0), max(end - CONTEXT, 0)
        a_part, b_part = a[start : len(a) - tail], b[start : len(b) - tail]
        lines = [
            *head,
            f"@@ -{start + 1},{len(a_part)} +{start + 1},{len(b_part)} @@\n",
            *(" " + x for x in a[start:top]), *("-" + x for x in a[top : len(a) - end]),
            *("+" + x for x in b[top : len(b) - end]),
            *(" " + x for x in a[len(a) - end : len(a) - tail]),
        ]  # fmt: skip
    diff = "".join(lines_ended(lines))
    return diff[:MAX_DIFF], len(diff) > MAX_DIFF


def span(start: int, stop: int) -> str:
    """A hunk header range for lines start..stop (0-based, stop excluded): its first
    line and, unless it is one line, its count (an empty range is the line before)."""
    count = stop - start
    if count == 1:
        return str(start + 1)
    return f"{start + (1 if count else 0)},{count}"


def lines_ended(lines: list[str]) -> Iterator[str]:
    """Diff lines, each ending a line: one the text ended without is marked."""
    for line in lines:
        yield line if line.endswith("\n") else f"{line}\n\\ No newline at end of file\n"
