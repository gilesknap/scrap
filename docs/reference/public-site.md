# Public site

The HTTP contract between scrap and the receiver of the public site, and how nginx serves what
the receiver writes. Why it is built this way is in
[](../explanations/decisions/0043-public-pages-a-static-site-scrap-pushes-to.md).

scrap is the only client. The PWA never talks to the receiver, and the receiver is never on a
public ingress: only nginx is.

## Settings

The receiver:

| Variable | Default | Meaning |
| --- | --- | --- |
| `RECEIVER_LISTEN` | `tcp:0.0.0.0:8081` | Where it listens: `tcp:<host>:<port>`, or `unix:<path>` (optional, for the later single-server install) |
| `RECEIVER_TOKEN_FILE` | unset | A file holding the token (surrounding whitespace ignored). Wins over `RECEIVER_TOKEN` |
| `RECEIVER_TOKEN` | unset | The token itself |
| `RECEIVER_SITE` | `/site` | The site directory it writes and nginx serves |

The receiver does not start without a token, or with one shorter than 32 characters.

scrap:

| Variable | Meaning |
| --- | --- |
| `SCRAP_PUBLISH_TO` | The receiver's URL, e.g. `http://scrap-public-receiver.scrap-public.svc:8081` |
| `SCRAP_PUBLISH_SITE` | The site's public base URL, e.g. `https://pages.gkcluster.org`, for the links scrap shows |
| `SCRAP_PUBLISH_TOKEN_FILE`, `SCRAP_PUBLISH_TOKEN` | The same token, as a file or a value; the file wins |

Without `SCRAP_PUBLISH_TO` and a token, publishing is off.

## Transport and auth

- HTTP/1.1. Each request is served within 30 seconds (reading the body included), or the
  connection is closed.
- Every route except `GET /healthz` needs `Authorization: Bearer <token>`. The token is compared
  with `hmac.compare_digest`. A missing or wrong token gets `401`. The token, and the
  `Authorization` header, are never logged.
- Request and response bodies other than a tar are JSON (`application/json`, UTF-8).

## Units

The site is made of **units**. A unit is replaced whole or deleted whole; nothing writes a single
file inside one.

| Unit | Pattern | Holds | Served at |
| --- | --- | --- | --- |
| A page | `p/[a-z0-9-]{1,120}` | `index.html`, and the page's images (`img-*`) and other files (`file-*`) | `/p/<slug>` and `/p/<slug>/<name>` |
| A tag | `t/[a-z0-9-]{1,80}` | `index.html` | `/t/<key>` |
| The home page | `home` | `index.html`, `tags.html`, `404.html` | `/`, `/tags`, any missing path |
| The search index | `pagefind` | Pagefind's files | `/pagefind/...` |

The unit in a URL is matched exactly, against the raw path before any decoding, with the whole
pattern anchored. A path holding `%`, a `.` segment, `//` or a trailing `/` gets `422`, as does a
unit that matches no pattern.

## The tar's files

A unit's body is a tar (`application/x-tar`, uncompressed). Its members are read one by one,
never with `extractall`, and each must be:

- a **regular file** (a directory entry is skipped): a symlink, hard link, device, FIFO or any
  other type is refused;
- at a **relative path** of 1 to 4 segments separated by `/`, each segment matching
  `[A-Za-z0-9_][A-Za-z0-9._-]{0,99}` (so no `..`, no leading `.` or `-`, no absolute path);
- **once**: a path that occurs twice is refused;
- of an allowed **extension** (the last `.` in the last segment, compared in lower case):
  `html`, `css`, `js`, `json`, `wasm`, `png`, `jpg`, `jpeg`, `gif`, `webp`, `svg`, `pdf`, `md`,
  `txt`, and Pagefind's own `pagefind`, `pf_meta`, `pf_index`, `pf_fragment` and `pf_filter`.

A page unit must hold `index.html`, a tag unit `index.html`, and `home` all three of its files.
A file that breaks any rule refuses the whole unit with `422`, and nothing is written.

## What scrap puts in a unit

The receiver checks only the rules above. These are scrap's, so that what it sends always passes
them.

