"""The search box's syntax (#84): words, "phrases", -word or !word (NOT), and the
filters kind:, tag: and is:. One pass over the text (the only regular expressions match
one character), so no input can make parsing take more than linear time."""

import re
from dataclasses import dataclass, field

__all__ = ["Term", "Filter", "Query", "parse", "KEYS"]

KEYS = ("kind", "tag", "is")
WORD = re.compile(r"[^\W_]")  # a letter or digit: something FTS indexes (one character)
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
MAX_TERMS = 16  # every term adds a subquery
MAX_FILTERS = 16
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
    prefix: bool = False  # the last term is the word being typed: match it as a prefix

    @property
    def positive(self) -> list[Term]:
        return [t for t in self.terms if not t.neg]

    @property
    def negative(self) -> list[Term]:
        return [t for t in self.terms if t.neg]

    def fts(self, term: Term) -> str:
        """A term as an FTS5 string (the last word typed as a prefix)."""
        star = "*" if self.prefix and term is self.terms[-1] else ""
        return f'"{term.text}"{star}'


def parse(text: str) -> Query:
    """The terms and filters of a query. Space between terms means AND."""
    s = CONTROL.sub(" ", text)
    n = len(s)
    q = Query()
    seen: set[Term] = set()
    last_word = False  # the last thing read was a plain positive word
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
            last_word = False
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
            last_word = False
            continue
        i = j
        if add(q, seen, Term(word, False, neg)):
            last_word = not neg
        elif WORD.search(word):
            last_word = False  # a repeat: not the word being typed
    q.prefix = last_word and bool(q.terms) and not q.terms[-1].neg
    return q


def add(q: Query, seen: set[Term], term: Term) -> bool:
    """Keep a term FTS can match (a letter or digit in it), once, at most MAX_TERMS."""
    if not WORD.search(term.text) or term in seen or len(q.terms) >= MAX_TERMS:
        return False
    seen.add(term)
    q.terms.append(term)
    return True
