-- M3 search (#84): a page's own chunk indexes its title, tags and summary as columns of their
-- own, so ranking can weight them (bm25 column weights) and the body column no longer repeats
-- the title. Derived chunks (what Claude read from a photo) fill only text. The runner then
-- re-indexes every page's own chunk in Python, in this same transaction (store.AFTER[3]), and
-- sets PRAGMA user_version = 3.

DROP TRIGGER chunk_ai;
DROP TRIGGER chunk_ad;
DROP TABLE chunk_fts;

ALTER TABLE chunk ADD COLUMN title TEXT NOT NULL DEFAULT '';
ALTER TABLE chunk ADD COLUMN tags TEXT NOT NULL DEFAULT '';     -- the page's tags, space-separated
ALTER TABLE chunk ADD COLUMN summary TEXT NOT NULL DEFAULT '';  -- its summary field, if any

CREATE VIRTUAL TABLE chunk_fts USING fts5(
    title, tags, summary, text, content='chunk', content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TRIGGER chunk_ai AFTER INSERT ON chunk BEGIN
    INSERT INTO chunk_fts(rowid, title, tags, summary, text)
    VALUES (new.id, new.title, new.tags, new.summary, new.text);
END;
CREATE TRIGGER chunk_ad AFTER DELETE ON chunk BEGIN
    INSERT INTO chunk_fts(chunk_fts, rowid, title, tags, summary, text)
    VALUES ('delete', old.id, old.title, old.tags, old.summary, old.text);
END;

-- Every chunk again, the derived ones as they are (the page's own are re-made after this).
INSERT INTO chunk_fts(chunk_fts) VALUES ('rebuild');
