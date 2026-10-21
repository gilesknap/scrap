-- Snooze (#104): a todo can be hidden from Now (and from the Todos tab's count) until a
-- day, snoozed_until (YYYY-MM-DD, as due: no time or time zone). Additive only: the column
-- is added by the Python step (store.AFTER[6], add_snooze) only if it is not there yet, so
-- an older scrap still runs on this database with PRAGMA user_version set back to 5 (it
-- names its columns and never sees this one), and migrating again later is harmless.
SELECT 1;