**A page** (`p/<slug>`, the page's slug in scrap). The PWA uploads the page's HTML, from
`pagehtml.ts` in its publish mode. In it, every `<img src>` and every link to a file of the page
is a placeholder naming the stored file: `scrap-blob:<sha>`. scrap replaces each placeholder with
an **absolute** path, `/p/<slug>/<name>` (the page is served at `/p/<slug>` with no trailing
slash, so a relative link would resolve under `/p/`), and puts the bytes beside `index.html`:

| File | Name | Bytes |
| --- | --- | --- |
| A photo | `img-<n>-<hex>.jpg` | The 2048-pixel JPEG preview (EXIF and GPS stripped when it was made) |
| A PNG or other raster image | `img-<n>-<hex>.jpg` or `.png`, as its preview is | The 2048-pixel preview |
| An SVG | `img-<n>-<hex>.svg` | The sanitised SVG scrap stores (ADR 42) |
| Another file (a PDF, a `.md`) | `file-<n>-<hex>.<ext>` | The file as stored, with its extension in lower case |

- `<n>` counts the page's images, and separately its other files, from 1, in the order they first
  appear in the HTML; the same file used twice is one file.
- `<hex>` is the first 10 hex digits of the SHA-256 of the bytes published (not the stored
  file's sha, which is never published, nor its uploaded name; a link's label may show the name).
- At most **20** images and files together go with one page. Over that, scrap refuses the
  publish with `422` and a message saying so, and nothing is pushed.
- A placeholder for a file that is not on the page, a file of a type the receiver does not
  allow, or any other `/api` or private address left in the HTML refuses the publish.

**A tag** (`t/<key>`). The key is made from the tag, so any tag (spaces, `/`, letters outside
ASCII) has one:

1. the tag as ASCII: Unicode NFKD, characters without an ASCII form dropped, lower case;
2. each run of characters other than `a-z` and `0-9` becomes `-`, and `-` is trimmed from both
   ends; cut to 60 characters and trimmed again;
3. then `-` and the first 8 hex digits of the SHA-256 of the whole tag (UTF-8).

So `personal/family` is `personal-family-` and 8 hex digits, for example
`personal-family-1a2b3c4d`; a tag with no ASCII letters or digits is `-` and its 8 digits. The key
is at most 69 characters, so it always fits the unit pattern, and tags that make the same slug
still get different keys.

**`home` and `pagefind`.** scrap builds them, and every tag unit, from the copies below with
plain Python templates and the `pagefind[bin]` Python package (at a pinned version).

## scrap's copies and reconciling

scrap keeps the last HTML uploaded for each public page at
`<data>/cache/publish/p/<slug>/index.html` (with its placeholders already replaced). It is
derived data and is not backed up. The site is rebuilt from these copies, never by rendering:

- **After a publish** scrap pushes the page's unit, then the units built from the copies that
  changed: `home`, the tags of the page (before and after), and `pagefind`.
- **After an unpublish** (Public off in the PWA or over MCP, a revert, the page going to the
  trash) scrap sends `DELETE /v1/units/p/<slug>`, deletes its copy, and pushes `home`, the page's
  tag units (deleting a tag unit no public page has any more) and `pagefind`.
- **Reconciling**, at startup and every 10 minutes: scrap reads `GET /v1/manifest`, computes the
  digest of each unit it would send (a page's files copied from its store again), `PUT`s every
  unit that is missing or differs, and ends with `POST /v1/sync` listing every unit it means
  to keep. A site that lost its files, such as a restarted pod with an `emptyDir`, is filled
  again within 10 minutes with nothing from the PWA.

A `503` (busy) is retried; any other failure is logged and left to the next reconcile.

## Limits

| Limit | Value | Over it |
| --- | --- | --- |
| Files in a unit | 10,000 | `413` |
| One file | 20 MiB | `413` |
| The request body | 256 MiB | `413` (from `Content-Length`, before reading) |
| The whole site | 2 GiB | `507`, counted as the site's bytes with this unit's new size in place of its old one |
| A request | 30 s | the connection is closed |

## The digest

Every `PUT` carries a `Scrap-Digest` header: the lowercase hex SHA-256 of, for each file in
sorted path order (sorted by the path's UTF-8 bytes),

```
<path> NUL <hex sha256 of the file's content> LF
```

that is, `path + "\0" + sha256(content).hexdigest() + "\n"`, concatenated. For example, in
Python:

```python
h = hashlib.sha256()
for path in sorted(files):
    h.update(path.encode() + b"\0" + hashlib.sha256(files[path]).hexdigest().encode() + b"\n")
digest = h.hexdigest()
```

The receiver computes it again from the tar. A missing header, or one that does not match, gets
`400` and nothing is written. The manifest reports each unit's digest, so scrap can tell whether
a unit already holds what it would send.

## Endpoints

### `GET /healthz`

No auth. `200` with `{"ok": true}` when the site directory is writable.

### `GET /v1/manifest`

What the site holds:

```json
{
  "version": 1,
  "bytes": 12345678,
  "quota": 2147483648,
  "units": {
    "p/my-whiteboard": {"digest": "<hex>", "files": 3, "bytes": 812345, "at": "2026-10-31T14:02:11Z"},
    "home": {"digest": "<hex>", "files": 3, "bytes": 20480, "at": "2026-10-31T14:02:12Z"}
  }
}
```

`bytes` is the site's total, `quota` its limit, and `at` when the unit was last written (UTC,
ISO 8601, to the second).

### `PUT /v1/units/{unit}`

Replace a unit (or make it). The body is the tar; `Content-Type: application/x-tar` and
`Content-Length` are required (`415` and `411` without them; chunked bodies are refused). One
lock serialises every write (`PUT`, `DELETE` and `sync`); a request that cannot take it at once
gets `503` with `Retry-After: 1`, and scrap tries again.

The swap is atomic, so nginx serves either the old unit or the new one, never a mix:

1. Each file is written into a new staging directory inside the site directory, and fsynced, as
   is the directory.
2. A new symlink pointing at it is made beside the unit's name and moved over the name with
   `os.replace`; the parent directory is fsynced.
3. The old unit's directory is deleted.

Staging directories, and the directories units point at, start with `.`, so nginx never serves
them by name. A staging directory left by a crash is deleted when the receiver starts.

`200` with the unit's manifest entry.

### `DELETE /v1/units/{unit}`

Remove a unit. `204`, also when it was not there.

### `POST /v1/sync`

`{"keep": ["home", "pagefind", "p/a", "t/b", ...]}`: delete every unit not in the list, so the
site holds no more than scrap means it to. Each entry must match a unit pattern (`422`
otherwise). A list that is empty, or does not hold `home`, is refused with `422` (a guard against
wiping the site by mistake). `200` with `{"deleted": [...]}`.

## Errors

Every error is JSON, `{"error": "<code>", "detail": "<a sentence>"}`:

| Status | `error` | When |
| --- | --- | --- |
| `400` | `digest` | `Scrap-Digest` missing or wrong |
| `400` | `bad_tar` | The body is not a readable tar |
| `401` | `unauthorized` | No token, or the wrong one |
| `404` | `not_found` | No such route |
| `405` | `method` | A method the route does not take |
| `411` | `length_required` | `PUT` without `Content-Length` |
| `413` | `too_large` | Over a limit of files, file size or body |
| `415` | `media_type` | `PUT` that is not `application/x-tar` |
| `422` | `bad_unit`, `bad_path`, `bad_sync` | A unit, a member path, a member type or extension, a missing required file, or a `sync` list that is refused |
| `503` | `busy` | Another write holds the lock |
| `507` | `quota` | The site would grow past its quota |

`detail` never repeats the token or a header.

## nginx

nginx serves the site directory read only, as files. It takes `GET` and `HEAD` only (`405`
otherwise), with no `autoindex` and `server_tokens off`.

| Path | Serves |
| --- | --- |
| `/` | `home/index.html` |
| `/tags` | `home/tags.html` |
| `/p/<slug>` | `p/<slug>/index.html` |
| `/p/<slug>/<file>` | `p/<slug>/<file>` |
| `/t/<key>` | `t/<key>/index.html` |
| `/pagefind/<path>` | `pagefind/<path>` |
| `/robots.txt` | `User-agent: *` and `Disallow: /`, from nginx's own config |
| anything else | `home/404.html`, with `404` |

A path segment starting with `.` is always `404`.

### Headers

On every response:

- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: no-referrer`
- `X-Robots-Tag: noindex, nofollow`

`Content-Security-Policy` depends on what is served:

| Served | `Content-Security-Policy` |
| --- | --- |
| HTML, and Pagefind's files | `default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline' 'self'; script-src 'self' 'wasm-unsafe-eval'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'` |
| A page's file (`/p/<slug>/img-*`, `/p/<slug>/file-*`), but a PDF | `sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:` |
| A PDF (`/p/<slug>/file-*.pdf`) | `sandbox` |

The only scripts are Pagefind's (its UI, on the home page), loaded from `/pagefind/` as files;
there is no inline script. It fetches its index (`connect-src 'self'`) and runs WebAssembly
(`'wasm-unsafe-eval'`). A page has no script. A page's file follows ADR 42's rule for stored
files: opened on its own it runs nothing and loads nothing, and a PDF keeps `sandbox` alone so
a browser's PDF viewer works.

Types come from the extension (`.md` and `.txt` as `text/plain; charset=utf-8`, Pagefind's own
files as `application/octet-stream`, `.wasm` as `application/wasm`).

### Caching

- HTML: `Cache-Control: no-cache`, so a browser or proxy checks again before each use, and a
  page unpublished is gone on its next load.
- Every other file: `Cache-Control: max-age=300`, so a deleted file can be seen for up to five
  minutes more from a cache.

Nothing the site does reaches copies people saved, or caches that ignore these headers.
