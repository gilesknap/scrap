# 40. Search greps raw text: a parameter, and a scan

Date: 2026-10-31 (#474)

## Status

Accepted

## Context

The search index (`chunk_fts`, `tokenize='porter unicode61'`) keeps only words, stemmed. It
cannot find punctuation or an exact string: every page with a Markdown table (`|---|`), a command
line, an IP address with its dots, a code identifier like `foo_bar(`. Answering "which pages
have a table?" took a SQL scan in the pod (#473).

## Decision

- `search` gains two optional parameters, `grep` (a pattern) and `regex` (off: a
  case-insensitive substring; on: an RE2 regex, `^` and `$` at each line). There is no `grep`
  tool: [](0030-fewer-mcp-tools.md) keeps the tool count down because models choose better among
  fewer, and this is a narrower search, not a new kind of request. `query` still chooses and
  orders the pages; `grep` must match too.
- It matches what is stored: a page's title, its Markdown body and the current text read from its
  files (derived `ocr`). The trash is not scanned.
- It is a scan in Python (`store/grep.py`), not a trigram index. A selective pattern over a few
  thousand pages takes tens of milliseconds; a broad one, or one that matches few pages so the
  scan reads everything (files' text included), costs time in proportion to all the stored text,
  which the time budget below caps. A trigram FTS table would need a migration and a second index
  of every text, and still could not answer a regex alone. The query's candidates come from
  search's own SQL (its filters, and its ranking for words), so filters, words and order behave
  as they do without `grep`.
- The regex engine is [RE2](https://github.com/google/re2) (`google-re2`), not Python's `re`.
  `re` backtracks, so a pattern like `^(a|aa)+$` can run for ever, and neither it nor the `regex`
  package (whose `timeout` bounds matching) bounds compiling: `(((a{1000}){1000}){1000})`, 25
  characters, takes gigabytes to compile, enough to have the pod killed. RE2 refuses a pattern
  whose program would pass `max_mem` (8 MiB) or whose counted repeats pass 1,000 (nested ones
  multiplied), and matches in time linear in the text, though for a large pattern, once RE2's
  DFA gives up, the constant is the pattern's size: `a.{999}b.{999}a` reads about 100 KB a
  second. The cost: no backreferences or lookaround (refused as an invalid regex), and `\w`,
  `\b`, `\d`, `\s` are ASCII only.
- So that the scan stays linear too, each search reads a window of whole lines about 16 KiB long,
  and the next starts after the match (or its line): each byte is read about once, and one
  search costs at most a window. A match longer than a window is missed. Matches do not overlap.
- Guards: a pattern of at most 200 characters; a 2-second budget for the whole scan, checked
  before every search, so a call ends within the budget and one window's search (a tool error
  past it); at most 1,000 matching lines counted and 5 returned a page, each line cut to about
  200 characters; the scan stops once it has the page of results asked for; pages are read 50
  at a time. An invalid regex is a tool error.

## Consequences

`google-re2` is a new dependency (wheels for CPython 3.11 to 3.14 on Linux x86_64 and aarch64,
as the container image needs). A grep's cost grows with the corpus: if scrap ever holds far more
text than a few thousand pages, the budget will start refusing broad patterns, and an index
(trigram, or `has:table`-style structure filters) can come then. The PWA's search box does not
take `grep`.
