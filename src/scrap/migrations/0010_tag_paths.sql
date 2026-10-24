-- Tags with empty path segments (/lead, trail/, a//b) are normalised (#87): the runner's
-- Python step (store.AFTER[10]) rewrites them and re-indexes only the pages concerned.
SELECT 1;
