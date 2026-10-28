"""Print the files map for publishing sim/out to the sim artifact.

    python3 sim/files.py [--static] [PREVIOUS.json] > files.json

By default: every file in sim/out except index.html (the publish's file_path) and
the two folders that never change between builds, blobs/ (the sample photos) and
excalidraw/ (the drawing fonts). They are already on the sim artifact, and files
left out of a publish are kept, so a normal publish need not send them. They also
keep a publish under the 255-file limit: the build is about 260 files.

--static prints only blobs/ and excalidraw/, for a new artifact (publish the
default map first, then this one to the same url) or to resend them.

The output is a map {"published/path": "source/path"} (the same, with root=sim/out).
Given the map of the previous publish, it adds "path": null for each file in it that
the build no longer has, so the publish removes it from the artifact (Vite renames
and re-splits chunks when the app changes). See sim/README.md.
"""

import json
import sys
from pathlib import Path

OUT = Path(__file__).parent / "out"
STATIC = ("blobs/", "excalidraw/")

args = sys.argv[1:]
static = "--static" in args
args = [a for a in args if a != "--static"]

names = sorted(p.relative_to(OUT).as_posix() for p in OUT.rglob("*") if p.is_file())
if static:
    names = [n for n in names if n.startswith(STATIC)]
else:
    names = [n for n in names if n != "index.html" and not n.startswith(STATIC)]
files: dict[str, str | None] = {n: n for n in names}

if args:
    prev = json.loads(Path(args[0]).read_text())
    prev = prev if isinstance(prev, dict) else [p["path"] for p in prev]
    for n in prev:
        if n not in files and (n.startswith(STATIC) == static) and n != "index.html":
            files[n] = None

json.dump(files, sys.stdout, indent=0)
print()
gone = sum(v is None for v in files.values())
print(f"{len(files) - gone} files, {gone} removed", file=sys.stderr)
