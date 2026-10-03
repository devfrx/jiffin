# Reading the time

How Jiffin reads the time of a condition: "quando apro Claude dopo le 23",
"alle 15", "il primo lunedì del mese"
([ADR-0020](../adr/0020-read-the-time-in-core.md)). The code is in `core`,
pure and without dependencies: `grammar.py` finds the time words and labels
them, `meanings.py` turns the labels into a `Schedule` with every decided
meaning and has `read`, the only way in, and `schedule.py` holds the
`Schedule` and its calendar.

## The stages

```mermaid
flowchart LR
    IN["condition, written_at"] --> MASK["names masked"]
    MASK --> PAT["patterns, in order"]
    PAT --> LEFT{"time words<br/>left over?"}
    LEFT -- "yes" --> UNCLEAR["not understood"]
    LEFT -- "no" --> AGREE{"the labels<br/>agree?"}
    AGREE -- "no" --> UNCLEAR
    AGREE -- "yes" --> MEAN["a Schedule in real dates"]
    MEAN -- "a date that does not exist" --> UNCLEAR
    MEAN --> OUT["the remainder; past or not"]
```

1. **Names masked.** Names are not time: quoted names, words with a digit or
   a dot inside ("report-9.xlsx"), capitalized words after the first
   ("Corriere della Sera", "zia Domenica"), the number after a name
   ("Windows 11"), a number that counts something ("alle 20 pagine", "le 8
   ore di lavoro"), and a time that names a thing ("il treno delle 7:40").
   The masked text keeps its length, so the offsets of a match are those of
   the condition.
2. **Patterns.** A closed list of forms, tried in order; a match may not
   overlap an earlier one. A match gives labels: what the words say, not yet
   what they mean ("lunedì" is the next Monday, "il lunedì" every Monday).
3. **Left over.** Time words outside the matches ("verso sera", "a dicembre",
   "il 15" without its month), or a word beside a match that changes it
   ("prima di lunedì", "il weekend prossimo"), make the time not understood:
   it is never guessed.
4. **Agree.** One label of each kind: days, hours, a period, a frequency. Two
   of a kind, or kinds that do not go together (a date and a period, "tra 2
   ore" and anything else), make the time not understood.
5. **A Schedule in real dates**, counted from `written_at`: "domani", "tra 2
   ore", "fino a domenica" and the start of a frequency are dates from there
   on. A date that does not exist ("il 31 aprile") makes the time not
   understood.

## What `read` returns

| Field | What it holds |
|---|---|
| `schedule` | The time, in real dates; none without a time, or with one not understood |
| `remainder` | What the engine rewrites: the condition without its time words and without what they leave hanging, that is connectors, commas, empty brackets and a preposition that led into the time ("il report di domani"). Without a time, or with one not understood, the condition byte for byte, so its statement stays as in 0.1 |
| `unclear` | Where the words not understood are, as phrases, for the line under "Quando" to name them |
| `past` | The time has no instance left when written: Salva turns off |
| `recurring` | Words that tick "Ogni volta" by themselves: "ogni…", "tutti i…", "un lunedì sì e uno no", a recurrence of the month or of the year |

`written_at` is the local time as the user's clock shows it: a zone, if it
has one, is ignored, and so are the seconds.

## The Schedule

| Part | Kinds | Examples |
|---|---|---|
| `days` | `Weekdays` (all seven: every day), `OnDate`, `EveryNWeeks`, `MonthWeekday`, `MonthDay`, `YearDay` | "il lunedì", "domani", "un lunedì sì e uno no", "il primo lunedì del mese", "a fine mese", "il 12 marzo di ogni anno" |
| `hours` | none (the whole day), `Slot`, `Moment` | "la sera", "dopo le 23", "alle 15" |
| `period` | `Period`: Jiffin days, both ends included | "dal 10 al 20 ottobre", "fino a domenica", "per tre giorni" |
| `frequency` | `Frequency`: once every N days, weeks, months or years, from the day written | "ogni due settimane", "una volta al mese" |

An `OnDate` is a deadline and a `Period` a window of validity: different
kinds on purpose ([ADR-0021](../adr/0021-one-alert-per-unit.md)).

## The calendar

- **The Jiffin day** runs from 04:00 to 04:00 (`jiffin_day`): before 04:00 it
  is still the day before. Hours before 04:00 are on the next calendar day:
  "domani alle 2 di notte", written on Friday, is 02:00 on Sunday.
- **An instance** is one time a schedule holds: the slot, the whole day or
  the moment of one Jiffin day. `instances(schedule, since)` gives them in
  order, from the one under way: a slot or a day is over once it has ended, a
  moment once it has passed. A slot may end on the next calendar day: "dopo
  le 23" ends at 04:00, "la notte" at 06:00.
- **A frequency** does not change the instances: it groups them into periods
  that follow each other from the day written (`frequency_period`); a period
  of months from the 31st ends where the next one starts, on the last day of
  a shorter month.
- **The next edge** (`next_edge`) is the next start or end of an instance, or
  the start of the next period of the frequency: when a reminder may start or
  stop ringing.
- The calendar works on wall-clock times; `Clock.instant` turns a day and an
  hour into an instant, with the zone's daylight saving.

## The meanings

Every decided meaning is in ADR-0020's table, and in `meanings.py`. Deduced
while building, from the decided ones:

- "un paio di giorni" is two days, as "un paio d'ore" is two hours; "per una
  settimana" is seven days, as "per tre giorni" is three.
- "tutti i lunedì", "tutti i giorni", "tutte le sere" tick "Ogni volta", as
  "ogni lunedì" does: they cannot mean "only then".
- "ogni settimana il lunedì" is every Monday; "ogni due settimane il lunedì e
  il giovedì", with two days, is a frequency with days, not a weekday every
  two weeks.
- In "da lunedì al venerdì", the first preposition decides: without its
  article it is a period, once.
- "fino al 31" in a month of 30 days, and "il 29 febbraio" in a year without
  it, are not understood.

Not understood on purpose, until a meaning is decided: "il prossimo weekend",
"il prossimo lunedì", "intorno alle 9", "dopo pranzo", "in pausa pranzo",
"nel tardo pomeriggio", "nei giorni festivi", "all'alba", "ogni ora", "per
ora", "da domani".

Known limits: a part of the day in a lowercase name is not told from a time
("Le mille e una notte", "la modalità notte"): the time is not understood,
and the condition is saved whole, without time, as if it had none. A time
word capitalized after the first word is a name: "quando apro Excel Lunedì"
has no time.

## The tests

The cases in `tests/fixtures/time/` are #80's 170 synthetic conditions, with
the expectations decided since; `tests/unit/core/test_meanings.py` describes
their format and adds the example tables of #89, #91 and #92. A new phrase is
a new rule and a new case.
