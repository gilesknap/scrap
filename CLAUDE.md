# scrap

Notes for Claude Code working in this repo. See `.github/CONTRIBUTING.md` for setup, checks, PRs and releases.

## Pull requests

- For any PR, use the `scrap-pr` skill (`.claude/skills/scrap-pr/`) alongside the general `pr-cycle` user skill: `pr-cycle` is the process, `scrap-pr` adds scrap's checks and specifics and wins where they differ.

## Keep modules small

- Aim for modules of a few hundred lines. Past about 500, split by responsibility before adding more.
- Put new code in a focused module, not in the nearest large file.
- A split is a package with a thin `__init__.py` that only re-exports (`store/`, `ingest/` and `enrich/` are examples). Callers keep `from scrap.x import Name`.
- Layer modules strictly downward (errors and constants first), so there are no import cycles.
- A pure refactor moves code verbatim: no logic edits, no renames. Keep it in its own PR, and check it with an `ast` comparison of the old and new definitions.
- Patch a name where it is looked up (the submodule that reads it), not on the package re-export.
- CSS order is the cascade: when splitting `web/src/style.css`, keep the files imported in their original order.

## Migrations

- `src/scrap/migrations/baseline.sql` is the schema at `db.BASELINE` (18). It is generated (`uv run python -m scrap.store.baseline`), never edited by hand.
- A schema change is a new numbered script after the baseline, `0019_*.sql` onward, numbered by merge order: no gaps, never reserve a number. The file name's number is `BASELINE + 1 + position` (a test enforces it).
- Then review the schema diff and refreeze the head snapshot: `uv run python -m scrap.store.baseline --snapshot`. `tests/test_baseline.py` fails without it.
- Plain SQL; avoid rebuilding a table in Python unless a `CHECK` must change. Folding scripts into a new baseline is rare and deliberate (`--fold`).
- The runner refuses a database below the baseline. See ADR 37.

## UI changes: mock first

- For any change you can see (the PWA, or the public site's look), mock it in the
  sim first (`.claude/skills/sim/`) and get the owner's OK on screenshots before
  building: 308 px and 130 % text, light and dark.
- For the public site, a static page from `web/src/public/page.css` and the
  publish mode's markup is enough.
- Changes the owner has already specified in detail still get screenshots in
  the PR, but no separate mock round.
