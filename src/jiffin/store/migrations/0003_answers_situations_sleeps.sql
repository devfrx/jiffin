-- Version 0.3: the answers stored in English (ADR-0026); the answers per place, which take the
-- place of `silence`, and the alerts asked for with Remind here (ADR-0029); the situations of a
-- revision, the stretches of their values and the outcome `outside_situation` (ADR-0028); and
-- the engine's sleeps (ADR-0027).
--
-- `revision` is referred to by other tables, so it only gains a column. `candidate` and `alert`
-- are rebuilt, since SQLite cannot change a CHECK; no table refers to them, so foreign keys stay
-- on, as in 0002.

-- The terms of the situations, as `store/terms.py` writes them; no revision had any before.
ALTER TABLE revision ADD COLUMN situations TEXT NOT NULL DEFAULT '[]'
    CHECK (json_valid(situations));

CREATE TABLE candidate_0003 (
    evaluation INTEGER NOT NULL REFERENCES evaluation (id) ON DELETE CASCADE,
    revision INTEGER NOT NULL REFERENCES revision (id) ON DELETE CASCADE,
    d REAL NOT NULL,
    from_cache INTEGER NOT NULL CHECK (from_cache IN (0, 1)),
    outcome TEXT NOT NULL CHECK (outcome IN (
        'alert', 'below_threshold', 'outside_time', 'outside_situation', 'silenced', 'snoozed',
        'same_occasion', 'held_back'
    )),
    PRIMARY KEY (evaluation, revision)
) STRICT;

INSERT INTO candidate_0003 (evaluation, revision, d, from_cache, outcome)
SELECT evaluation, revision, d, from_cache, outcome FROM candidate;
DROP TABLE candidate;
ALTER TABLE candidate_0003 RENAME TO candidate;
CREATE INDEX candidate_revision ON candidate (revision);

CREATE TABLE alert_0003 (
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
    answer TEXT CHECK (answer IN ('done', 'useful', 'snooze', 'not_here', 'closed')),
    snooze TEXT CHECK (snooze IN ('next_time', 'quarter_hour', 'hour', 'tomorrow')),
    answered_at INTEGER,
    requested INTEGER NOT NULL CHECK (requested IN (0, 1))
) STRICT;

-- Versions 0.1 and 0.2 stored the answers in Italian, and no alert was asked for before 0.3.
INSERT INTO alert_0003 (
    id, revision, evaluation, context, d, created_at, due_at, shown_at, vanished_at, seen_at,
    answer, snooze, answered_at, requested
)
SELECT
    id, revision, evaluation, context, d, created_at, due_at, shown_at, vanished_at, seen_at,
    CASE answer
        WHEN 'fatto' THEN 'done'
        WHEN 'utile' THEN 'useful'
        WHEN 'rimanda' THEN 'snooze'
        WHEN 'non_qui' THEN 'not_here'
        WHEN 'chiuso' THEN 'closed'
    END,
    snooze, answered_at, 0
FROM alert;
DROP TABLE alert;
ALTER TABLE alert_0003 RENAME TO alert;
CREATE INDEX alert_revision ON alert (revision);
CREATE INDEX alert_evaluation ON alert (evaluation);
CREATE INDEX alert_context ON alert (context);
CREATE INDEX alert_created_at ON alert (created_at);

-- Every answer per place and every withdrawal, kept until the reminder is deleted: the last row
-- of a reminder in a context counts, and the earlier ones serve the replay.
CREATE TABLE context_answer (
    id INTEGER PRIMARY KEY,
    reminder INTEGER NOT NULL REFERENCES reminder (id) ON DELETE CASCADE,
    context INTEGER NOT NULL REFERENCES context (id),
    here TEXT NOT NULL CHECK (here IN ('not_here', 'remind_here', 'withdrawn')),
    d REAL,
    engine_build INTEGER REFERENCES engine_build (id),
    at INTEGER NOT NULL
) STRICT;

CREATE INDEX context_answer_place ON context_answer (reminder, context);
CREATE INDEX context_answer_context ON context_answer (context);
CREATE INDEX context_answer_engine_build ON context_answer (engine_build);

-- Each silence was a Not here: it takes the d, the build and the time of the last alert its
-- reminder had in its context answered Not here, and the rows follow those times. A silence whose
-- alert is gone cannot be older than its reminder.
INSERT INTO context_answer (reminder, context, here, d, engine_build, at)
SELECT
    silence.reminder, silence.context, 'not_here', alert.d, evaluation.engine_build,
    coalesce(alert.answered_at, reminder.created_at)
FROM silence
JOIN reminder ON reminder.id = silence.reminder
LEFT JOIN alert ON alert.id = (
    SELECT a.id FROM alert AS a JOIN revision AS r ON r.id = a.revision
    WHERE r.reminder = silence.reminder AND a.context = silence.context AND a.answer = 'not_here'
    ORDER BY a.answered_at DESC, a.id DESC LIMIT 1
)
LEFT JOIN evaluation ON evaluation.id = alert.evaluation
ORDER BY coalesce(alert.answered_at, reminder.created_at), silence.reminder, silence.context;
DROP TABLE silence;

-- One row per stretch of a value of a situation, once it ended: kept 30 days, like the
-- evaluations. The values are states, never texts: an app's executable, a site, `yes`, `home`.
CREATE TABLE situation (
    kind TEXT NOT NULL CHECK (kind IN (
        'call', 'away', 'power', 'display', 'headphones', 'network', 'playback'
    )),
    value TEXT NOT NULL,
    since INTEGER NOT NULL,
    until INTEGER NOT NULL
) STRICT;

CREATE INDEX situation_until ON situation (until);

-- Each light sleep of the engine, written when it starts and again when it ends: kept 30 days.
CREATE TABLE engine_sleep (
    slept_at INTEGER PRIMARY KEY,
    reason TEXT NOT NULL CHECK (reason IN ('idle', 'nothing_in_front')),
    woken_at INTEGER,
    woken_by TEXT CHECK (woken_by IN ('context', 'statement', 'judgement', 'retry')),
    ready_at INTEGER
) STRICT;
