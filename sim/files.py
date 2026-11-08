"""Print the files map for publishing sim/out to the sim artifact.

    python3 sim/files.py [--static] [--part N/M] [PREVIOUS.json] > files.json

By default: every file in sim/out except index.html (the publish's file_path) and
the two folders that never change between builds, blobs/ (the sample photos) and
excalidraw/ (the drawing fonts). They are already on the sim artifact, and files
left out of a publish are kept, so a normal publish need not send them.

--part N/M prints the Nth of M near-equal slices of the map (by path): one publish
takes at most 255 files and the map is now about 285, so publish --part 1/2 and then
--part 2/2 to the same url, one straight after the other.

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
part = next((a for a in args if a.startswith("--part")), None)
if part:
    i = args.index(part)
    spec = part.split("=", 1)[1] if "=" in part else args.pop(i + 1)
    args.remove(part)
    part_n, parts = (int(x) for x in spec.split("/"))
    if not 1 <= part_n <= parts:
        sys.exit(f"--part {spec}: N must be from 1 to M")

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

if part:
    keys = sorted(files)
    size = -(-len(keys) // parts)  # rounded up
    files = {k: files[k] for k in keys[(part_n - 1) * size : part_n * size]}

json.dump(files, sys.stdout, indent=0)
print()
gone = sum(v is None for v in files.values())
print(f"{len(files) - gone} files, {gone} removed", file=sys.stderr)
