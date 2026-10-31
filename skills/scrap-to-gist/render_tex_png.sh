#!/bin/bash
# usage: render_tex_png.sh TEXFILE COLOR OUT.png
# Renders the TeX in TEXFILE as display maths with KaTeX (as scrap does) in headless
# Chrome: 2x pixels, transparent background. Prints the CSS size; the width is the one to
# use in <img width=...>. Light: '#1f2328', dark: '#f0f6fc'.
# Needs python3, internet (KaTeX from jsDelivr, the version scrap bundles) and Chrome or
# Chromium; set CHROME to its path if it is not on PATH as google-chrome, chromium or
# chromium-browser. Each run uses its own temporary folder, so runs can go in parallel.
set -eu
katex=0.16.47  # web/package.json in scrap
color=$2
out=$(realpath -m "$3")
chrome=${CHROME:-$(command -v google-chrome || command -v chromium || command -v chromium-browser || true)}
if [ -z "$chrome" ]; then
    echo "render_tex_png.sh: no Chrome or Chromium found; set CHROME" >&2
    exit 1
fi
if ! [[ $color =~ ^#[0-9a-fA-F]{3,8}$ ]]; then
    echo "render_tex_png.sh: COLOR must be like '#1f2328'" >&2
    exit 1
fi
# The TeX goes into the page as a JSON string, with "</" written "<\/" so it cannot end
# the <script>
tex=$(python3 -c 'import json,sys; print(json.dumps(open(sys.argv[1]).read().strip()).replace("</", "<\\/"))' "$1")
dir=$(mktemp -d)
trap 'rm -rf "$dir"' EXIT
cat > "$dir/page.html" <<H
<!DOCTYPE html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@$katex/dist/katex.min.css">
<script src="https://cdn.jsdelivr.net/npm/katex@$katex/dist/katex.min.js"></script>
<style>html,body{margin:0;background:transparent}#m{display:inline-block;padding:6px 10px;color:$color;font-size:16px}#m .katex-display{margin:0}</style></head>
<body><span id="m"></span><script>
katex.render($tex, document.getElementById('m'), {displayMode:true, throwOnError:true});
document.fonts.ready.then(()=>{const r=document.getElementById('m').getBoundingClientRect();
document.title=Math.ceil(r.width)+'x'+Math.ceil(r.height);});
</script></body></html>
H
size=$(timeout 60 "$chrome" --headless=new --disable-gpu --no-sandbox --user-data-dir="$dir/profile" \
  --virtual-time-budget=10000 --dump-dom "$dir/page.html" 2>/dev/null |
  grep -o '<title>[0-9x]*' | sed 's/<title>//' || true)
if [ -z "$size" ]; then
    echo "render_tex_png.sh: KaTeX did not render (no internet, or bad TeX?)" >&2
    exit 1
fi
w=${size%x*}; h=${size#*x}
timeout 60 "$chrome" --headless=new --disable-gpu --no-sandbox --user-data-dir="$dir/profile" \
  --hide-scrollbars --virtual-time-budget=5000 --default-background-color=00000000 \
  --force-device-scale-factor=2 --window-size="$w,$h" --screenshot="$out" "$dir/page.html" >/dev/null 2>&1
echo "$out ${w}x${h} css px"
