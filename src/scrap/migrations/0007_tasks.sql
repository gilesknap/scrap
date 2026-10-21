-- Task lists drive a todo: each page's count of task boxes (- [ ] / - [x]), ticked and in
-- all, kept with its text (store.Store._body), so rows and the Todos screen can say "2 of 5"
-- without reading every body. Additive, as 0006: the Python step (store.AFTER[7],
-- add_tasks) adds the columns only if missing, then counts every page's boxes again, so an
-- older scrap still runs with user_version set back to 6 (or 5) and migrating again puts
-- right any count it left behind.
SELECT 1;
