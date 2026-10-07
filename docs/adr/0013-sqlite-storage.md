# ADR-0013: Store data in one SQLite file with the standard sqlite3 module

- **Status:** Accepted; amended by [ADR-0027](0027-light-sleep-of-the-engine.md) (the engine's sleeps), [ADR-0028](0028-read-the-situations-in-core.md) (the situations) and [ADR-0029](0029-learn-from-answers-per-place.md) (the answers per place instead of the silences)
- **Date:** 2026-09-30
- **Deciders:** devfrx
- **Sources:** tickets [#28](https://github.com/devfrx/jiffin/issues/28) (storage), [#15](https://github.com/devfrx/jiffin/issues/15) (what is saved) and [#30](https://github.com/devfrx/jiffin/issues/30) (`context_since`)

## Context

The app keeps reminders with their revisions, evaluations with the judged
reminders, alerts with their answers, "not here" silences, the pair cache and a
few settings, under retention and deletion rules
([ADR-0014](0014-feedback-data-retention.md)). One process writes, through one
connection on the worker thread ([ADR-0012](0012-package-structure-ports.md)).

Facts checked on 2026-09-30:

- SQLite from 3.7.0 to 3.51.2 has the rare "WAL-reset" corruption bug; it needs
  two connections writing or checkpointing at the same time.
- The python.org installers of Python 3.13 ship SQLite 3.50.4; the
  python-build-standalone builds that uv manages ship 3.53.1, and keep getting
  3.13 security fixes after python.org stops publishing installers (the last
  one, 3.13.16, is scheduled for 2026-10-06 by PEP 719).
- Alembic 1.20 requires SQLAlchemy and Mako; yoyo-migrations has had no commit
  since August 2024.

## Decision

**SQLite, through the standard library's `sqlite3`.**

- One file, `%LOCALAPPDATA%\Jiffin\jiffin.db`, with `logs\` and `models\` next
  to it: outside Velopack's install folder, whose packId is `devfrx.Jiffin`, so
  updates and uninstalls never touch the data
  ([ADR-0015](0015-package-pyinstaller-velopack.md)).
- Hand-written SQL in `store`; no ORM.
- Python managed by uv: `python-preference = "only-managed"` and the exact
  version in `.python-version`. A test asserts that `sqlite3.sqlite_version` is
  at least 3.51.3.

**The connection** is opened in this order:

1. `sqlite3.connect(path, autocommit=True, timeout=5)`;
2. `PRAGMA journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON`,
   `secure_delete=ON`, `optimize=0x10002`;
3. the migrations;
4. `conn.autocommit = False`: from here on, PEP 249 transactions.

The order matters: with `autocommit=False` from the start a transaction is
already open, `foreign_keys` stays 0 and the switch to WAL fails (verified with
Python 3.13.7).

- Times are integer UTC milliseconds; `sqlite3`'s default date adapters are
  deprecated since Python 3.12.
- `STRICT` tables, foreign keys always declared, indexes on foreign-key columns
  and on the timestamps the cleanup uses.

**Schema of the first version:**

| Table | Holds | Keys and links | Kept |
|---|---|---|---|
| `reminder` | a reminder: created, completed, snoozed until | `id` | until the user deletes it |
| `revision` | each version of a reminder: "Quando", "Ricordami di", the English statement and the engine build that wrote it (empty until the engine answers) | `id`; `reminder`, cascade; number unique per reminder | with the reminder |
| `context` | a normalized context: `app`, `title`, `address` | `id`; the three values unique together | while a row uses it |
| `engine_build` | protocol, engine version, llama.cpp build, model sha256, prompt versions | `id`; unique on the whole set | always; not personal data |
| `evaluation` | an evaluation: when, context, `context_since` (when the context came to the foreground), outcome (`ok` or `error`), threshold, engine build | `id`; `context`, `engine_build` | 30 days |
| `candidate` | a reminder judged in an evaluation: `d`, whether it came from the cache, whether it raised an alert or why not | (`evaluation`, `revision`), both cascade | with the evaluation |
| `alert` | an alert: when, context, `d`, answer (`fatto`, `utile`, `rimanda`, `non_qui`) and when | `id`; `revision`, cascade; `evaluation`, set to null when the evaluation expires | answered: while the reminder exists; unanswered: 30 days |
| `silence` | a "not here" | (`reminder`, `context`); `reminder`, cascade | while the reminder exists |
| `judgement` | the cache: the `d` of a revision in a context, with an engine build | (`context`, `revision`, `engine_build`); `revision`, cascade; last-used time | 30 days after last use |
| `setting` | settings, values in JSON | `key` | always |

- **The cache key** is context, revision and engine build: exactly the text the
  model sees ([ADR-0004](0004-context-identity.md)). A written revision never
  changes, and a different engine gives different numbers. The cascade on the
  revision makes deletion complete.
- **The threshold is not a setting.** It depends on the model and on the
  prompts ([ADR-0008](0008-rewrite-conditions-english-statements.md)), so it is
  a constant in the code next to their versions, and every evaluation records
  it. On the acceptance day the harness recomputes the alerts at any threshold
  from the stored `d` values, and the chosen value enters the next build.
- **Settings in the first version:** the material of the alert and of the tray
  list; defaults live in the code.
- **Private windows** never become rows.
- **Logs** contain no titles, addresses or reminder texts: only ids and numbers.

**Migrations.**

- Hand-written and numbered (`store/migrations/0001_init.sql`, …), applied in
  order with `PRAGMA user_version`. Each migration and its version bump share
  one transaction: all or nothing.
- Forward only. When the file carries a higher version than the app knows,
  after a downgrade, the app does not open it and says so.
- Before migrating, a copy through the backup API. After migrating,
  `integrity_check` and `foreign_key_check`: if they pass, the copy is deleted
  (it would keep data deleted later); if not, the copy is restored and the error
  reported.
- Changes `ALTER TABLE` cannot make use the 12-step rebuild documented by
  sqlite.org, with foreign keys off and `PRAGMA foreign_key_check` at the end.
- Tests: from an empty file to the latest version, and from every earlier
  version with synthetic data.

**Cleanup**, at startup and then daily, on the worker thread, in one
transaction:

1. evaluations older than 30 days (their candidates cascade);
2. unanswered alerts older than 30 days;
3. cache entries unused for 30 days;
4. contexts no row uses any more.

Then `PRAGMA optimize` and a `wal_checkpoint(TRUNCATE)`.

**Deleting a reminder** cascades to its revisions, candidates, alerts, cache
entries and silences; then evaluations left without candidates and orphan
contexts are deleted, followed by a `TRUNCATE` checkpoint. With `secure_delete`,
deleted content becomes zeros in the file, and the checkpoint keeps old pages
out of the WAL.

## Consequences

**Positive**

- The database itself enforces the retention and deletion rules.
- Standard library only; the migration runner is a few dozen lines.

**Negative (accepted)**

- Hand-written SQL and migrations to maintain.
- A single connection: the harness reads a copy made through the backup API,
  or opens the file read-only, never as a second writer.

**Follow-up**

- An ER diagram in Mermaid in `docs/design/` with the first build.
- `silence` has no revision column: when a reminder's text changes, the code
  deletes its silences, as [ADR-0004](0004-context-identity.md) requires.
