# scrap

Notes for Claude Code working in this repo. See `.github/CONTRIBUTING.md` for setup, checks, PRs and releases.

## Keep modules small

- Aim for modules of a few hundred lines. Past about 500, split by responsibility before adding more.
- Put new code in a focused module, not in the nearest large file.
- A split is a package with a thin `__init__.py` that only re-exports (`store/`, `ingest/`, `enrich/` and `importer/` are examples). Callers keep `from scrap.x import Name`.
- Layer modules strictly downward (errors and constants first), so there are no import cycles.
- A pure refactor moves code verbatim: no logic edits, no renames. Keep it in its own PR, and check it with an `ast` comparison of the old and new definitions.
- Patch a name where it is looked up (the submodule that reads it), not on the package re-export.
- CSS order is the cascade: when splitting `web/src/style.css`, keep the files imported in their original order.
