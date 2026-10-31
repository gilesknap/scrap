#!/bin/sh
# Checks a built scrap-public image as the chart runs it: the receiver and nginx
# in two containers, read-only root filesystems, sharing one site volume. Uploads
# through the receiver (a tar and digest made with tar and sha256sum, not Python,
# as a cross-check of the contract), then reads through nginx.
#   ./scrap-public/test-image.sh [IMAGE]       (default scrap-public:test)
#   RUNTIME=podman ./scrap-public/test-image.sh  (default: docker, else podman)
# Needs curl, tar (GNU) and sha256sum.
set -eu

image=${1:-scrap-public:test}
rt=${RUNTIME:-$(command -v docker || command -v podman)}
run_id=scrap-public-test-$$
token=$(head -c 30 /dev/urandom | od -An -tx1 | tr -d ' \n')
work=$(mktemp -d)
fail=0
# shellcheck disable=SC2329 # run by the trap
cleanup() {
    "$rt" rm -f "$run_id-rcv" "$run_id-web" "$run_id-idx" >/dev/null 2>&1 || true
    "$rt" volume rm -f "$run_id" >/dev/null 2>&1 || true
    rm -rf "$work"
}
trap cleanup EXIT
ok() { echo "ok   $1"; }
bad() {
    echo "FAIL $1"
    fail=1
}
check() { # DESCRIPTION command...
    d=$1
    shift
    if "$@"; then ok "$d"; else bad "$d"; fi
}

# The port a container's PORT is published on
port() { "$rt" port "$1" "$2/tcp" | head -1 | sed 's/.*://'; }

"$rt" volume create "$run_id" >/dev/null
common="--read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges"
# shellcheck disable=SC2086 # $common is several options
"$rt" run -d --name "$run_id-rcv" $common -v "$run_id:/site" -e RECEIVER_TOKEN="$token" \
    -p 127.0.0.1::8081 "$image" receive >/dev/null
# shellcheck disable=SC2086
"$rt" run -d --name "$run_id-web" $common -v "$run_id:/site:ro" \
    -p 127.0.0.1::8080 "$image" web >/dev/null
# shellcheck disable=SC2086
"$rt" run -d --name "$run_id-idx" $common -v "$run_id:/site:ro" -e INDEXING=on \
    -p 127.0.0.1::8080 "$image" web >/dev/null
rcv="http://127.0.0.1:$(port "$run_id-rcv" 8081)"
web="http://127.0.0.1:$(port "$run_id-web" 8080)"
idx="http://127.0.0.1:$(port "$run_id-idx" 8080)"

up=""
for _ in $(seq 50); do
    if curl -fsS "$rcv/healthz" >/dev/null 2>&1 && curl -sS "$web/robots.txt" >/dev/null 2>&1 &&
        curl -sS "$idx/robots.txt" >/dev/null 2>&1; then
        up=1
        break
    fi
    sleep 0.2
done
if [ -z "$up" ]; then
    "$rt" logs "$run_id-rcv"
    "$rt" logs "$run_id-web"
    bad "the containers did not start"
    exit 1
fi
ok "receiver and nginx start with read-only root filesystems"
check "the receiver runs as uid 10001" [ "$("$rt" exec "$run_id-rcv" id -u)" = 10001 ]
check "nginx runs as uid 10001" [ "$("$rt" exec "$run_id-web" id -u)" = 10001 ]

# A unit's tar and Scrap-Digest: sha256 of "path NUL sha256hex LF" in sorted order
make_unit() { # DIR -> $work/unit.tar, $digest
    (cd "$1" && find . -type f | sed 's|^\./||' | LC_ALL=C sort >"$work/list")
    tar --format=ustar --owner=0 --group=0 --numeric-owner -cf "$work/unit.tar" \
        -C "$1" -T "$work/list"
    digest=$(while read -r f; do
        printf '%s\000%s\n' "$f" "$(sha256sum <"$1/$f" | cut -d' ' -f1)"
    done <"$work/list" | sha256sum | cut -d' ' -f1)
}
put() { # UNIT DIR [TOKEN] -> HTTP status
    make_unit "$2"
    curl -sS -o "$work/out" -w '%{http_code}' -X PUT "$rcv/v1/units/$1" \
        -H "Authorization: Bearer ${3:-$token}" -H "Content-Type: application/x-tar" \
        -H "Scrap-Digest: $digest" --data-binary "@$work/unit.tar"
}
status() { curl -sS -o /dev/null -w '%{http_code}' --path-as-is "$@"; }
header() { # URL NAME -> the header's value
    curl -sS -o /dev/null -D - "$1" | tr -d '\r' | sed -n "s/^$2: //Ip"
}

