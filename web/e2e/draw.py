"""E2E fixture: a synthetic whiteboard photo, "read" by a fake Claude, in a data folder.

Run as `uv run python web/e2e/draw.py DATA_DIR` while scrap serves DATA_DIR. It
saves a capture of a drawn (not photographed) whiteboard, runs its ingest job with a
canned answer instead of calling Claude, and prints {"slug", "capture_id", "sha256"}
as JSON. With a second argument, `failed`, `pause` or `resume`, it sets up that
ingest state instead. Nothing in it is real or private.
"""

import io
import json
import sys

from PIL import Image, ImageDraw

from scrap import claude, ingest
from scrap.store import Store, new_ulid, transaction

W, H = 1600, 1200
BOXES = [  # (id, x, y, w, h, label)
    ("phone", 120, 180, 320, 160, "Phone"),
    ("queue", 640, 180, 320, 160, "Queue"),
    ("model", 1160, 180, 320, 160, "Model"),
]
BOARD = {
    "kind": "whiteboard",
    "title": "Capture pipeline sketch",
    "tags": ["sketch", "pipeline"],
    "description": "A whiteboard sketch of a capture pipeline: phone, queue and model, "
    "with a note on retries.",
    "text": "Phone\nQueue\nModel\nretry with backoff\nkeep originals (?)",
    "elements": [
        *[
            {"type": "rectangle", "id": i, "x": x, "y": y, "width": w, "height": h,
             "label": label, "labelFontSize": 44, "strokeColor": "#1e1e1e"}
            for i, x, y, w, h, label in BOXES
        ],
        {"type": "arrow", "id": "a1", "x": 440, "y": 260, "points": [0, 0, 200, 0],
         "start": "phone", "end": "queue"},
        {"type": "arrow", "id": "a2", "x": 960, "y": 260, "points": [0, 0, 200, 0],
         "start": "queue", "end": "model"},
        {"type": "text", "id": "note", "x": 640, "y": 620, "text": "retry with backoff",
         "fontSize": 48, "strokeColor": "#1971c2"},
        {"type": "arrow", "id": "a3", "x": 800, "y": 340, "points": [0, 0, 0, 270],
         "start": "queue", "end": "note", "strokeColor": "#1971c2"},
        {"type": "ellipse", "id": "keep", "x": 140, "y": 820, "width": 520,
         "height": 200, "label": "keep originals (?)", "labelFontSize": 40,
         "strokeColor": "#e03131"},
    ],
}  # fmt: skip


def photo() -> bytes:
    """The board, drawn: dark marker on an off-white board, roughly where Claude would
    have put its elements."""
    img = Image.new("RGB", (W, H), (244, 243, 238))
    d = ImageDraw.Draw(img)
    for _, x, y, w, h, _ in BOXES:
        d.rectangle((x, y, x + w, y + h), outline=(30, 30, 30), width=8)
    for x0 in (440, 960):
        d.line((x0, 260, x0 + 190, 260), fill=(30, 30, 30), width=8)
    d.line((800, 340, 800, 600), fill=(25, 113, 194), width=8)
    d.ellipse((140, 820, 660, 1020), outline=(224, 49, 49), width=8)
    d.rectangle((640, 620, 1100, 680), fill=(210, 225, 240))  # where the note is
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def fake(model, system, messages, schema, blob):
    content = [{"type": "text", "text": json.dumps(BOARD)}]
    usage = {"input_tokens": 1, "output_tokens": 1}
    return claude.Completion(BOARD, content, usage, model, "end_turn")


def state(data_dir: str, how: str) -> None:
    """The ingest states the PWA shows: a photo whose job failed ("failed"), or the
    queue paused for a spend limit ("pause") and running again ("resume")."""
    store = Store(data_dir)
    with store.connect() as conn, transaction(conn):
        if how == "pause":
            conn.execute(
                "UPDATE queue_state SET paused_until = ?, reason = 'credit'",
                (ingest.FAR,),
            )
        elif how == "resume":
            ingest.resume(conn, "2000-01-01T00:00:00.000Z")
    if how != "failed":
        return
    sha, size = store.put_blob(io.BytesIO(photo()))
    c = store.prepare({"id": new_ulid(), "text": "A board that failed"}, ["image/png"])
    ref = store.capture(c, [(sha, "image/png", size, "failed.png")], "e2e")[0]
    with store.connect() as conn, transaction(conn):
        conn.execute(
            "UPDATE job SET state = 'dead', failures = 3,"
            " last_error = 'image: cannot identify image file' WHERE capture_id = ?",
            (ref["capture_id"],),
        )
    print(json.dumps({**ref, "sha256": sha}))


def main(data_dir: str) -> None:
    store = Store(data_dir)
    sha, size = store.put_blob(io.BytesIO(photo()))
    c = store.prepare({"id": new_ulid()}, ["image/png"])
    ref = store.capture(c, [(sha, "image/png", size, "whiteboard.png")], "e2e")[0]
    with store.connect() as conn, transaction(conn):  # claim just this capture's job
        job = conn.execute(
            "UPDATE job SET state = 'running' WHERE capture_id = ? AND state = 'queued'"
            " RETURNING id, capture_id, source_sha256, failures, options",
            (ref["capture_id"],),
        ).fetchone()
    ingest.Worker(store, fake).process(job)
    print(json.dumps({**ref, "sha256": sha}))


if __name__ == "__main__":
    if len(sys.argv) > 2:
        state(sys.argv[1], sys.argv[2])
    else:
        main(sys.argv[1])
