# 11. Whiteboards become Excalidraw drawings: model skeletons, human scenes, two sanitisers

Date: 2026-10-19 (backend and PWA 2026-10-19/20)

## Status

Accepted

## Context

Chat is poor at showing images, but a whiteboard photo is more useful redrawn as something
editable and searchable. Excalidraw is an off-the-shelf editor with a component, an open file format
and a skeleton API, so scrap writes no drawing tool.

## Decision

- The model returns flat, schema-bound **element skeletons**; code expands them with
  `convertToExcalidrawElements` in the browser (with two documented workarounds for free-text
  arrows and font loading). The server converts approximately only for zip downloads.
- A drawing is a derived version ([](0004-originals-kept-everything-else-derived.md)). Saving an edit
  creates a `human` version against a base version (409 if stale); **History** and **Restore** copy
  a version forward. Reprocessing over a human drawing always asks (**Replace mine / Keep mine**).
- Two sanitisers. **Model output is strict** (six element types, bounded ids, colours, numbers,
  counts; a bad element is dropped with a warning). **Human scenes are permissive** (also
  `freedraw`, Excalidraw's own keys and colours) but strip embedded files and non-http links, and
  are limited to 5 MB, 32 levels and no lone surrogates. A violation is a 422 and the editor keeps
  its state.
- On a page the drawing is a static SVG framed like the photo, with the frame size supplied by the
  server so nothing shifts; tapping opens a full-screen viewer/editor. Drafts live in IndexedDB.

## Consequences

- Dependent on Excalidraw API behaviour (the version is pinned; drift is a named risk).
- Model drawings are approximate; the photo stays beside them.
- Embedded images, frames and embeds are unsupported in scenes.