mkdir -p "$work/page" "$work/home" "$work/tag" "$work/pagefind/fragment" "$work/assets/fonts"
echo '<p>a public page</p>' >"$work/page/index.html"
echo '%PDF-1.7' >"$work/page/file-1-0123456789.pdf"
echo '# notes' >"$work/page/file-2-0123456789.md"
echo '<svg xmlns="http://www.w3.org/2000/svg"/>' >"$work/page/img-1-0123456789.svg"
echo '<p>home</p>' >"$work/home/index.html"
echo '<p>tags</p>' >"$work/home/tags.html"
echo '<p>not here</p>' >"$work/home/404.html"
echo '<p>a tag</p>' >"$work/tag/index.html"
echo 'export {}' >"$work/pagefind/pagefind.js"
echo 'x' >"$work/pagefind/fragment/en_1.pf_fragment"
echo '.katex{}' >"$work/assets/katex.css"
echo 'ttf' >"$work/assets/fonts/KaTeX_Main.ttf"
mkdir -p "$work/bad"
echo '<p>x</p>' >"$work/bad/index.html"
echo 'alert(1)' >"$work/bad/app.js"

check "a bad token is 401" [ "$(put p/a-page "$work/page" "x$token")" = 401 ]
check "PUT p/a-page through the receiver" [ "$(put p/a-page "$work/page")" = 200 ]
check "PUT home through the receiver" [ "$(put home "$work/home")" = 200 ]
check "PUT t/a-tag-0123abcd" [ "$(put t/a-tag-0123abcd "$work/tag")" = 200 ]
check "PUT pagefind" [ "$(put pagefind "$work/pagefind")" = 200 ]
check "PUT assets" [ "$(put assets "$work/assets")" = 200 ]
check "a page holding a script is refused" [ "$(put p/bad "$work/bad")" = 422 ]
check "the manifest lists them" sh -c "curl -fsS -H 'Authorization: Bearer $token' \
    '$rcv/v1/manifest' | grep -q '\"assets\"' "

check "/p/a-page is the page" [ "$(curl -fsS "$web/p/a-page")" = '<p>a public page</p>' ]
check "/p/a-page/ is the page" [ "$(curl -fsS "$web/p/a-page/")" = '<p>a public page</p>' ]
check "/ is home/index.html" [ "$(curl -fsS "$web/")" = '<p>home</p>' ]
check "/tags is home/tags.html" [ "$(curl -fsS "$web/tags")" = '<p>tags</p>' ]
check "/t/<key> is the tag page" [ "$(curl -fsS "$web/t/a-tag-0123abcd")" = '<p>a tag</p>' ]
check "an attached file is served" \
    [ "$(curl -fsS "$web/p/a-page/file-1-0123456789.pdf")" = '%PDF-1.7' ]
check "/pagefind/ serves the index" \
    [ "$(curl -fsS "$web/pagefind/fragment/en_1.pf_fragment")" = x ]
check "/assets/ serves the CSS" [ "$(curl -fsS "$web/assets/katex.css")" = '.katex{}' ]
check "a missing page is 404" [ "$(status "$web/p/nope")" = 404 ]
check "a 404 shows home/404.html" [ "$(curl -sS "$web/p/nope")" = '<p>not here</p>' ]
check "HEAD works" [ "$(status -I "$web/p/a-page")" = 200 ]
for path in /tags.html /index.html /404.html /home /anything.html; do
    check "only /, /tags and /robots.txt at the top: $path is 404" [ "$(status "$web$path")" = 404 ]
done

csp_home="default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; font-src 'self'; script-src 'self' 'wasm-unsafe-eval'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
csp_page="default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; font-src 'self'; script-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
strict="sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:"
check "a page's CSP runs no script" [ "$(header "$web/p/a-page" content-security-policy)" = "$csp_page" ]
check "a tag page's CSP runs no script" \
    [ "$(header "$web/t/a-tag-0123abcd" content-security-policy)" = "$csp_page" ]
check "home's CSP allows Pagefind" [ "$(header "$web/" content-security-policy)" = "$csp_home" ]
check "/pagefind/ has home's CSP" \
    [ "$(header "$web/pagefind/pagefind.js" content-security-policy)" = "$csp_home" ]
check "/assets/ has home's CSP" \
    [ "$(header "$web/assets/katex.css" content-security-policy)" = "$csp_home" ]
