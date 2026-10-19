-- M1 subset of the design schema: captures, blobs, pages and their revisions, and full-text
-- search over title and body. derived, job, tag, link, meta and chunk_vec come with later
-- migrations. Applied in one transaction; the runner then sets PRAGMA user_version = 1.

CREATE TABLE blob (
    sha256      TEXT PRIMARY KEY,
    mime        TEXT NOT NULL,
    size        INTEGER NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE page (
    id          TEXT PRIMARY KEY,              -- ULID
    slug        TEXT NOT NULL UNIQUE,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL DEFAULT '',      -- Markdown
    kind        TEXT NOT NULL DEFAULT 'note' CHECK (kind IN ('note', 'todo', 'consume',
                  'memory', 'reference', 'whiteboard', 'document')),
    kind_fixed  INTEGER NOT NULL DEFAULT 0 CHECK (kind_fixed IN (0, 1)),  -- 1: the user chose it
    fields      TEXT NOT NULL DEFAULT '{}' CHECK (json_type(fields) = 'object'),  -- flat
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    deleted_at  TEXT                           -- set: in the trash
);
CREATE INDEX page_by_kind ON page(kind);
CREATE INDEX page_by_updated ON page(updated_at);

-- Rev 1 is written at creation; every title or body change adds one.
CREATE TABLE page_rev (
    page_id     TEXT NOT NULL REFERENCES page(id) ON DELETE CASCADE,
    rev         INTEGER NOT NULL,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    author      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (page_id, rev)
);

CREATE TABLE capture (
    id          TEXT PRIMARY KEY,              -- ULID minted by the client: the retry key
    kind        TEXT NOT NULL CHECK (kind IN ('photo', 'note', 'url', 'file')),
    text        TEXT,
    url         TEXT,
    source      TEXT NOT NULL,                 -- 'pwa', 'share', 'mcp'
    author      TEXT NOT NULL,
    created_at  TEXT NOT NULL,                 -- on the device
    received_at TEXT NOT NULL,                 -- on the server
    page_id     TEXT NOT NULL REFERENCES page(id) ON DELETE CASCADE
);
CREATE INDEX capture_by_page ON capture(page_id);

CREATE TABLE capture_blob (
    capture_id  TEXT NOT NULL REFERENCES capture(id) ON DELETE CASCADE,
    ord         INTEGER NOT NULL,
    sha256      TEXT NOT NULL REFERENCES blob(sha256),
    filename    TEXT,
    PRIMARY KEY (capture_id, ord)
);

-- The search index, a cache. Chunks are never updated: delete and insert.
CREATE TABLE chunk (
    id          INTEGER PRIMARY KEY,
    page_id     TEXT NOT NULL REFERENCES page(id) ON DELETE CASCADE,
    ord         INTEGER NOT NULL,
    text        TEXT NOT NULL
);
CREATE INDEX chunk_by_page ON chunk(page_id);

CREATE VIRTUAL TABLE chunk_fts USING fts5(
    text, content='chunk', content_rowid='id', tokenize='porter unicode61'
);

CREATE TRIGGER chunk_ai AFTER INSERT ON chunk BEGIN
    INSERT INTO chunk_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER chunk_ad AFTER DELETE ON chunk BEGIN
    INSERT INTO chunk_fts(chunk_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
CREATE TRIGGER chunk_bu BEFORE UPDATE ON chunk BEGIN
    SELECT RAISE(ABORT, 'chunks are immutable: delete and insert');
END;
