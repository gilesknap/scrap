# scrap-public: what a client (scrap) must send

The receiver (`receiver.py`) is the authority; this is the minimum a client needs.
`src/scrap/publish/unit.py` builds a unit's tar and digest exactly as described here
(`build_unit(files) -> (tar_bytes, digest)`), and the receiver's tests use it.

## Connection

- `SCRAP_PUBLISH_TO`: the receiver's base URL, e.g. `http://scrap-receiver.scrap-public.svc:8081`.
- Every request but `GET /healthz` carries `Authorization: Bearer <token>`
  (`SCRAP_PUBLISH_TOKEN[_FILE]`, the receiver's `RECEIVER_TOKEN[_FILE]`, at least 32
  characters, no whitespace). Otherwise `401` with `WWW-Authenticate: Bearer`, before any
  other check (an unknown path is `401` too, not `404`).
- HTTP/1.1, keep-alive. Every error is JSON `{"error": "<code>", "detail": "<text>"}`.

## Units

The unit is the raw path after `/v1/units/`, matched exactly (no decoding):

| unit | pattern | must hold |
| --- | --- | --- |
| page | `p/[a-z0-9-]{1,120}` | `index.html` |
| tag | `t/[a-z0-9-]{1,80}` | `index.html` |
| home | `home` | `index.html` (also `tags.html`, `404.html`) |
| search index | `pagefind` | at least one file |

Anything else (`%`, `.`, `//`, a trailing `/`, upper case, a query string) is `422 bad_unit`.

nginx serves: `/` → `home/index.html`, `/tags` → `home/tags.html`, `/<name>` → `home/<name>`,
`/p/<slug>` and `/p/<slug>/` → `p/<slug>/index.html`, `/p/<slug>/<path>` → that file (and the
same for `/t/<key>`), `/pagefind/<path>`, and `home/404.html` for any 404. So a page links its
own files as `/p/<slug>/img-1-0123456789.jpg`.

## A unit's tar

- An **uncompressed** tar (ustar or pax), with only regular files (`REGTYPE`): no directory
  entries, symlinks, hardlinks, devices, FIFOs or sparse files. Each path once.
- Paths are relative, with no `./` prefix: at most 4 segments joined by `/`, each matching
  `[A-Za-z0-9_][A-Za-z0-9._-]{0,99}` (so no leading dot, no `..`). A file may not share its
  path with a folder of another (`a` and `a/b.html`).
- The extension (after the last `.`, any case) must be one of: `html css js mjs json wasm txt
  md`, `png jpg jpeg gif webp avif svg ico woff woff2`, `pdf csv zip epub docx xlsx pptx odt
  ods odp bin`, `pagefind pf_meta pf_index pf_fragment pf_filter`. Use `bin` for an attachment
  of any other type.
- At most 10,000 files and 20 MiB per file (`413`), within the 2 GiB site quota counted over
  every live unit, the one being replaced counted at its new size (`507`).
- Attachments are `/p/<slug>/file-*`: a PDF there gets `Content-Security-Policy: sandbox`
  alone, any other `file-*` the strict sandbox that loads nothing (ADR 42's rule); everything
  else the site's CSP.

## The digest

`Scrap-Digest: <64 lower-case hex>` is the sha256 of, for each file in sorted path order
(byte order; paths are ASCII), the line

```
<path> NUL <sha256 hex of the content> LF
```

concatenated. In Python:

```python
hashlib.sha256(b"".join(
    p.encode() + b"\0" + hashlib.sha256(files[p]).hexdigest().encode() + b"\n"
    for p in sorted(files)
)).hexdigest()
```

A missing or different digest is `400 digest_mismatch`, and nothing changes. The digest is
also the unit's `digest` in the manifest, so a client can compare without re-uploading.

## Endpoints

- `GET /healthz` → `200 {"ok": true}`, no token.
- `GET /v1/manifest` → `200 {"version": 1, "bytes": N, "quota": N, "units": {"p/x":
  {"digest": "...", "files": N, "bytes": N, "at": "2026-10-31T12:00:00Z"}}}`.
- `PUT /v1/units/{unit}` with `Content-Type: application/x-tar`, `Content-Length` (no chunked:
  `411`), `Scrap-Digest`. Over 256 MiB is `413` before the body is read (send `Expect:
  100-continue` to hear it before sending). Another write in progress: `503 busy` with
  `Retry-After: 1`; retry. The whole upload has 30 s (`408`). `200` with the unit's manifest
  entry plus `"unit"`. Other codes: `415` (content type), `400 bad_tar`, `422 bad_member`,
  `422 no_index`, `422 empty_unit`.
- `DELETE /v1/units/{unit}` → `204`, whether or not it was there (or `503 busy`).
- `POST /v1/sync` with `Content-Type: application/json` and `{"keep": [unit, ...]}` → deletes
  every live unit not listed: `200 {"deleted": [...]}`. `422` for an empty list, a list without
  `home`, or an entry that is not a unit; `400` if `keep` is not a list of strings.
- A wrong method on a known route is `405` with `Allow`.

## The receiver's side

`RECEIVER_LISTEN=tcp:HOST:PORT` (default `tcp:0.0.0.0:8081`), `RECEIVER_SITE` (default `/site`),
`RECEIVER_TOKEN` or `RECEIVER_TOKEN_FILE` (the file wins; its content, stripped),
`RECEIVER_QUOTA_BYTES` (default 2 GiB). On start it empties `staging/` and removes every copy
no unit's symlink refers to.