check "a 404 has home's CSP" [ "$(header "$web/p/nope" content-security-policy)" = "$csp_home" ]
check "a PDF attachment keeps sandbox alone" \
    [ "$(header "$web/p/a-page/file-1-0123456789.pdf" content-security-policy)" = sandbox ]
check "another attachment is sandboxed and loads nothing" \
    [ "$(header "$web/p/a-page/file-2-0123456789.md" content-security-policy)" = "$strict" ]
check "an image is sandboxed and loads nothing" \
    [ "$(header "$web/p/a-page/img-1-0123456789.svg" content-security-policy)" = "$strict" ]
check "an attachment keeps nosniff" \
    [ "$(header "$web/p/a-page/file-2-0123456789.md" x-content-type-options)" = nosniff ]
check "Markdown is text/markdown" \
    [ "$(header "$web/p/a-page/file-2-0123456789.md" content-type)" = "text/markdown; charset=utf-8" ]
check "a .ttf is font/ttf" [ "$(header "$web/assets/fonts/KaTeX_Main.ttf" content-type)" = font/ttf ]
check "nosniff" [ "$(header "$web/p/a-page" x-content-type-options)" = nosniff ]
check "no referrer" [ "$(header "$web/p/a-page" referrer-policy)" = no-referrer ]
check "noindex" [ "$(header "$web/p/a-page" x-robots-tag)" = "noindex, nofollow" ]
check "HTML is no-cache" [ "$(header "$web/p/a-page" cache-control)" = no-cache ]
check "files are max-age=300" \
    [ "$(header "$web/p/a-page/file-1-0123456789.pdf" cache-control)" = "public, max-age=300" ]
check "a PDF is application/pdf" \
    [ "$(header "$web/p/a-page/file-1-0123456789.pdf" content-type)" = application/pdf ]
check "no server version" [ "$(header "$web/" server)" = nginx ]
check "robots.txt disallows all" sh -c "curl -fsS '$web/robots.txt' | grep -qx 'Disallow: /'"
check "INDEXING=on: no X-Robots-Tag" [ -z "$(header "$idx/p/a-page" x-robots-tag)" ]
check "INDEXING=on: robots.txt allows" sh -c "curl -fsS '$idx/robots.txt' | grep -qx 'Allow: /'"

for path in /v1/manifest /v1/units/home /healthz; do
    check "nginx has no $path" [ "$(status -H "Authorization: Bearer $token" "$web$path")" = 404 ]
done
uid=$("$rt" exec "$run_id-rcv" sh -c 'readlink /site/www/p/a-page' | sed 's|.*/||')
check "the unit's copy has an id" [ -n "$uid" ]
for path in "/units/$uid/index.html" "/staging/" "/www/p/a-page" "/home/index.html" \
    "/p/a-page/../../../units/$uid/index.html" "/p/a-page/%2e%2e/%2e%2e/units/$uid/index.html" \
    "/p/a-page/..%2f..%2f..%2funits/$uid/index.html" "/p/" "/p" "/pagefind/" "/.." \
    "/home/../../units/$uid/index.html"; do
    check "nginx refuses $path" [ "$(status "$web$path")" -ge 400 ]
done
for method in POST PUT DELETE PATCH; do
    check "nginx refuses $method" [ "$(status -X "$method" -d x "$web/p/a-page")" = 405 ]
done
check "the site volume is read only in the web container" \
    sh -c "! '$rt' exec '$run_id-web' sh -c 'echo x >/site/www/x' 2>/dev/null"

check "DELETE p/a-page" [ "$(curl -sS -o /dev/null -w '%{http_code}' -X DELETE \
    -H "Authorization: Bearer $token" "$rcv/v1/units/p/a-page")" = 204 ]
check "a deleted page is 404" [ "$(status "$web/p/a-page")" = 404 ]

# A clean stop on SIGTERM (what Kubernetes sends): exit 0, well within the grace
# shellcheck disable=SC2329 # run through check
stopped() { # CONTAINER
    "$rt" stop -t 10 "$1" >/dev/null &&
        [ "$("$rt" inspect -f '{{.State.ExitCode}}' "$1")" = 0 ]
}
check "the receiver stops cleanly on SIGTERM" stopped "$run_id-rcv"
check "nginx stops cleanly on SIGTERM" stopped "$run_id-web"

if [ "$fail" != 0 ]; then
    "$rt" logs "$run_id-rcv" 2>&1 | tail -20
    "$rt" logs "$run_id-web" 2>&1 | tail -20
fi
exit "$fail"
