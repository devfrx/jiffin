# The situations

How Jiffin reads the situations of a condition, "quando finisco la call", "a
casa", "quando sono su YouTube da più di 20 minuti", and when a reminder with
them rings ([ADR-0028](../adr/0028-read-the-situations-in-core.md)). Jiffin
reads states, never texts: whether an app captures from a microphone, the
user is away, the PC runs on battery, an external display or headphones are
connected, which network it is on, and whether something plays.

The code is in `core`: `situations.py` holds the situations, the call apps,
the terms of a condition and `Situations`, which follows them over time;
`grammar.py` finds their words beside the time's, `meanings.py` has `read`,
and `reminders.py` and `units.py` ring them. The words are the lexicon's,
`situations.toml`. The context thread observes them
([context.md](context.md#the-situations)); the store keeps a revision's terms
and the stretches ([data model](data-model.md)).

## The situations

| Situation | Its values | Holds when |
|---|---|---|
| `call` | the executables of the apps that capture from a microphone; for a browser, the site of the tab in front that records, when its name can be read | an app captures; with an app named, a call on it |
| `away` | `yes`, `no` | no key, mouse, call or anything playing for 3 minutes (`AWAY_MS`); or the PC locked or asleep |
| `power` | `battery`, `plugged` | |
| `display` | `yes`, `no` | an external display is connected |
| `headphones` | `yes`, `no` | the default output is headphones or a headset |
| `network` | `home`, `office`, by the labels of the settings; `offline`; none on a network without a label | |
| `playback` | the ids Windows' media controls give the apps that play, in lower case: `spotify.exe`, `vivaldi.<id>` | no words name it: it keeps `away` off in front of a video |

- **The call apps** are a closed list in `core`, `CALL_APPS`, each with the
  names a condition gives it, its executables and its sites: Discord, Meet
  ("Google Meet"), Slack, Teams ("Microsoft Teams"; since January 2026 its
  calls run in `ms-teams_modulehost.exe`), Telegram, WhatsApp and Zoom. A site
  is one of its domains or under one. A supported browser whose tab that
  records could not be read counts whole: its call is on any app with a site,
  the mistake that shows. Another browser is a call, but on no app by name.
- **Values, never texts:** an executable, a site, a label; never a title, a
  track or a network's name.

## Reading them

`read` reads the situations first, with the technique of the time
([time.md](time.md)): a closed list of phrases, built from the lexicon, tried
in order; a match may not overlap an earlier one ("torno a casa" before
"torno"). Each phrase may take the verb that leads into it: "sono in call",
"esco di casa". Names are no situations, as they are no time, but the names of
the call apps are: "su Zoom", "al PC". Then the situations are set aside, as
names are, and the time is read on the rest: their words are no time, and
their durations ("da più di 20 minuti") are no count of hours left over.

`read` gives `situations`, a tuple of terms in the order written; none
without situations, or when they are not understood:

| Term | Means | Examples |
|---|---|---|
| `Holds(situation, value)` | the situation holds | "quando sono in call", "in call su Zoom", "a batteria", "con le cuffie", "senza rete", "quando torno a casa" |
| `Ends(situation, value)` | a stretch of it has just ended | "quando finisco la call", "dopo la videochiamata", "quando tolgo le cuffie", "quando stacco il caricatore", "quando esco di casa", "quando torno" (the end of `away`) |
| `Lasts(minutes, situation, value)` | its stretch has lasted at least that long; with no situation, the occasion of the thing the judge checks | "in call da più di un'ora", "se sono via da più di 10 minuti", "quando sono su YouTube da più di 20 minuti" |

- **The value** is the one the situation holds with: for a call, the name of
  a call app, or none for any call; for the others, one of the values above.
- **A duration** ("da più di", "da almeno", "da oltre", or "da" alone, then
  minutes or hours) goes with the situation written right before it; without
  one, with the situation right after it ("quando sono da più di un'ora in
  call"); else with the thing the judge checks. The second rule is deduced:
  the ADR says only "right before".
- **The remainder** loses the words of the time and of the situations, and
  what they leave hanging, as the time's does. What opens a condition
  ("quando", "se", "ogni volta che…"), and a verb the situations left ("quando
  sono"), go too when nothing else is left: "quando sono in call" has an empty
  remainder, and is never rewritten nor judged.

**Not understood**, named under "Quando" and never guessed:

- a word of a situation outside a phrase understood: "quando ho una call",
  the battery's level ("50% della batteria"), the lid, the Wi-Fi;
- the end of a thing the judge checks: "quando chiudo Figma", "quando finisco
  di lavorare", "quando smetto di guardare YouTube";
- a duration that does not say how long, or not in minutes or hours: "da un
  po'", "da più di 2 giorni"; one that does not say since when ("per 20
  minuti", "dopo 20 minuti") is the time's;
- a word before a phrase that changes it, "quando non sono in call", "vicino a
  casa"; or after it, "in call con Mario", "la call delle 15", "a casa di
  Mario", "in carica il PC", unless a time, a duration or another situation
  starts there ("a casa la sera", "in call con le cuffie");
- two situations of a kind, two ends, an end with a duration, and a duration
  of the thing in a condition with no thing ("da più di 20 minuti" alone).

Situations not understood leave the condition as it reads without them: its
time, if understood, and the remainder with their words, which go to the
judge as before 0.3. A time not understood leaves the whole condition, byte
for byte, and no situations: the line under "Quando" names its words, and
the user writes it again. Work is no office ("al lavoro"), and what plays
("musica", "video") stays with the judge, which sees the window.

## Over time

The capture sends `core` a `SituationObservation` at each change, and the
state of each situation at start: its time, the situation, and all its values
now.

- **A change counts once it has lasted 5 s** (`CHANGE_MS`), as a context does
  ([ADR-0019](../adr/0019-five-second-debounce.md)): a microphone that stops
  for 2 s does not end the call, and one observed then gone is none. Once it
  counts, its values hold from when they arrived, and those gone left then.
  `core` counts the 5 s, so a replay gives the same stretches.
- **How a situation holds with a value** is followed through every change: it
  holds from when it began to, through changes of values that keep it holding
  (a Meet call whose tab is read, then not: the browser counts whole), and it
  ended when it stopped. A situation followed for the first time holds from
  when its values arrived; an end before is not known.
- **Each value's stretch** is recorded once it ended, `SituationStretch`
  (situation, value, since, until), as `Left` is for contexts: a row of the
  table `situation`, kept 30 days.
- **Not read any more** (`values` None, when the app ends or the capture loses
  it) ends the stretches at once, and is no end. At the app's close the worker
  observes every situation so, all at the time the context in front leaves:
  where the harness finds the close.
- **After a restart** the stretches start again from the state read at start:
  a call in progress loses its minutes, a known limit.
- **During the pause** the situations are read and recorded.

## When a reminder rings

A reminder still rings at most once per unit
([lifecycles.md](lifecycles.md)), while its time holds and its situations
hold together, from when the last of them began to:

| Condition | Unit | May ring |
|---|---|---|
| a situation that holds, no remainder | each stretch of it, within its time: a stretch over three evenings of "la sera" is three | during the stretch |
| a situation that holds, with a remainder | the occasion: a true stretch needs the situation too, as it needs the time | |
| an end, no remainder | each end, as a moment | from the end that counts, 5 s after it: one-off until the next end, so never lost; with "Ogni volta" until 04:00 of its Jiffin day |
| an end, with a remainder | each end: at the first occasion of the remainder after it, as a moment with an app | as above |
| a duration of a situation | each stretch, once it has lasted N | from its start + N to its end |
| a duration of the thing | the occasion, once it has lasted N | from the occasion's start + N, while a true stretch goes on |

- **With a moment, a frequency or a one-off date** the unit stays the
  instance of the time, and the situations are one more thing that must hold:
  "alle 15 se sono in ufficio" rings once, from 15:00, once in the office.
- **An end counts** after the condition was written and within the window of
  its time under way: "quando finisco la call stasera" does not ring for a
  call that ended at 17:00.
- **A change of situation is a deadline**, and so is a duration reached: while
  a context is stable it is judged again, from the cache, for the reminders on
  them. A true stretch ends when its situation stopped, not when the change
  counted.
- **The outcome `outside_situation`**, after `outside_time`: true and within
  its time, but a situation does not hold, an end has not come, a duration is
  not reached. Every reminder with a remainder is still judged in every stable
  context.
- **Without a remainder** a reminder is never judged: its alert has no
  evaluation and no d, rings with the engine down or asleep, and is due when
  the situation made it due (the start of a stretch, an end, a duration
  reached) or when its context came, if later.
- **Not here** on its alert keeps it quiet in that context; it may ring in the
  next stable one, if its unit still holds. **Remind here** rings a reminder
  outside its situation too, as asked, and the card names why it was quiet.
- **During the pause** nothing rings but a Remind here; an end that came
  meanwhile rings at its end, due from the return.

## The lexicon

The words are data, the rules are code
([ADR-0026](../adr/0026-italian-in-language-files.md)):
`src/jiffin/lang/it/situations.toml` holds them, and
`jiffin.lang.situations` reads it once, at import, into `SITUATIONS`. Its
`read` section holds, by role: what opens a condition, the modifiers before
and after a phrase, the words left over, the leads of a duration, and for each
situation its phrases, a placeholder standing for its words ("in {call}",
"tolgo {headphones}"), with the verbs that may lead into them. The section
`write`, the words under "Quando" and on the alert, comes with
[#153](https://github.com/devfrx/jiffin/issues/153): the owner picks them
from a list. The names of the call apps are names, not Italian: they live in
`core`.

## The tests

`tests/unit/core/test_meanings.py` reads every phrase of ADR-0028, understood
or not; `tests/unit/core/test_situations.py` follows the situations over time;
`tests/unit/core/test_reminders.py` rings them, a test for each row of the
table above. Conditions without situations read as before: the time's case
files pass unchanged.
