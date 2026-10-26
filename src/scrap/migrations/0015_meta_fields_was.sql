-- Changing a page's fields over MCP (edit_meta's fields, #309) is a metadata revision: the
-- values it set are page_meta_rev.fields_added (as a kind's defaults are), and the values
-- they had before, or the fields it took off, the new column fields_was (a JSON object).
-- The Python step (store.AFTER[15], add_fields_was) adds the column only if missing, so
-- migrating again is harmless; an older scrap never reads it. Existing rows get '{}'.
SELECT 1;
