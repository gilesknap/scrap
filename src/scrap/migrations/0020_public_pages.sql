-- Public pages (ADR 43, #497): a page the owner made public, and the flag's changes as
-- part of each metadata revision (revert undoes them). Only the flag is stored: what
-- was published, and when, is the kept copy under cache/publish (scrap.publish).
ALTER TABLE page ADD COLUMN public INTEGER NOT NULL DEFAULT 0 CHECK (public IN (0, 1));
CREATE INDEX page_public ON page(id) WHERE public = 1;

ALTER TABLE page_meta_rev ADD COLUMN public_before INTEGER NOT NULL DEFAULT 0
    CHECK (public_before IN (0, 1));
ALTER TABLE page_meta_rev ADD COLUMN public_after INTEGER NOT NULL DEFAULT 0
    CHECK (public_after IN (0, 1));
