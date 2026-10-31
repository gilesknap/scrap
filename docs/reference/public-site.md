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
| A page | `p/[a-z0-9-]{1,120}` | `index.html` and the page's attached files | `/p/<slug>` and `/p/<slug>/<file>` |
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

The PWA's HTML links a page's own files by absolute path (`/p/<slug>/<file>`): the page is
served at `/p/<slug>` with no trailing slash, so a relative link would resolve under `/p/`.

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

- `Content-Security-Policy: default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline' 'self'; script-src 'self' 'wasm-unsafe-eval'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`.
  The only scripts are Pagefind's (its UI, on the home page), loaded from `/pagefind/`, which
  fetches its index (`connect-src 'self'`) and runs WebAssembly (`'wasm-unsafe-eval'`); a page
  has no script.
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: no-referrer`
- `X-Robots-Tag: noindex, nofollow`

Types come from the extension (`.md` and `.txt` as `text/plain; charset=utf-8`, Pagefind's own
files as `application/octet-stream`, `.wasm` as `application/wasm`).

### Caching

- HTML: `Cache-Control: no-cache`, so a browser or proxy checks again before each use, and a
  page unpublished is gone on its next load.
- Every other file: `Cache-Control: max-age=300`, so a deleted file can be seen for up to five
  minutes more from a cache.

Nothing the site does reaches copies people saved, or caches that ignore these headers.
