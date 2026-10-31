# Public site

The contract for public pages: what the PWA uploads to scrap, what scrap pushes to the public
site's receiver, and how nginx serves it. This page is the single source of truth for it; the
`scrap-public` image and scrap both follow it. Why it is built this way is in
[](../explanations/decisions/0043-public-pages-a-static-site-scrap-pushes-to.md).

scrap is the receiver's only client. The PWA never talks to the receiver, and the receiver is
never on a public ingress: only nginx is.

## Settings

The `scrap-public` image has two commands, `web` (nginx, port 8080) and `receive` (the
receiver). In Kubernetes they are two containers of one pod, sharing the site volume at `/site`.

| Variable | Read by | Default | Meaning |
| --- | --- | --- | --- |
| `RECEIVER_LISTEN` | `receive` | `tcp:0.0.0.0:8081` | Where it listens, `tcp:<host>:<port>` (a Unix socket may be added for the later single-server install) |
| `RECEIVER_TOKEN_FILE` | `receive` | unset | A file holding the token (its content, stripped). Wins over `RECEIVER_TOKEN`. This is how the receiver gets it in a deployment: the chart mounts the Secret as a file, never as an environment variable |
| `RECEIVER_TOKEN` | `receive` | unset | The token itself, for tests and development only |
| `RECEIVER_SITE` | `receive` | `/site` | The site folder ([layout](#the-site-folder)) |
| `RECEIVER_QUOTA_BYTES` | `receive` | 2 GiB | The site's quota, in bytes |
| `INDEXING` | `web` | `off` | `on` lets search engines index the site; `off` sends `X-Robots-Tag: noindex, nofollow` and a `robots.txt` of `Disallow: /`. Anything else stops `web` at start |

The receiver does not start without a token, with one shorter than 32 characters, or with one
holding whitespace.

scrap:

| Variable | Meaning |
| --- | --- |
| `SCRAP_PUBLISH_TO` | The receiver's base URL, e.g. `http://scrap-receiver.scrap-public.svc:8081` (the chart's Service is `<fullname>-receiver`, here for a release named `scrap`) |
| `SCRAP_PUBLISH_SITE` | The site's public base URL, e.g. `https://pages.gkcluster.org`, for the links scrap shows |
| `SCRAP_PUBLISH_TOKEN_FILE`, `SCRAP_PUBLISH_TOKEN` | The same token, as a file or a value; the file wins |

Without `SCRAP_PUBLISH_TO` and a token, publishing is off.

## Transport and auth

- HTTP/1.1 with keep-alive. A request has 30 seconds in all, its body included (`408`).
- A client should send `Expect: 100-continue` with every request that has a body, where its
  HTTP library supports it, so a refusal
  that needs only the headers (`401`, `411`, `413`, `415`, `422 bad_unit`) arrives before the
  body is sent. When the receiver refuses a body it has not read, it closes the connection
  lingering (it reads and drops what is still arriving for a moment first), so a client that
  cannot send `Expect` still sees the answer rather than a reset.
- Every route except `GET /healthz` needs `Authorization: Bearer <token>`, compared with
  `hmac.compare_digest`. Without it the answer is `401` with `WWW-Authenticate: Bearer`, before
  any other check: an unknown path is `401` too, not `404`. The token, and the `Authorization`
  header, are never logged; the log has the request line and status only.
- Every error is JSON, `{"error": "<code>", "detail": "<a sentence>"}` ([](#errors)).
- A wrong method on a known route is `405` with `Allow`.

## Units

The site is made of **units**. A unit is replaced whole or deleted whole; nothing writes one file
inside a unit.

| Unit | Pattern | Must hold | May hold | Served at |
| --- | --- | --- | --- | --- |
| A page | `p/[a-z0-9-]{1,120}` | `index.html` | its images and files (below) | `/p/<slug>`, `/p/<slug>/`, `/p/<slug>/<name>` |
| A tag | `t/[a-z0-9-]{1,80}` | `index.html` | other `.html` files | `/t/<key>`, `/t/<key>/` |
| The home page | `home` | `index.html` | any other one-segment `.html` (scrap sends `tags.html` and `404.html`) | `/`, `/tags`, every 404 |
| The search index | `pagefind` | at least one file | Pagefind's files and `scrap-search.js` | `/pagefind/<path>` |
| Shared assets | `assets` | at least one file | KaTeX's CSS and fonts | `/assets/<path>` |

The unit is the raw request path after `/v1/units/`, matched exactly against the pattern (no
decoding). Anything else, such as `%`, a `.` segment, `//`, a trailing `/`, upper case or a query
string, is `422 bad_unit`.

What each kind may hold. A member that breaks its kind's rule is `422 bad_member`:

| Unit | Members |
| --- | --- |
| `p/*` | `index.html`; `img-<n>-<hex>.jpg`, `.png` or `.svg`; `file-<n>-<hex>.<ext>` with `<ext>` one of `pdf`, `txt`, `md`, `csv`, `zip`, `epub`, `docx`, `xlsx`, `pptx`, `odt`, `ods`, `odp`, `bin`. `<n>` is `[1-9][0-9]?`, `<hex>` is `[0-9a-f]{10}`. One segment each: no folders |
| `t/*` | `.html` files, one segment each |
| `home` | `.html` files, one segment each (`robots.txt` is not in a unit: nginx makes it) |
| `pagefind` | `js`, `mjs`, `json`, `wasm`, `pagefind`, `pf_meta`, `pf_index`, `pf_fragment`, `pf_filter` |
| `assets` | `css`, `woff`, `woff2`, `ttf` |

So `.js` and `.wasm` exist only under `/pagefind/`, CSS and fonts only under `/assets/`, and no
page or tag unit can hold a script or a stylesheet. An attachment is never published as `html`,
`htm`, `js`, `mjs`, `css` or `svg`: an SVG attachment is published as an image (`img-*.svg`), and
a type outside the list as `bin`.

## The tar

A unit's body is a tar:

- **uncompressed**, in pax or ustar format;
- of **regular files only** (`REGTYPE`): a directory entry, symlink, hard link, device, FIFO or
  sparse file is refused (`422 bad_member`);
- with **relative paths and no `./` prefix**: 1 to 4 segments joined by `/`, each matching
  `[A-Za-z0-9_][A-Za-z0-9._-]{0,99}` (so no leading `.`, no `..`, no absolute path), within the
  unit's own rule above;
- each path **once**, and no path that is also a folder of another (`a` and `a/b.html`);
- **not empty** (`422 empty_unit`);
- with no pax extended header, or GNU long-name or long-link header, over 64 KiB
  (`400 bad_tar`).

The extension is what follows the last `.` of the last segment, compared in lower case. The
receiver reads the tar member by member as it streams in, writing each file itself; it never
uses `extractall`. Any refusal leaves the site as it was.

## Limits

| Limit | Value | Over it |
| --- | --- | --- |
| Files in a unit | 10,000 | `413 too_many_files` |
| One file | 20 MiB | `413 file_too_large` |
| The request body | 256 MiB | `413 body_too_large`, from `Content-Length`, before the body is read |
| The site | `RECEIVER_QUOTA_BYTES`, 2 GiB | `507 over_quota`, counted over every live unit, the one being replaced at its new size; each file counts as its size rounded up to whole 4 KiB blocks, at least 4096 bytes |
| A request | 30 s | `408 timeout` |

scrap's own limits are tighter for a page: at most 20 images and files, each at most 20 MiB, and
at most 200 MiB for the unit ([](#what-scrap-sends-for-a-page)).

## The digest

Every `PUT` carries `Scrap-Digest: <64 lower-case hex>`: the SHA-256 of, for each file in sorted
path order (byte order; paths are ASCII), the line

```
<path> NUL <hex sha256 of the file's content> LF
```

concatenated. In Python:

```python
hashlib.sha256(b"".join(
    p.encode() + b"\0" + hashlib.sha256(files[p]).hexdigest().encode() + b"\n"
    for p in sorted(files)
)).hexdigest()
```

The receiver computes it again from the tar. A missing or different digest is
`400 digest_mismatch`, and nothing changes. It is also the unit's `digest` in the manifest.

## Endpoints

### `GET /healthz`

No token. Always `200 {"ok": true}` while the receiver runs.

### `GET /v1/manifest`

`200` with what the site holds:

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

`bytes` (the site's and each unit's) is the files' actual content in bytes; only the quota
counts in 4 KiB blocks ([](#limits)). `quota` is the limit, and `at` when the unit was last
written (UTC, ISO 8601, to the second).

### `PUT /v1/units/{unit}`

Replace a unit, or make it. Required: `Content-Type: application/x-tar` (`415
unsupported_media_type`), `Content-Length` (`411 length_required`; a chunked body is `411`
too, and a length that is not a number `400 bad_request`) and `Scrap-Digest`. Send
`Expect: 100-continue` where the client supports it ([](#transport-and-auth)).

One lock serialises every write (`PUT`, `DELETE`, `sync`). A request that cannot take it at once
gets `503 busy` with `Retry-After: 1`.

The swap is atomic, so nginx serves the old unit or the new one, never a mix or nothing: the
files are unpacked into `staging/<id>/` and fsynced, moved to `units/<id>/` with the unit's
manifest entry beside it, then a new symlink at `www/<unit>` replaces the old one with
`os.replace`, and the old copy is deleted.

`200` with the unit's manifest entry and `"unit"`. Other answers: `400 bad_tar`,
`400 short_body` (fewer bytes than `Content-Length`), `400 digest_mismatch`,
`422 bad_member`, `422 no_index`, `422 empty_unit`, `413`, `507`, `408`.

### `DELETE /v1/units/{unit}`

Remove a unit. `204`, also when it was not there, or `503 busy`.

### `POST /v1/sync`

`{"keep": ["home", "pagefind", "assets", "p/a", "t/b", ...]}` deletes every live unit not in the
list. It needs `Content-Type: application/json` (`415`) and `Content-Length` (`411`), with a body
of at most 1 MiB. `200 {"deleted": [...]}`. Refused: a body that is not `{"keep": [strings]}`
(`400 bad_request`), an empty list (`422 empty_keep`), a list without `home` (`422 no_home`),
and an entry that is not a unit (`422 bad_unit`).

## Errors

| Status | `error` | When |
| --- | --- | --- |
| `400` | `bad_request` | A malformed `Content-Length`, or a `sync` body that is not `{"keep": [...]}` |
| `400` | `short_body` | The body ended before `Content-Length` |
| `400` | `bad_tar` | The body is not a readable tar |
| `400` | `digest_mismatch` | `Scrap-Digest` missing or wrong |
| `401` | `unauthorized` | No token, or the wrong one |
| `404` | `not_found` | No such route |
| `405` | `method_not_allowed` | A method the route does not take (with `Allow`) |
| `408` | `timeout` | The request took over 30 s, or stalled |
| `411` | `length_required` | No `Content-Length`, or a chunked body |
| `413` | `body_too_large`, `too_many_files`, `file_too_large` | Over a limit |
| `415` | `unsupported_media_type` | The wrong `Content-Type` |
| `422` | `bad_unit` | Not a unit |
| `422` | `bad_member` | A member's type, path or extension is not allowed, it is there twice, or it is a folder too |
| `422` | `no_index` | A page, tag or home unit without `index.html` |
| `422` | `empty_unit` | A tar with no files |
| `422` | `empty_keep`, `no_home` | A `sync` list that is refused |
| `500` | `server_error` | Anything unexpected in the receiver |
| `503` | `busy` | Another write holds the lock (with `Retry-After: 1`) |
| `507` | `over_quota` | The site would be over its quota, or the disk itself is full |

`detail` never repeats the token or a header.

## The site folder

`RECEIVER_SITE` holds:

- `www/`: nginx's root, holding only each unit's symlink (`www/p/<slug>`, `www/t/<key>`,
  `www/home`, `www/pagefind`, `www/assets`) to its copy;
- `units/<id>/` and `units/<id>.json`: each unit's files and its manifest entry;
- `staging/`: uploads being unpacked.

`units/` and `staging/` are outside nginx's root, so they are never served. At start the receiver
empties `staging/`, rebuilds its index of live units from the symlinks, and removes every copy no
symlink refers to and anything else in `www/`. In Kubernetes the folder is an `emptyDir`: a
restarted pod starts empty and scrap fills it again ([](#reconciling)).

## nginx

nginx serves `www/` read only, as files. It takes `GET` and `HEAD` only (`405` otherwise), with
`autoindex off` and `server_tokens off`.

| Path | Serves |
| --- | --- |
| `/` | `home/index.html` |
| `/tags` | `home/tags.html` |
| `/robots.txt` | from nginx's own config: `User-agent: *` and `Disallow: /` (`Allow: /` with `INDEXING=on`) |
| `/p/<slug>`, `/p/<slug>/` | `p/<slug>/index.html` |
| `/p/<slug>/<name>` | `p/<slug>/<name>` |
| `/t/<key>`, `/t/<key>/` | `t/<key>/index.html` |
| `/t/<key>/<name>` | `t/<key>/<name>` |
| `/pagefind/<path>` | `pagefind/<path>` |
| `/assets/<path>` | `assets/<path>` |
| anything else | `home/404.html`, with `404` |

`<path>` and `<name>` follow the tar's segment rule. Only `/`, `/tags` and `/robots.txt` are
served at the top level: `/home/...`, `/units/...`, `/v1/...` and dotfiles are `404`.

Types come from the extension: `.md` as `text/markdown`, `.txt` as `text/plain`, `.ttf` as
`font/ttf`, `.wasm` as `application/wasm`, Pagefind's index files and `.bin` as
`application/octet-stream`; text types are `charset=utf-8`.

### Headers

On every response:

- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: no-referrer`
- `X-Robots-Tag: noindex, nofollow` (left out with `INDEXING=on`)

`Content-Security-Policy`, by path:

| Path | `Content-Security-Policy` |
| --- | --- |
| `/p/<slug>/file-*.pdf` | `sandbox` |
| `/p/<slug>/img-*`, `/p/<slug>/file-*` (not a PDF) | `sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:` |
| `/p/...` and `/t/...` otherwise (a page's or tag's HTML) | `default-src 'none'; img-src 'self' data:; style-src 'self'; style-src-attr 'unsafe-inline'; font-src 'self'; script-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'` |
| everything else (home, `/pagefind/`, `/assets/`, 404) | `default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; font-src 'self'; script-src 'self' 'wasm-unsafe-eval'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'` |

A page's images and files follow ADR 42's rule for stored files: opened on their own they run
nothing and load nothing, and a PDF keeps `sandbox` alone so a browser's PDF viewer works. Pages
and tag pages run no script. The home page's only scripts are Pagefind's and
`/pagefind/scrap-search.js` (scrap's start-up file; there is no inline script), which fetch the
index (`connect-src 'self'`) and run WebAssembly (`'wasm-unsafe-eval'`).

### Caching

- HTML: `Cache-Control: no-cache`, so a browser or proxy checks again before each use, and an
  unpublished page is gone on its next load.
- Every other file: `Cache-Control: public, max-age=300`, so a deleted file can be seen from a
  cache for up to five minutes more.

Nothing the site does reaches copies people saved, or caches that ignore these headers.

## The PWA's API in scrap

These routes are under `/api`, so only the owner's PWA session reaches them (behind Cloudflare
Access or Tailscale, as the rest of `/api`). They are **not** served under `/mcp`, and an MCP
bearer token cannot reach them: MCP never publishes HTML. Errors are scrap's usual
`{"error", "detail"}` JSON.

### The flag

`PATCH /api/pages/{id}` with `{"public": true}` or `{"public": false}`, or MCP
`edit_meta(public=...)`, sets `page.public`, as a revision that `revert` can undo.

- **On** only sets the flag. The page is published the next time the PWA renders it: through
  the Public toggle (which sets the flag, then publishes), a save, or Refresh all.
- **Off** unpublishes at once, whichever route turned it off, and so does the page going to the
  trash ([](#scraps-copies)).
- Undelete and revert keep the flag as it is. A page with `public` on and `published_at` null
  shows its badge as "Public · not published yet", and Refresh all publishes it. That is only a
  null timestamp, not stale tracking.

### `PUT /api/pages/{id}/published`

Publish the page. The body is JSON, at most 25 MiB:

```json
{"html": "<!DOCTYPE html>...", "rev": 42, "defer": false}
```

`html` is the page from `pagehtml.ts`'s publish mode, and `rev` the page's revision the PWA
rendered. With `defer: true` scrap pushes the page's unit but not `home`, the tag units or
`pagefind` (Refresh all, below).

Under scrap's lock, scrap reads the page again, then checks ([](#the-html-scrap-accepts)),
replaces the placeholders, builds the unit and pushes it. `200` with
`{"url": "<SCRAP_PUBLISH_SITE>/p/<slug>", "published_at": "<UTC ISO 8601>", "files": <n>}`.

| Status | `error` | When |
| --- | --- | --- |
| `409` | `not_public` | The page is not `public`, or it is in the trash |
| `409` | `stale` | `rev` is not the page's current revision |
| `413` | `too_large` | The body is over 25 MiB |
| `422` | from the check | The HTML fails a rule, or a cap ([](#placeholders-and-files)); `detail` says which |
| `502` | `publish_failed` | The receiver refused or failed; `detail` holds its `error` code |
| `503` | `not_configured` | Publishing is off (no `SCRAP_PUBLISH_TO` or token) |

A receiver `503 busy` is retried for up to 10 seconds before `502`.

### `GET /api/public`

The public pages: `[{"id", "slug", "title", "published_at"}]`, with `published_at` null for a
page not published yet. `?links_to=<slug>` lists only the public pages whose text links to that
page (from the backlinks). The PWA uses it to decide which links in a page stay live, to find
the pages to render again when a page is made public or private, and for Refresh all.

### `POST /api/public/rebuild`

Build `home`, every tag unit and `pagefind` once, and push those whose digest changed. Refresh
all sends each public page with `defer: true`, then calls this once.

## What scrap sends for a page

scrap **checks** the uploaded HTML, refusing anything that does not pass with `422` (it never
cleans the HTML), **replaces** its placeholders, adds the page's files, and pushes the unit.

### Parsing

- The HTML is parsed with a WHATWG-conformant parser (html5lib in Python), never a regular
  expression, `html.parser` or `lxml.html`, so scrap checks the tree a browser would build.
- Elements and attributes are matched as (namespace, local name), HTML, MathML or SVG. Anything
  not listed below is refused, which covers `xlink:href`, an SVG `a` and an SVG `style`.
- Values are checked after entity decoding. URL rules use `re.fullmatch`.
- Comments are dropped or allowed. CDATA sections, processing instructions and `template` are
  refused, as is an attribute given twice on one element.
- "A class includes `katex`" means `katex` is one of its whitespace-separated tokens.
- A `style` value is parsed as declarations, `property: value` separated by `;`, with spaces
  after `:` and a trailing `;` allowed.

### The HTML scrap accepts

The document is `<!DOCTYPE html>` with `html`, `head`, `title` and `body`; `html`, `head` and
`body` may have only `lang` and `dir`. In `head`, only:

- `<meta charset="utf-8">`;
- `<meta name="viewport" content="...">`;
- the CSP, which must be present:
  `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' data:; style-src 'self'; style-src-attr 'unsafe-inline'; font-src 'self'">`.
  Its parsed `content`, with whitespace normalised, must equal that exactly. There is no
  `script-src`, so no script runs even if the file is opened elsewhere;
- `<link rel="stylesheet" href="/assets/page.css">` (pagehtml's page CSS, moved out of the file),
  and, for a page with maths, `<link rel="stylesheet" href="/assets/katex.css">`. No other `link`.

There is **no `<style>` element** anywhere: every one is refused.

In `body`, only pagehtml's kept elements (`a abbr article aside b blockquote br caption code dd
del details div dl dt em figcaption figure h1 h2 h3 h4 h5 h6 hr i img ins kbd li mark ol p pre q
s section small span strong sub summary sup table tbody td tfoot th thead time tr u ul`), and,
inside a `span` whose class includes `katex` ("inside KaTeX" below), KaTeX's markup:

- MathML: `math semantics annotation mrow mi mn mo mtext mspace msup msub msubsup mfrac msqrt
  mroot mover munder munderover mtable mtr mtd mstyle mpadded mphantom menclose`;
- SVG: `svg`, `path` and `line`, which it draws stretchy symbols with.

Attributes:

| Attribute | Where | Value |
| --- | --- | --- |
| `class`, `dir` | any kept HTML element | any text |
| `colspan`, `rowspan` | `td`, `th` | 1 to 3 digits |
| `open` | `details` | none |
| `alt` | `img` | any text |
| `src` | `img` | a `scrap-blob:<sha>` placeholder, and nothing else |
| `href` | `a` | below |
| `aria-hidden` | `span` inside KaTeX | `true` |
| `style` | `span`, `mstyle`, `mpadded`, `svg` inside KaTeX | the declarations below |
| `xmlns` | `math`, `svg` | the MathML or SVG namespace |
| `width`, `height`, `viewBox`, `preserveAspectRatio` | `svg` | as KaTeX writes them, with no `url(` |
| `d` | `path` | as KaTeX writes it |
| `x1`, `y1`, `x2`, `y2`, `stroke-width` | `line` | as KaTeX writes them |
| `display`, `encoding`, `accent`, `accentunder`, `columnalign`, `columnlines`, `columnspacing`, `rowlines`, `rowspacing`, `depth`, `voffset`, `lspace`, `rspace`, `width`, `height`, `displaystyle`, `scriptlevel`, `mathsize`, `mathvariant`, `mathcolor`, `mathbackground`, `linethickness`, `fence`, `stretchy`, `separator`, `largeop`, `minsize`, `maxsize`, `linebreak`, `notation` | MathML inside KaTeX | as KaTeX writes them, with no `url(` |

An `a`'s `href` must fully match one of:

- `https?://...` to any host **except scrap's own origins** (`public.public_origins()`: the
  addresses in `SCRAP_PUBLIC_URL` and the like), which are refused;
- `mailto:...`, or `#...`;
- `/p/<slug>` of a page that is public, or `/t/<key>`;
- a placeholder, `scrap-blob:<sha>` or `scrap-tag:<tag>`.

`/api/...` is always refused, as are `//...` and `/\...` (a browser reads both as another host),
`javascript:`, `data:` and anything else. There is no rule about private (RFC 1918) addresses.

### KaTeX's markup

The publish mode writes each formula as `katex.renderToString(tex, options)`, with the PWA's
options from `web/src/math.ts` (`trust: false`, `throwOnError: true`, `strict: "ignore"`), so
the markup is KaTeX's own string, not the browser's serialisation of the page. The lists above
and below come from KaTeX 0.16.47, the version the PWA bundles: every `setAttribute(...)` and
every `.style.<property> =` in `katex.mjs`, checked by rendering a corpus with those options and
reading both halves of the output, the HTML and the MathML (fractions, roots, every matrix and
alignment environment, arrays with rules, `CD`, `\\[<size>]`, line breaks, `\color`,
`\colorbox`, `\fcolorbox`, `\boxed`, `\cancel`, `\angl`, stretchy arrows and accents, braces,
`\rule`, `\raisebox`, spacing, sizes, `\mathop`, `\pmb` and `\boldsymbol`). The attributes KaTeX
sets only with `trust` (`href`, `src`, `alt`, `valign` on `mglyph`) or only for an error it
renders instead of throwing (`title`) are not allowed. A new KaTeX version means checking the
lists again.

The `style` declarations allowed:

| Property | Value |
| --- | --- |
| `height`, `width`, `min-width`, `vertical-align`, `top`, `bottom`, `left`, `margin-left`, `margin-right`, `margin-top`, `padding-left`, `border-width`, `border-top-width`, `border-right-width`, `border-bottom-width` | a length |
| `margin` | one or two lengths |
| `color`, `background-color`, `border-color` | a colour |
| `border` (on `mpadded`, from `\fcolorbox`) | a length, `solid`, a colour |
| `border-style`, `border-right-style` | `solid` or `dashed` |
| `position` | `relative` |
| `text-shadow` (on `span` and `mstyle`, from `\pmb`) | three lengths |

A length is `-?([0-9]+|[0-9]*\.[0-9]+)(em|ex|px)?`. A colour is `#` and 3, 4, 6 or 8 hex digits,
`rgb(...)` or `rgba(...)` of numbers and `%`, or a name of letters only (`red`, `Goldenrod`,
`transparent`). Any other property or value, or `style` outside KaTeX, is refused.

**The `katex` gate is visual hygiene, not a security boundary.** It keeps stray markup and
inline styles out of the page's own content, but a page could wrap anything in a `katex` span.
What keeps a public page safe is the CSP (the page's meta CSP and nginx's, with
`script-src 'none'`), the allow-list of elements and attributes, and that the upload is reachable
only from the owner's PWA session.

### Placeholders and files

- `scrap-blob:[0-9a-f]{64}` names a stored file by its sha. It is replaced only when it is the
  whole value of an `img`'s `src` or an `a`'s `href`; anywhere else (in text, say) it is left as
  text. The element decides the kind: an `img` is published as an image, an `a` as a file. A
  file used both ways is published once as each; a file used twice the same way, once.
- `scrap-tag:<tag, URL-encoded>` as an `href` (a tag chip) is replaced by `/t/<key>`
  ([](#tag-keys)).
- A placeholder naming a file that is not on the page, or a tag the page does not have, refuses
  the publish.
- **Drawings (Excalidraw) are not published** in this version: the publish mode leaves them out,
  and a photo with a drawing on it is published as the photo alone. Publishing drawings is a
  follow-up.

Each `scrap-blob` becomes an absolute path, `/p/<slug>/<name>` (absolute, because a relative link
from `/p/<slug>` would resolve under `/p/`), and scrap adds the bytes beside `index.html`:

| Published as | Name | `kind` in `files.json` | Bytes |
| --- | --- | --- | --- |
| A photo or raster image | `img-<n>-<hex>.jpg` (`.png` when its preview is a PNG) | `img` | Its 2048-pixel preview, EXIF and GPS stripped when the preview was made |
| An SVG, as an image or as an attachment | `img-<n>-<hex>.svg` | `img` | The stored SVG, run through scrap's SVG sanitiser again at publish (SVGs stored before #480 were never sanitised) |
| Another attachment | `file-<n>-<hex>.<ext>` | `file` | The file as stored; `<ext>` from the list in [](#units), else `bin` |

- `<n>` counts images and files separately, from 1, in the order they first appear in the HTML.
- `<hex>` is the first 10 hex digits of the SHA-256 of the bytes published. Neither the stored
  sha nor the uploaded file name is published (a link's label may show the name).
- **Caps:** at most 20 images and files together, each at most 20 MiB, and at most 200 MiB for
  the whole unit (under the receiver's 256 MiB body). Over any of them scrap refuses the publish
  with `422` and a message saying which, before pushing anything.
- **Time:** the receiver's 30 seconds cover the whole request, body included, so a unit must also
  be one scrap can upload in 30 s on its link to the receiver (200 MiB needs about 56 Mbit/s).
  scrap's client sends `Expect: 100-continue`. A `408` is logged as a failure, and the next
  reconcile tries the unit again.

### Tag keys

A tag's key is computed only in Python, by scrap. It is **not** `slug_base`, the rule for a
page's slug:

1. Take the tag as stored. `h` is the first 8 hex digits of the SHA-256 of its UTF-8 bytes.
2. Normalise it to Unicode NFKD, encode it as ASCII dropping every character that has no ASCII
   form, and lower-case it.
3. Replace each run of characters other than `a-z` and `0-9` with one `-`, and strip `-` from both
   ends.
4. Cut it to 60 characters and strip `-` from the end again.
5. The key is that slug, `-`, then `h`; or `h` alone if the slug is empty.

So `personal/family` is `personal-family-` followed by 8 hex digits (for example
`personal-family-1a2b3c4d`). A key is at most 69 characters, inside the `t/` pattern, and two tags
with the same slug still get different keys.

## What scrap builds

From its kept copies and their `meta.json` ([](#scraps-copies)), with plain Python templates and
no Markdown:

- `home`: `index.html` (the public pages by `published_at`, newest first, with their tags and
  Pagefind's search box), `tags.html` (every tag with its pages) and `404.html`;
- a `t/<key>` unit for each tag a public page has, listing its pages;
- `pagefind`: the index, built by the `pagefind[bin]` Python package at a pinned version, plus
  Pagefind's UI files and `scrap-search.js`, which starts the UI. Each page is indexed from an
  in-memory copy with its `.katex` elements removed and the formula's TeX (from its
  `annotation encoding="application/x-tex"`) put in their place, so search finds the TeX, not
  KaTeX's glyph spans;
- `assets`: `page.css` (pagehtml's page CSS), `katex.css` and KaTeX's fonts, from scrap's own
  static build of the PWA, and Pagefind's UI stylesheet, as CSS lives only in `assets`.

Titles and tag names come from `meta.json`. Every build is deterministic: the same copies give
the same bytes (sorted order, no timestamps), so an unchanged unit has an unchanged digest.

## scrap's copies

For each published page scrap keeps the unit exactly as it last pushed it, under
`<data>/cache/publish/p/<slug>/`:

- `index.html` (placeholders replaced), every `img-*` and `file-*`;
- `files.json`, which maps each published name to
  `{"sha": <stored file>, "kind": "img" | "file", "bytes_sha256": <hex>}`;
- `meta.json`: `{"id", "title", "tags", "published_at"}`, the tags being the page's current
  tags in the database at publish time.

It is derived data, not backed up. scrap also stores the digest it last pushed for every unit.

**One lock in scrap** is held over every publish, unpublish and reconcile step, so they never
interleave.

- **Publish:** read the page again and refuse unless it is public and not in the trash (`409
  not_public`); check and build the page unit, push it, write the copy, `meta.json` and the
  digest; then, unless deferred, build `home`, the page's tag units (before and after) and
  `pagefind`, and push those whose digest changed.
- **Unpublish** (Public off in the PWA or over MCP, a revert, the page going to the trash):
  delete scrap's copy first, then `DELETE /v1/units/p/<slug>`, then build and push `home`, the
  page's tag units (deleting a tag unit no public page has any more) and `pagefind`.

## Reconciling

At startup, scrap first builds the derived units fresh (`home`, every `t/*`, `pagefind` and
`assets`) and pushes any whose digest changed, which covers a new KaTeX, new templates or a new
Pagefind after an upgrade. Then, at startup and every 10 minutes, under the lock, scrap:

1. works out the units to keep: the kept page copies whose pages are public and not in the
   trash, their tags, `home`, `pagefind` and `assets`. A kept copy of any other page is deleted,
   with its unit;
2. reads `GET /v1/manifest`;
3. compares each unit's manifest digest with the digest it last pushed and stored (not with a
   fresh build), and `PUT`s the unit again from its kept bytes when it is missing or differs. A
   page's copy is re-read under the lock before each `PUT`. A kept copy that is missing or
   damaged (a file gone, or bytes that no longer match `files.json`) is not pushed: scrap deletes
   the copy and the unit, then rebuilds `home`, the tag units and `pagefind`; the next Refresh
   all publishes the page again;
4. ends with `POST /v1/sync` listing the units to keep, which deletes any stray.

No rendering is involved, so a site that lost its files is refilled without the PWA. A `503` is
retried; any other failure is logged and left to the next run.
