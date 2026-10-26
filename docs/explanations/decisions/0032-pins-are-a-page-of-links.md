# 32. Pins are an ordinary page of links

Date: 2026-10-26

## Status

Accepted

## Context

Search phase 2 (#314) lets you keep your own searches and pages one tap away under the empty
search box. Pins could be a table, a setting or localStorage; each would be a thing to sync,
back up, edit and export of its own, and a pin kept on one phone would be missing on another.

## Decision

- The pins are one page, titled Pinned with the slug `pinned`: a Markdown list of links
  (`- [People](/search?q=tag:person%20group:letter)`, `- [Contacts](/p/contacts)`). The launcher
  shows them in order. Renaming, reordering and removing a pin is editing the page, which syncs,
  is revised, backed up, searchable and linkable like any other.
- `POST /api/pinned` returns the page, making it once. The slug is the reservation: the page is
  looked up by it inside one write transaction, a trashed one is brought back, and a page the
  owner already called `pinned` is the Pinned page. No migration.
- A normal page the owner titles "Pinned" gets the slug `pinned` and so becomes the pin list.
- Pins link by slug, and a slug never changes when a page is retitled, so a pin survives a
  rename. The client edits with `base_rev` and retries a `409` up to three times.
- Claude does not read the page (`should_enrich`, the backfill and the related pass skip the
  slug); Ask Claude still works on it.
- `group:area` is a search group: topic pages by area in the order `GET /api/topics` gives, so
  the Topics screen and `is:topic` in Search share one grouping and one order. Topic hits carry
  `area`.

## Consequences

A page the owner makes called "Pinned" becomes the pin list. The Pinned page appears in search
results like any page. A browser with no Share menu has no Pin to Search row; the page can be
edited by hand.
