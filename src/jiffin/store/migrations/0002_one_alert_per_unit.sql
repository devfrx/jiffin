-- Version 0.2 (ADR-0020, ADR-0021): the time and "Ogni volta" on the revision, when a context
-- left and the return pause on the evaluation, the new outcomes, and alerts that may have no
-- judgement, with when they were due and which Rimanda answered them.
--
-- `revision` is referred to by other tables, so it only gains columns. `candidate` and `alert`
-- are rebuilt, since SQLite cannot change a CHECK or drop a NOT NULL; no table refers to them,
-- so foreign keys stay on.

-- Without a time the remainder is the condition, and version 0.1 had no times.
ALTER TABLE revision ADD COLUMN remainder TEXT NOT NULL DEFAULT '';
UPDATE revision SET remainder = condition;
ALTER TABLE revision ADD COLUMN schedule TEXT CHECK (json_valid(schedule));
ALTER TABLE revision ADD COLUMN written_at INTEGER;
ALTER TABLE revision ADD COLUMN perennial INTEGER NOT NULL DEFAULT 0 CHECK (perennial IN (0, 1));
ALTER TABLE revision ADD COLUMN created_at INTEGER;
-- Version 0.1 knows when a revision was made only for the first one, made with its reminder.
UPDATE revision SET created_at = (SELECT created_at FROM reminder WHERE id = revision.reminder)
WHERE number = 1;

ALTER TABLE evaluation ADD COLUMN context_until INTEGER;
ALTER TABLE evaluation ADD COLUMN return_pause INTEGER;

CREATE TABLE candidate_0002 (
    evaluation INTEGER NOT NULL REFERENCES evaluation (id) ON DELETE CASCADE,
    revision INTEGER NOT NULL REFERENCES revision (id) ON DELETE CASCADE,
    d REAL NOT NULL,
    from_cache INTEGER NOT NULL CHECK (from_cache IN (0, 1)),
    outcome TEXT NOT NULL CHECK (outcome IN (
        'alert', 'below_threshold', 'outside_time', 'silenced', 'snoozed', 'same_occasion',
        'held_back'
    )),
    PRIMARY KEY (evaluation, revision)
) STRICT;

INSERT INTO candidate_0002 (evaluation, revision, d, from_cache, outcome)
SELECT evaluation, revision, d, from_cache, outcome FROM candidate;
DROP TABLE candidate;
ALTER TABLE candidate_0002 RENAME TO candidate;
CREATE INDEX candidate_revision ON candidate (revision);

CREATE TABLE alert_0002 (
    id INTEGER PRIMARY KEY,
    revision INTEGER NOT NULL REFERENCES revision (id) ON DELETE CASCADE,
    evaluation INTEGER REFERENCES evaluation (id) ON DELETE SET NULL,
    context INTEGER NOT NULL REFERENCES context (id),
    d REAL,
    created_at INTEGER NOT NULL,
    due_at INTEGER NOT NULL,
    shown_at INTEGER,
    vanished_at INTEGER,
    seen_at INTEGER,
    answer TEXT CHECK (answer IN ('fatto', 'utile', 'rimanda', 'non_qui', 'chiuso')),
    snooze TEXT CHECK (snooze IN ('next_time', 'quarter_hour', 'hour', 'tomorrow')),
    answered_at INTEGER
) STRICT;

-- In version 0.1 an alert was due when its context came to the foreground; when its evaluation
-- has expired, when it was made is the best left.
INSERT INTO alert_0002 (
    id, revision, evaluation, context, d, created_at, due_at, shown_at, vanished_at, seen_at,
    answer, answered_at
)
SELECT
    alert.id, alert.revision, alert.evaluation, alert.context, alert.d, alert.created_at,
    ifnull(evaluation.context_since, alert.created_at), alert.shown_at, alert.vanished_at,
    alert.seen_at, alert.answer, alert.answered_at
FROM alert LEFT JOIN evaluation ON evaluation.id = alert.evaluation;
DROP TABLE alert;
ALTER TABLE alert_0002 RENAME TO alert;
CREATE INDEX alert_revision ON alert (revision);
CREATE INDEX alert_evaluation ON alert (evaluation);
CREATE INDEX alert_context ON alert (context);
CREATE INDEX alert_created_at ON alert (created_at);
