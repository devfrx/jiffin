# ADR-0020: Read the time of a condition with our own grammar in `core`

- **Status:** Accepted
- **Date:** 2026-10-03
- **Deciders:** devfrx
- **Sources:** the [0.2 decision map](https://github.com/devfrx/jiffin/issues/75): tickets [#77](https://github.com/devfrx/jiffin/issues/77) (scope), [#79](https://github.com/devfrx/jiffin/issues/79) (research), [#80](https://github.com/devfrx/jiffin/issues/80) (measurement), [#81](https://github.com/devfrx/jiffin/issues/81), [#82](https://github.com/devfrx/jiffin/issues/82), [#89](https://github.com/devfrx/jiffin/issues/89), [#90](https://github.com/devfrx/jiffin/issues/90), [#91](https://github.com/devfrx/jiffin/issues/91) and [#92](https://github.com/devfrx/jiffin/issues/92) (meanings), [#84](https://github.com/devfrx/jiffin/issues/84) (how the time is shown), [#88](https://github.com/devfrx/jiffin/issues/88) (core design); amends [ADR-0008](0008-rewrite-conditions-english-statements.md)

## Context

In version 0.2 a condition can say when: time slots, weekdays and dates, with
an app or a site ("quando apro Claude dopo le 23") or alone ("alle 15 ricordami
di chiamare Mario") ([#77](https://github.com/devfrx/jiffin/issues/77)). The
judge cannot check a time: it sees a context, not the clock. And its threshold
is calibrated on statements without time
([ADR-0008](0008-rewrite-conditions-english-statements.md)): a condition
without time must keep the statement it has today.

Options considered ([#79](https://github.com/devfrx/jiffin/issues/79)):

- **A library:** none understands Italian time slots and recurrences with the
  decided meanings. dateparser 1.4.3 has no time slots; ovos-date-parser reads
  one date and time per sentence; Recognizers-Text never published its Italian
  periods for Python; Duckling (Haskell, no Windows wheel) and HeidelTime
  (GPL-3.0, Java) do not fit the stack.
- **B, the engine's model constrained by a GBNF grammar:** the model copies the
  time words and fills fixed fields; the code does the arithmetic.
- **H1, A first, then B for what A does not understand.**
- **A, our own grammar in `core`:** a closed vocabulary, exactly the decided
  meanings, no dependency.

A and B were frozen, then measured on 125 held-out synthetic cases written by
sub-agents from the decided meanings only
([#80](https://github.com/devfrx/jiffin/issues/80)):

| | A (grammar) | B (engine + GBNF) | H1 (A, then B) |
|---|---|---|---|
| Silent errors, on 125 held-out cases | 12 (and 5 needless "not understood") | 46 | 26 |
| Decided times read right, on 109 | 106 | 84 | 106 |
| Conditions without time whose statement stays the same, on 41 | 39 | 31 | 35 |
| Vague phrases flagged instead of guessed, on 20 | 13 | 5 | 3 |
| Time per condition (median) | 0.1–0.2 ms | 1.1–1.2 s cold; 0.6–0.8 s with the prompt prefix cached | — |
| Extra VRAM | none | none beyond the loaded engine | — |

B takes names for times ("via 20 Settembre" became 20 September, "l'interno
2145" 21:45) and guesses where the rules are clear ("lunedì" as every Monday).
When A says "not understood", the phrase is usually vague, and B guesses it:
that is why H1 is worse than A alone.

## Decision

**The time is read in `core`, by our own grammar, never by the engine.** Three
pure modules, without dependencies:

- `schedule.py`: the `Schedule` type and its calendar: the Jiffin day, from
  04:00 to 04:00 (`DAY_STARTS_AT` moves here from `reminders.py`), the
  instances, the deadlines.
- `grammar.py`: finds the time words and labels them. It is technique A of
  [#80](https://github.com/devfrx/jiffin/issues/80), with the errors listed
  there fixed.
- `meanings.py`: from the labels to the schedule, with every decided meaning
  in one place; the remainder; and `read(condition, written_at)`, the only way
  in.

**What `read` returns**, a `Reading`:

- `schedule`, or none: no time, or a time not understood;
- `remainder`: the condition without its time words and without the
  connectors they leave hanging; the whole condition, byte for byte, when
  there is no time or it is not understood
  ([#90](https://github.com/devfrx/jiffin/issues/90));
- `unclear`: where the words not understood are, to name them under "Quando";
- `past`: a date already gone, which turns Salva off
  ([#84](https://github.com/devfrx/jiffin/issues/84));
- `recurring`: the words that tick "Ogni volta" by themselves
  ([#92](https://github.com/devfrx/jiffin/issues/92)).

**A `Schedule` is in real dates**, resolved when the condition is written:

| Part | Kinds | Examples |
|---|---|---|
| Days | every day; weekdays; a day with its date; a weekday every N weeks, from a day; the nth or last weekday of the month; a day of the month, 1 to 31 or the last; a day of the year | "il lunedì", "nei giorni feriali", "domani", "lunedì", "un lunedì sì e uno no", "il primo lunedì del mese", "il 15 di ogni mese", "a fine mese", "il 12 marzo di ogni anno" |
| Hours | the whole day; a slot; a moment | "la sera", "dopo le 23", "alle 15", "tra 2 ore" |
| Period, if any | from the first to the last Jiffin day, both included | "dal 10 al 20 ottobre", "fino a domenica", "per tre giorni" |
| Frequency, if any | at most once every N days, weeks, months or years, from the day it is written | "ogni due settimane", "una volta al mese" |

A day with its date and a period are different kinds on purpose. A date is a
**deadline**: a one-off reminder with a date is never lost
([#82](https://github.com/devfrx/jiffin/issues/82),
[#89](https://github.com/devfrx/jiffin/issues/89)). A period is a **window of
validity**: once it ends, the reminder stays and goes silent
([#91](https://github.com/devfrx/jiffin/issues/91)).

**It is read when written.** In the creation window at every key, on the
interface thread, since it is a pure function of 0.1–0.2 ms; then again in
`core` on Salva, with the time of saving: "domani", "tra 2 ore", "fino a
domenica" and the start of a frequency count from there
([#81](https://github.com/devfrx/jiffin/issues/81)). Modifica does not read a
condition again while its text is unchanged: the saved time, remainder and
statement stay, and the line under "Quando" shows the saved time until the
text is touched. Otherwise "domani" written yesterday, after a change to
"Ricordami di" only, would become the day after.

**Stored on the revision** ([ADR-0013](0013-sqlite-storage.md), migration
0002): `schedule` as JSON (its shape is `store`'s, on the types of
`schedule.py`), `remainder` and `perennial`. Revisions from 0.1 become
reminders without time, whose remainder is the condition: they behave as
today, and take a time if edited.

**The statement is written from the remainder**, with the rewriting of
[ADR-0008](0008-rewrite-conditions-english-statements.md), unchanged: same
prompt, same protocol. An empty remainder, a reminder with only a time, is not
rewritten and never reaches the engine. A new revision with the same remainder
copies the statement instead of asking the engine again.

**The words of a time are written by `ui`** when it shows them, next to
today's sentence in `ui/words.py`: `core` gives the structure, the interface
the text. Hours with two digits; dates with the weekday, "Oggi" or "Domani" in
front when they are, and the year only when it is not the current one
([#84](https://github.com/devfrx/jiffin/issues/84)). So "domani alle 21",
written yesterday, reads today "Oggi, venerdì 2 ottobre, alle 21:00".

### The meanings

Decided with the owner on the map; Claude's deductions, accepted, are in the
tickets.

| Words | Meaning | Ticket |
|---|---|---|
| "mattina", "pomeriggio", "sera", "notte" | 06–12, 12–18, 18–23, 23–06 | [#81](https://github.com/devfrx/jiffin/issues/81) |
| "nel weekend"; "nei giorni feriali", "lavorativi", "in settimana" | Saturday and Sunday; Monday to Friday | [#81](https://github.com/devfrx/jiffin/issues/81), [#89](https://github.com/devfrx/jiffin/issues/89), [#90](https://github.com/devfrx/jiffin/issues/90) |
| "dopo le 23"; "prima delle 9"; "dopo cena" | until 04:00; from 04:00; after 21:00, until 04:00 | [#81](https://github.com/devfrx/jiffin/issues/81), [#89](https://github.com/devfrx/jiffin/issues/89), [#90](https://github.com/devfrx/jiffin/issues/90) |
| "alle 15", "verso le 9", "a mezzogiorno", "a mezzanotte" | moments; the hours of a 24-hour clock, so "alle 3" is 03:00; "alle 3 del pomeriggio" 15:00, "alle 11 di sera" 23:00 | [#81](https://github.com/devfrx/jiffin/issues/81), [#89](https://github.com/devfrx/jiffin/issues/89), [#90](https://github.com/devfrx/jiffin/issues/90) |
| hours before 04:00 | belong to the day before: "domani alle 2 di notte", written on Friday, is 02:00 on Sunday | [#90](https://github.com/devfrx/jiffin/issues/90) |
| "domani", "tra 3 giorni", "tra 2 ore", "tra un paio d'ore" | counted from when written, by the Jiffin day | [#81](https://github.com/devfrx/jiffin/issues/81), [#89](https://github.com/devfrx/jiffin/issues/89), [#90](https://github.com/devfrx/jiffin/issues/90) |
| "stasera"; "stanotte" | today's evening; today's night, 23:00 to 06:00 | [#89](https://github.com/devfrx/jiffin/issues/89), [#90](https://github.com/devfrx/jiffin/issues/90) |
| "lunedì"; "il lunedì", "di lunedì", "ogni lunedì" | the next Monday, once (written on a Monday, the one after); every Monday | [#89](https://github.com/devfrx/jiffin/issues/89) |
| "il 5 ottobre" already past | next year's | [#89](https://github.com/devfrx/jiffin/issues/89) |
| a date already past in the day ("stasera" written at 23:30) | flagged: Salva turns off | [#82](https://github.com/devfrx/jiffin/issues/82), [#89](https://github.com/devfrx/jiffin/issues/89) |
| "dal 10 al 20 ottobre", "fino a domenica", "entro domenica", "fino al 20", "per tre giorni", "questa settimana", "la prossima settimana", "da lunedì a giovedì" | periods, both ends included; one already over is next year's, one already started holds from now; "fino a domenica" written on a Sunday is the next one; with the article ("dal lunedì al giovedì") it is every week instead | [#91](https://github.com/devfrx/jiffin/issues/91) |
| "ogni due settimane", "ogni mese", "ogni tre giorni", "una volta al mese", "una volta al giorno", "ogni anno" | frequencies: once per period, at the first occasion, periods counted in Jiffin days from the day written. "Ogni giorno" is every day, not a frequency | [#92](https://github.com/devfrx/jiffin/issues/92) |
| "il primo lunedì del mese" (and second, third, fourth, last), "il 15 di ogni mese", "il primo del mese", "a fine mese", "il 12 marzo di ogni anno", "un lunedì sì e uno no" | days of the month or year, whole days; 29–31 in shorter months are the month's last day; no "quinto lunedì" | [#92](https://github.com/devfrx/jiffin/issues/92) |
| "ogni…", "un lunedì sì e uno no", and recurrences of the month or the year | tick "Ogni volta" by themselves, once, while the user has not touched the box; "il lunedì", "la sera", "nei giorni feriali", "nel weekend" do not | [#92](https://github.com/devfrx/jiffin/issues/92) |
| anything else that looks like time ("verso sera") | not understood: the reminder is saved without time, the whole condition goes to the rewriting, and the line under "Quando" names the words | [#90](https://github.com/devfrx/jiffin/issues/90) |

## Consequences

**Positive**

- Instant and checkable: every phrase is a test case. No VRAM, no prompt or
  GBNF to version and measure again at every change of model.
- The statement of a condition without time stays as today, so the threshold
  calibrated by [ADR-0008](0008-rewrite-conditions-english-statements.md)
  holds.
- Real dates make a saved time independent of the grammar's version: a later
  fix does not move reminders already saved.
- The line under "Quando" shows at every key what Jiffin understood, so a
  wrong reading is seen before saving.

**Negative (accepted)**

- A grammar of rules will always meet phrases it does not know. It flags them
  instead of guessing ([#90](https://github.com/devfrx/jiffin/issues/90)), and
  the reminder still works, without its time.
- Our own grammar to maintain: each new phrase is a rule and a test.
- On the measurement, 2 of 41 conditions without time had their statement
  changed (a name in quotes, "alle 20 pagine della tesi"). Both are among the
  errors to fix.

**Follow-up**

- The prototype of [#80](https://github.com/devfrx/jiffin/issues/80) and its
  170 synthetic cases, with the example tables of
  [#89](https://github.com/devfrx/jiffin/issues/89),
  [#91](https://github.com/devfrx/jiffin/issues/91) and
  [#92](https://github.com/devfrx/jiffin/issues/92), become the tests of
  `core`; the errors of A listed in #80 are fixed on the way.
- When `core` reads the time, `docs/design/` gets its description, and this
  record stays as history.
