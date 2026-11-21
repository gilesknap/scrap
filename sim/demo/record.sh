#!/bin/bash
# The demo video (#549), end to end: build the sim (unless sim/out is there; --rebuild to
# force), its demo cut, record it with Playwright, then an MP4 and a GIF of the capture beat.
#   sim/demo/record.sh [--rebuild] [record.mjs options: --fast, --pace N]
# Outputs in ${DEMO_OUT:-_claude/demo-video}: demo.webm, demo.mp4, demo-web.mp4 (under 10 MB),
# capture.gif, frames/.
# The MP4 and GIF need an ffmpeg with libx264 on PATH: Playwright's own ffmpeg only
# encodes VP8 WebM (it has no H.264, GIF or even VP8 decoder).
set -euo pipefail
DEMO=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SIM=$(dirname "$DEMO")
REPO=$(dirname "$SIM")
export DEMO_OUT=${DEMO_OUT:-$REPO/_claude/demo-video}
mkdir -p "$DEMO_OUT"

# sim/build.sh and mock.py call python3: shim one from uv's when there is none on PATH
if ! command -v python3 >/dev/null; then
  SHIM="$DEMO_OUT/.bin"
  mkdir -p "$SHIM"
  printf '#!/bin/sh\nexec %s "$@"\n' "$(cd / && uv python find --system)" > "$SHIM/python3"
  chmod +x "$SHIM/python3"
  export PATH="$SHIM:$PATH"
fi

if [ "${1:-}" = --rebuild ] || [ ! -f "$SIM/out/sim.js" ]; then
  [ "${1:-}" = --rebuild ] && shift
  "$SIM/build.sh"
fi
"$DEMO/build.sh"
node "$DEMO/record.mjs" --out "$DEMO_OUT" "$@"

FFMPEG=$(command -v ffmpeg || true)
if [ -z "$FFMPEG" ]; then
  echo "no ffmpeg on PATH: $DEMO_OUT/demo.webm only (no MP4 or GIF)" >&2
  exit 0
fi
"$FFMPEG" -y -loglevel error -i "$DEMO_OUT/demo.webm" -an -c:v libx264 -pix_fmt yuv420p \
  -preset slow -crf 18 -movflags +faststart "$DEMO_OUT/demo.mp4"
# A copy under 10 MB for a GitHub attachment: 1080p at a higher CRF while it fits, else 720p
for v in "28 1080" "32 1080" "36 1080" "30 720" "34 720"; do
  set -- $v
  "$FFMPEG" -y -loglevel error -i "$DEMO_OUT/demo.webm" -an -c:v libx264 -pix_fmt yuv420p -preset slow \
    -crf "$1" -vf "scale=-2:$2" -movflags +faststart "$DEMO_OUT/demo-web.mp4"
  size=$(stat -c %s "$DEMO_OUT/demo-web.mp4")
  echo "demo-web.mp4: ${2}p, CRF $1, $((size / 1024)) KiB"
  [ "$size" -lt 10000000 ] && break
done
# The photo capture (camera to Claude's reading) as a GIF: the phone side, a third size
read -r FROM LEN < <(node -e 'const b = require(process.argv[1]); const f = Math.max(0, (b["camera-view"] ?? 5) - 3);
  console.log(f.toFixed(2), ((b["photo-read"] ?? f + 25) + 3 - f).toFixed(2))' "$DEMO_OUT/beats.json")
"$FFMPEG" -y -loglevel error -ss "$FROM" -t "$LEN" -i "$DEMO_OUT/demo.webm" \
  -vf "crop=600:1080:20:0,fps=10,scale=300:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse" \
  "$DEMO_OUT/capture.gif"
# A frame every 8 s, to look at
rm -rf "$DEMO_OUT/video-frames" && mkdir -p "$DEMO_OUT/video-frames"
"$FFMPEG" -y -loglevel error -i "$DEMO_OUT/demo.webm" -vf fps=1/8 "$DEMO_OUT/video-frames/f%02d.png"
ls -l "$DEMO_OUT"/demo.* "$DEMO_OUT"/demo-web.mp4 "$DEMO_OUT/capture.gif"
