#!/bin/sh
# scrap-public's entrypoint: `web` runs nginx on the site (port 8080), `receive` runs
# the upload receiver (RECEIVER_LISTEN, default tcp:0.0.0.0:8081). In Kubernetes they
# are two containers of one pod sharing the site volume at /site.
#   INDEXING=on   (web) let search engines index the site; default off: noindex
set -eu

case "${1:-}" in
web)
    case "${INDEXING:-off}" in
    on)
        robots_tag=""
        robots_txt='User-agent: *\\nAllow: /\\n'
        ;;
    off)
        robots_tag="noindex, nofollow"
        robots_txt='User-agent: *\\nDisallow: /\\n'
        ;;
    *)
        echo "scrap-public: INDEXING must be on or off, not '$INDEXING'" >&2
        exit 2
        ;;
    esac
    # An empty X-Robots-Tag value makes nginx leave the header out. The robots.txt
    # text keeps its \n escapes for nginx's quoted string (sed turns \\ into \).
    sed -e "s|@X_ROBOTS_TAG@|$robots_tag|" -e "s|@ROBOTS_TXT@|$robots_txt|" \
        /etc/scrap-public/nginx.conf.template >/tmp/nginx.conf
    exec nginx -e stderr -c /tmp/nginx.conf -g 'daemon off;'
    ;;
receive)
    exec python3 -I /usr/local/lib/scrap-public/receiver.py
    ;;
*)
    echo "usage: scrap-public web|receive" >&2
    exit 2
    ;;
esac
