-- The first schema (ADR-0013). Times are UTC milliseconds; what is kept, and for how long,
-- follows ADR-0014.

CREATE TABLE reminder (
    id INTEGER PRIMARY KEY,
    created_at INTEGER NOT NULL,
    completed_at INTEGER,
    snoozed_until INTEGER
) STRICT;

CREATE TABLE engine_build (
    id INTEGER PRIMARY KEY,
    protocol INTEGER NOT NULL,
    engine_version TEXT NOT NULL,
    llama_cpp_build TEXT NOT NULL,
    model_sha256 TEXT NOT NULL,
    judge_prompt INTEGER NOT NULL,
    rewrite_prompt INTEGER NOT NULL,
    UNIQUE (
        protocol, engine_version, llama_cpp_build, model_sha256, judge_prompt, rewrite_prompt
    )
) STRICT;

CREATE TABLE revision (
    id INTEGER PRIMARY KEY,
    reminder INTEGER NOT NULL REFERENCES reminder (id) ON DELETE CASCADE,
    number INTEGER NOT NULL,
    condition TEXT NOT NULL,
    action TEXT NOT NULL,
    statement TEXT,
    statement_build INTEGER REFERENCES engine_build (id),
    UNIQUE (reminder, number)
) STRICT;

CREATE INDEX revision_statement_build ON revision (statement_build);

CREATE TABLE context (
    id INTEGER PRIMARY KEY,
    app TEXT NOT NULL,
    title TEXT NOT NULL,
    address TEXT
) STRICT;

-- One row per context: a missing address counts as one value.
CREATE UNIQUE INDEX context_identity ON context (app, title, ifnull(address, ''));

CREATE TABLE evaluation (
    id INTEGER PRIMARY KEY,
    at INTEGER NOT NULL,
    context INTEGER NOT NULL REFERENCES context (id),
    context_since INTEGER NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('ok', 'error')),
    threshold REAL NOT NULL,
    engine_build INTEGER REFERENCES engine_build (id)
) STRICT;

CREATE INDEX evaluation_at ON evaluation (at);
CREATE INDEX evaluation_context ON evaluation (context);
CREATE INDEX evaluation_engine_build ON evaluation (engine_build);

CREATE TABLE candidate (
    evaluation INTEGER NOT NULL REFERENCES evaluation (id) ON DELETE CASCADE,
    revision INTEGER NOT NULL REFERENCES revision (id) ON DELETE CASCADE,
    d REAL NOT NULL,
    from_cache INTEGER NOT NULL CHECK (from_cache IN (0, 1)),
    outcome TEXT NOT NULL
        CHECK (outcome IN ('alert', 'below_threshold', 'silenced', 'snoozed', 'held_back')),
    PRIMARY KEY (evaluation, revision)
) STRICT;

CREATE INDEX candidate_revision ON candidate (revision);

CREATE TABLE alert (
    id INTEGER PRIMARY KEY,
    revision INTEGER NOT NULL REFERENCES revision (id) ON DELETE CASCADE,
    evaluation INTEGER REFERENCES evaluation (id) ON DELETE SET NULL,
    context INTEGER NOT NULL REFERENCES context (id),
    d REAL NOT NULL,
    created_at INTEGER NOT NULL,
    shown_at INTEGER,
    vanished_at INTEGER,
    seen_at INTEGER,
    answer TEXT CHECK (answer IN ('fatto', 'utile', 'rimanda', 'non_qui')),
    answered_at INTEGER
) STRICT;

CREATE INDEX alert_revision ON alert (revision);
CREATE INDEX alert_evaluation ON alert (evaluation);
CREATE INDEX alert_context ON alert (context);
CREATE INDEX alert_created_at ON alert (created_at);

CREATE TABLE silence (
    reminder INTEGER NOT NULL REFERENCES reminder (id) ON DELETE CASCADE,
    context INTEGER NOT NULL REFERENCES context (id),
    PRIMARY KEY (reminder, context)
) STRICT;

CREATE INDEX silence_context ON silence (context);

CREATE TABLE judgement (
    context INTEGER NOT NULL REFERENCES context (id),
    revision INTEGER NOT NULL REFERENCES revision (id) ON DELETE CASCADE,
    engine_build INTEGER NOT NULL REFERENCES engine_build (id),
    d REAL NOT NULL,
    last_used INTEGER NOT NULL,
    PRIMARY KEY (context, revision, engine_build)
) STRICT;

CREATE INDEX judgement_revision ON judgement (revision);
CREATE INDEX judgement_engine_build ON judgement (engine_build);
CREATE INDEX judgement_last_used ON judgement (last_used);

CREATE TABLE setting (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL CHECK (json_valid(value))
) STRICT;
