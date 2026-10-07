# ADR-0026: Write the code in English, and keep the app's Italian in language files

- **Status:** Accepted
- **Date:** 2026-10-07
- **Deciders:** devfrx
- **Sources:** the [0.3 decision map](https://github.com/devfrx/jiffin/issues/119): tickets [#130](https://github.com/devfrx/jiffin/issues/130) (names in the code), [#131](https://github.com/devfrx/jiffin/issues/131) (research) and [#132](https://github.com/devfrx/jiffin/issues/132) (where the Italian lives); amends [ADR-0002](0002-apache-license-english-repository.md), [ADR-0012](0012-package-structure-ports.md), [ADR-0020](0020-read-the-time-in-core.md) and [ADR-0021](0021-one-alert-per-unit.md)

## Context

[ADR-0002](0002-apache-license-english-repository.md) writes the repository
in English and the interface in Italian, "with all strings in one place". In
0.2 the Italian sits in the code in four forms (verified at `d38c7ff`):

- the names of the commands, in comments, docs and stored values: the answers
  in `alert.answer` are `fatto`, `utile`, `rimanda`, `non_qui` and `chiuso`,
  and "Rimanda" names the command in about 40 lines of `src` and 54 of `docs`;
- the texts of the interface: `Texts.qml`, `ui/words.py` (14 functions that
  compose sentences from pieces), the message of `app/root.py`, the harness's
  pages;
- the words the time grammar knows: about 200 entries in `core/grammar.py`,
  some inside regexes, and about 30 in `core/meanings.py`;
- the phrases of the tests and fixtures.

The owner asked for the code all in English, not for an app in English
([#119](https://github.com/devfrx/jiffin/issues/119)): the app stays Italian,
and an English app is out of scope. `ui/words.py` and the harness must stay
without Qt: the harness imports `ui/words.py` by name
([ADR-0021](0021-one-alert-per-unit.md)).

Ways to keep the texts out of the code
([#131](https://github.com/devfrx/jiffin/issues/131),
[#132](https://github.com/devfrx/jiffin/issues/132)):

- **Qt's translation system:** works in QML; in PySide it has three traps; it
  wants an English source text for every string, which the app never shows;
  and it cannot reach `ui/words.py` and the harness, so the app would end with
  two systems, against "one place".
- **gettext:** no way into QML without a bridge and an extractor of our own.
- **Fluent and MessageFormat 2:** immature in Python (`fluent.runtime` stopped
  in 2023, `messageformat2` is at 0.1.1).
- **Babel:** about 9.7 MB for a plural rule that, for Italian, is one line.
- **A catalog of our own:** one format for QML, Python and the harness. JSON
  has no comments, and today's texts carry notes for whoever changes them;
  YAML is one more dependency and guesses the types of values; TOML is read by
  the standard library's `tomllib`.
- **A Python module generated from the catalog**, as dateparser does: `core`
  would stay without I/O, at the price of a generator and a generated copy,
  whose staleness fails silently.
- **The lexicon passed into `core` from outside:** pure, but carried through
  every constructor, from the interface to the harness, for the same result.

## Decision

**In the repository, Italian lives in three places only:**

1. **the language files**, in `src/jiffin/lang/it/`: everything the app shows
   and understands;
2. **between quotes, as an example of what the user writes**: the phrases of
   the tests, and examples in comments and docs ("quando apro Figma dopo le
   23");
3. **history**: the migrations already applied (0001 and 0002), the accepted
   ADRs and the past entries of the CHANGELOG, which are not rewritten.

Everything else is English: identifiers, comments, docs, messages for
developers, stored values.

**The names in the code** ([#130](https://github.com/devfrx/jiffin/issues/130),
confirmed by the owner) are the ones the code already has; the screen does not
change.

| On screen (unchanged) | In the code |
|---|---|
| Fatto | `done`, stored `done` (was `fatto`) |
| Rimanda: Alla prossima volta, Tra 15 minuti, Tra un'ora, Domani | `snooze`, stored `snooze` (was `rimanda`): `next_time`, `quarter_hour`, `hour`, `tomorrow` |
| Non qui | `not_here`, stored `not_here` (was `non_qui`) |
| the X of the alert | `close`, stored `closed` (was `chiuso`) |
| Utile (0.1 only) | `useful`, stored `useful` (was `utile`) |
| Quando, Ricordami di | `condition`, `action` |
| Ogni volta | `perennial` |
| the tray list, Non visti, Attivi | `TrayList`, `unseen`, `active` |
| Nuovo, Modifica, Completa, Elimina | `new`, `edit`, `complete`, `delete` |
| Sospendi, Riprendi | `pause`, `resume` |
| the return pause; the occasion (not on screen) | `return_pause`; `occasion`, and `unit` for the occasion or the instance of a time |

- **One word for each thing, in each place's form:** `not_here` in Python and
  in stored values, `notHere` in QML, `NOT_HERE` for enum members. In comments
  and docs the same word with spaces: a command capitalised like a button
  (Done, Snooze, Next time, Quarter hour, Hour, Tomorrow, Not here, Close,
  New, Edit, Complete, Delete, Pause, Resume), a part in lower case (the
  condition, the action, a perennial reminder, the tray list, unseen alerts,
  active reminders, the return pause, the occasion).
- **`perennial`, not `recurring`:** `recurring` already names the time words
  that tick "Ogni volta" by themselves ([ADR-0020](0020-read-the-time-in-core.md)).

**The texts: a catalog of our own, in TOML.** `src/jiffin/lang/it/texts.toml`
has one key per text, named after the code's names: `alert.done = "Fatto"`,
`snooze.next_time = "Alla prossima volta"`.

- **`jiffin.lang` reads it**, a new part without Qt that imports nothing from
  `jiffin`, with `tomllib`. It reads each file once, at import, and validates
  it into typed dataclasses: a missing key stops the tests and the start.
- **QML reaches it through a Python singleton of `ui`**, as it reaches `Look`.
  `Texts.qml` stays as a typed facade, so qmllint still checks every use; each
  of its properties takes its key, and it holds no Italian.
- **Sentences composed from pieces become whole sentences** in the catalog,
  with named placeholders (`{minutes}`); plurals as `{ one = "…", other = "…" }`,
  chosen by the Italian rule (one only for n = 1), the one Qt uses; and cases
  of agreement, such as the feminine Sunday, as separate keys the code
  chooses.
- **Numbers, sizes and lists** ("2,4 GB", "Chrome e Brave") are written by
  `jiffin.lang` in Python, with separators and conjunction in the language
  file: QML formats nothing on its own, and the app and the harness write
  alike.
- **The message of `app/root.py`** for an app that cannot start comes from the
  catalog; only when the catalog itself cannot be read does a technical
  fallback in English, in the code, take its place.

**The words of the time: `src/jiffin/lang/it/time.toml`, the rules stay
code.** Its `read` section holds the lexicon of `core/grammar.py` and
`core/meanings.py`, the prepositions now inside the regexes included; its
`write` section the words and fragments of `ui/words.py`. The rules (regexes,
handlers, agreement, elision) stay code for the Italian language, with English
identifiers, and take their words from the lexicon, as chrono does. `Part`
becomes an English enum, and "mattina" or "sera" go to the lexicon. `core`
imports `jiffin.lang`.

**Stored values: English, with migration 0003**
([ADR-0013](0013-sqlite-storage.md)). `Answer` stores `done`, `useful`,
`snooze`, `not_here` and `closed`. A new CHECK on `alert.answer` needs the
12-step rebuild of the table, which translates the old values with a `CASE`,
as 0002 did; `store` passes the enum's value, not the literal `'non_qui'`.
Migrations 0001 and 0002 are never touched, and older copies stay replayable,
since the harness migrates a copy before reading it. The harness's labels do
not change: they are keyed by text, with true or false.

**The harness's texts: `src/jiffin/lang/it/harness.toml`**: the sentences of
its three Jinja pages, `_WHY` of `report.py` and the states written by
`statements.py`; the templates become English markup with keys. The file is
left out of the app's package, as `harness/**` is
([ADR-0017](0017-evaluation-harness-subpackage.md)). The summary of numbers
only stays in English, since it goes into issues.

**The phrases of the tests stay in the tests**, as literals: they are data in
the app's language, and read best next to the expected result. Moving them to
data files, as Duckling's and Recognizers-Text's corpora do, would pay off
only with more languages. Their names, docstrings and comments are English;
tests that find a button by its text take the text from the catalog. The same
holds for the examples of `ui/__main__.py`, a developer's tool, whose printed
messages become English.

**Command names in comments, docs and ADRs are the English ones.** Code,
comments, `docs/design/` and the README are rewritten, since they describe the
present. Accepted ADRs and past CHANGELOG entries stay as they are; new ADRs
use the English names, and quote the Italian of the screen where its exact
words were decided. Mockups stay pictures of the Italian screen. No glossary:
the catalog itself says that `alert.snooze` is "Rimanda".

**How it stays so.**

- **A pre-commit hook**, a local script with the standard library only; CI
  runs pre-commit before pytest, so the same check runs there. It recognises
  Italian from accented letters and from the words of the language files
  themselves, minus a short list of words that are English too ("file",
  "come", "menu"). It fails on Italian outside `lang/`: in comments and
  docstrings outside quotes; in the literals of `src`, except the examples of
  `ui/__main__.py`; in `docs/design/` and the README outside quotes; in the
  migrations from 0003 on. It does not look at the tests' literals, the ADRs,
  the CHANGELOG and the mockups.
- **A unit test on the catalog:** every key the code uses, in QML and Python,
  exists, and every key of the files is used; the placeholders of each text
  are those the code passes; each plural has its forms.

**What this amends.**

- [ADR-0002](0002-apache-license-english-repository.md): where the Italian
  lives, and the check. The interface's "one place" is the language files.
- [ADR-0012](0012-package-structure-ports.md): a ninth part, `lang`, which
  imports nothing from `jiffin` and which every part may import, `core`
  included. `core`'s "no I/O" does not cover the package's language data, read
  once at import.
- [ADR-0020](0020-read-the-time-in-core.md): the lexicon is data, the rules
  are code, and `Part` is English.
- [ADR-0021](0021-one-alert-per-unit.md): the stored values of the answers.

## Consequences

**Positive**

- One place for each kind of Italian, kept so by a check in pre-commit and CI.
- `core`, `ui/words.py`, QML and the harness share one catalog, without Qt.
- A text of the screen changes in one file, not in QML or Python.

**Negative (accepted)**

- A small catalog format and its loader to maintain, instead of Qt's.
- `core` reads files at import: it is no longer strictly without I/O.
- The check recognises Italian by its letters and words: it can miss a word
  that is in no language file, and a word shared with English needs its list.
- Accepted ADRs and past CHANGELOG entries keep the Italian names: a reader
  meets both.

**Follow-up**

- Built before the rest of 0.3, so that the new code is born in English, and
  without visible change: the same texts on every screen and on the owner's
  list of phrases, the same meanings on `test_meanings.py` and
  `test_words.py`, the same `read` before and after on the case files and the
  generated counts.
- Migration 0003 names the old answers only to translate them: the check lets
  that through as history.
- When this is built, `docs/design/` follows: `architecture.md` (the part
  `lang`), `time.md`, `creation.md` and every page that names a command.
