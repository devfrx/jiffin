-- Each stretch with nothing in front for the reminders, written when it starts and again when it
-- ends: kept 30 days, for the harness to check that the engine slept (ADR-0031). `startup` marks
-- the one the app starts with.
CREATE TABLE nothing_in_front (
    since INTEGER PRIMARY KEY,
    until INTEGER,
    startup INTEGER NOT NULL CHECK (startup IN (0, 1))
) STRICT;
