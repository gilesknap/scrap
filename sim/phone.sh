#!/bin/bash
# Put the sim, built from this checkout, on GitHub Pages as an installable test copy of scrap, so
# the owner can try it on his real phone (Chrome's zoom, the installed app, restarts) in minutes,
# without a release. See sim/README.md, "Phone test copies".
#
#   sim/phone.sh NAME            build, then publish to https://<owner>.github.io/scrap/NAME/
#   sim/phone.sh --delete NAME   remove it again
#
# NAME is a short folder name (letters, digits, -). It goes on the gh-pages branch beside the
# docs, whose deploy keeps other files. Pushes need write access to the repo.
set -euo pipefail
SIM="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$SIM")"
delete=0
if [ "${1:-}" = "--delete" ]; then delete=1; shift; fi
NAME="${1:?usage: sim/phone.sh [--delete] NAME}"
[[ "$NAME" =~ ^[a-z0-9-]+$ ]] || { echo "NAME: lowercase letters, digits and - only" >&2; exit 2; }
URL="$(git -C "$REPO" remote get-url origin)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
git clone -q --depth 1 -b gh-pages "$URL" "$WORK/pages"
cd "$WORK/pages"
rm -rf "$NAME"
if [ "$delete" = 1 ]; then
  git add -A "$NAME" 2>/dev/null || true
  git commit -q -m "Remove the phone test copy $NAME" || { echo "nothing to remove"; exit 0; }
  git push -q origin gh-pages
  echo "removed $NAME"
  exit 0
fi
"$SIM/build.sh"
mkdir "$NAME"
cp -r "$SIM/out/." "$NAME/"
cp "$SIM/phone/probe.js" "$SIM/phone/test-sw.js" "$NAME/"
branch="$(git -C "$REPO" rev-parse --abbrev-ref HEAD)"
commit="$(git -C "$REPO" rev-parse --short HEAD)"
python3 -I - "$NAME" "$branch" <<'PY'
import json, pathlib, sys
d, branch = pathlib.Path(sys.argv[1]), sys.argv[2]
json.dump({
    "name": f"scrap test {d.name}", "short_name": f"scrap {d.name}"[:12],
    "start_url": "./", "scope": "./", "display": "standalone",
    "background_color": "#161411", "theme_color": "#161411",
    "icons": [{"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
              {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"},
              {"src": "icon-maskable.png", "sizes": "512x512", "type": "image/png",
               "purpose": "maskable"}],
}, open(d / "manifest.webmanifest", "w"), indent=1)
f = d / "index.html"
s = f.read_text()
# build.sh strips the document skeleton for the artifact host: put it back, with the manifest
# and the readout, so the page is a standalone, installable app
s = s.replace("<title>scrap sim</title>",
              f"<title>scrap test {d.name}</title>\n"
              '    <link rel="manifest" href="./manifest.webmanifest" />\n'
              '    <script src="./probe.js"></script>', 1)
s = s.replace("<header>", "</head>\n<body>\n<header>", 1)
f.write_text(f'<!doctype html>\n<html lang="en">\n<head>\n<!-- {branch} -->\n{s}\n</body>\n</html>\n')
PY
git add -A "$NAME"
git commit -q -m "Phone test copy $NAME: the sim from $branch ($commit)"
git push -q origin gh-pages
owner="$(echo "$URL" | sed -E 's#.*github.com[:/]([^/]+)/.*#\1#')"
echo "published: https://$owner.github.io/scrap/$NAME/ (live in a minute or two)"
