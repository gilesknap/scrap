-- The owner's guidance for Claude's next reading of one image (#538): a note per
-- (capture, image), as writeup_guidance is per page. The image's Regenerate sends it
-- with the image; it never steers a write-up, and is never published.
CREATE TABLE image_guidance (
    capture_id    TEXT NOT NULL REFERENCES capture(id) ON DELETE CASCADE,
    source_sha256 TEXT NOT NULL,
    text          TEXT NOT NULL,
    author        TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (capture_id, source_sha256)
);
