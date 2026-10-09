# ADR-0028: Read the situations of a condition in `core`, from states and never from texts

- **Status:** Accepted
- **Date:** 2026-10-07
- **Deciders:** devfrx
- **Sources:** the [0.3 decision map](https://github.com/devfrx/jiffin/issues/119): tickets [#123](https://github.com/devfrx/jiffin/issues/123) (research), [#124](https://github.com/devfrx/jiffin/issues/124) (which signals), [#134](https://github.com/devfrx/jiffin/issues/134) (the trial on the machine, discarded) and [#125](https://github.com/devfrx/jiffin/issues/125) (decision); amends [ADR-0001](0001-keep-data-and-inference-local.md), [ADR-0004](0004-context-identity.md), [ADR-0008](0008-rewrite-conditions-english-statements.md), [ADR-0012](0012-package-structure-ports.md), [ADR-0013](0013-sqlite-storage.md), [ADR-0014](0014-feedback-data-retention.md), [ADR-0017](0017-evaluation-harness-subpackage.md), [ADR-0019](0019-five-second-debounce.md), [ADR-0020](0020-read-the-time-in-core.md) and [ADR-0021](0021-one-alert-per-unit.md)

## Context

The owner asked Jiffin to understand more of what the user does, for example
when a call ends ([#119](https://github.com/devfrx/jiffin/issues/119)):
conditions such as "quando finisco la call" or "quando sono su YouTube da più
di 20 minuti". In 0.2 the judge sees only the app, the title and the address
([ADR-0004](0004-context-identity.md)). Read at `1006e4e`, "quando finisco la
call" goes whole to the judge, which does not see the call; "da più di 20
minuti" is a time not understood, and that condition goes whole to the judge
too.

What a local app can know on Windows 11
([#123](https://github.com/devfrx/jiffin/issues/123)):

- **A call:** Core Audio's capture sessions say which app captures from a
  microphone: documented, with events, without consent. In a browser they see
  the whole browser; the tab is the one Chromium marks in its accessible name
  as recording or sharing, in Chrome and Brave (Vivaldi to try). The mark is a
  translated text, not a contract.
- **Cheap and reliable:** idle time, power, playback, headphones, displays,
  the network's profile.
- **Heavy for privacy:** notifications and the text on screen.
- **No local source:** the calendar. The Wi-Fi's name through the WLAN API
  asks for the location consent since autumn 2024, and lights its icon.

Which signals enter was the owner's choice
([#124](https://github.com/devfrx/jiffin/issues/124)). Where to read them:

- **In the judge's evidence:** the cache's key is exactly the text the model
  sees, so a situation in the evidence multiplies the keys, and a duration
  changes every second: every change would be a new judgement, and the engine
  would never sleep ([ADR-0027](0027-light-sleep-of-the-engine.md)). A new
  evidence also changes the judge's prompt and moves its threshold
  ([ADR-0008](0008-rewrite-conditions-english-statements.md),
  [ADR-0003](0003-acceptance-thresholds.md)), and the places of
  [ADR-0029](0029-learn-from-answers-per-place.md) and the harness's labels
  would multiply (deduced).
- **The engine, with a GBNF grammar:** on the time it made 46 silent errors in
  125 cases, against 12 of our grammar
  ([ADR-0020](0020-read-the-time-in-core.md)).
- **The code, as for the time.**

The trial on the machine ([#134](https://github.com/devfrx/jiffin/issues/134))
was discarded without numbers: the owner could not hold a call. The end of a
call is checked on real calls, from the acceptance day of 0.3; the other
signals while building.

## Decision

**Jiffin reads states, never texts.** Beyond the app, the title and the
address of the window in front, it knows *whether* and *when* something
happens, never what is written. A permanent rule, next to "everything local"
and "no telemetry" ([ADR-0001](0001-keep-data-and-inference-local.md)).

- **In** (the owner's choice): the call (which app uses the microphone, from
  when to when; in a browser, whether the tab in front records or shares the
  screen); playback (only whether something plays, never its title or
  artist); the state of the PC (idle time, power, displays, headphones); the
  network, with a label the owner gives.
- **Out:** the text and the sender of notifications, the text on screen and
  of the field being typed in, the calendar, the Wi-Fi's name, the camera,
  the undocumented ConsentStore, connected devices; Do Not Disturb stays
  unread ([ADR-0024](0024-hold-and-hide-alerts.md)).

**The code reads the situations, as it reads the time.** `core`'s grammar
reads, beyond the time, the situations of a condition: one that holds
("quando sono in call"), one that ends ("quando finisco la call"), and how
long a situation or the thing the judge checks has lasted ("quando sono su
YouTube da più di 20 minuti"). The rest of the condition goes to the judge as
in 0.2: statements, prompts, the threshold T = 0.97 and the cache do not
change, and a change of situation never wakes the engine. A technical choice,
delegated by the owner; the names in the code, the end of the things the
model judges and the places of the networks are the owner's.

**The situations**, each a value over time (names confirmed by the owner):

| Situation | Holds when | Examples | From |
|---|---|---|---|
| `call` | an app captures from a microphone; that app, when the condition names a call app ("su Zoom", "su Meet"). In a browser the app is the browser, and the site the one of the tab in front that records; when the tab cannot be read, the whole browser | "in call", "durante la chiamata", "quando finisco la call", "dopo la videochiamata", "in call su Zoom da più di un'ora" | Core Audio's capture sessions; the accessible name of the tab in front, only while a browser captures |
| `away` | no key or mouse for 3 minutes, without a call and with nothing playing; or the PC locked or asleep | "quando torno al PC", "quando torno", "se sono via da più di 10 minuti" | `GetLastInputInfo`; the lock and sleep notices the capture already gets |
| `power` | on battery, or plugged in | "a batteria", "quando stacco il caricatore", "in carica" | `GetSystemPowerStatus` and the power notices |
| `display` | an external monitor is connected | "con il monitor esterno", "quando collego lo schermo" | Qt's `screenAdded` and `screenRemoved`, or `QueryDisplayConfig` |
| `headphones` | the default output is headphones or a headset | "con le cuffie", "quando metto le cuffie", "quando tolgo le cuffie" | `IMMNotificationClient` |
| `network` | a network the owner called home (`home`) or office (`office`); or no network | "a casa", "in ufficio", "quando esco di casa", "senza rete" | the Network List Manager, by the network's id and never its name; the label is in the settings |
| `playback` | something plays | none: it keeps `away` off in front of a video | GSMTC through `ctypes`, or Core Audio's output sessions, chosen while building after a trial |

- **The call apps** are a closed list, with their executable and their site:
  Discord, Zoom, Teams, Meet and the like. Another name after a call ("con
  Mario") makes the situation not understood.
- **Of playback** the code knows only *that* something plays. "Musica",
  "video" and "podcast" say *what*: they stay with the judge, which sees the
  window, as in 0.2.
- **The 3 minutes of `away`** are ActivityWatch's (180 s); to be verified.
- **Home and office are fixed** (the owner's choice): `read` does not depend
  on the settings, and a label cannot change the meaning of a phrase ("al
  lavoro").

**Three forms:**

| Form | Means | Examples |
|---|---|---|
| holds (`holds`) | the situation holds now | "quando sono in call", "quando entro in call", "a batteria" |
| ends (`ends`) | a stretch of the situation has just ended (5 s ago) | "quando finisco la call", "dopo la chiamata", "quando tolgo le cuffie", "quando torno" (the end of `away`) |
| lasts (`lasts`) | the stretch of a situation, or the occasion of the thing the judge checks, has lasted at least N minutes | "in call da più di un'ora", "quando sono su YouTube da più di 20 minuti", "da almeno mezz'ora" |

- **A thing lasts from the start of its occasion:** an absence shorter than
  the return pause does not start it again, as it starts no new occasion
  ([ADR-0021](0021-one-alert-per-unit.md)). A situation lasts from the start
  of its stretch.
- **"Da più di N" goes with the situation written just before it**; without
  one, with the thing.
- **Not understood on purpose**, named under "Quando" and never guessed:
  - the end of a thing the model judges: "quando chiudo Figma", "quando
    finisco di lavorare", "quando smetto di guardare YouTube" (the owner's
    choice: as the end of an occasion it would also ring at every break
    longer than the return pause);
  - durations that do not say since when: "per 20 minuti", "dopo 20 minuti",
    "da un po'", "più di un'ora al giorno";
  - the battery's level, the lid, what plays, who the user talks with;
  - two situations of the same kind, or an end and a duration together.
- **"Ogni volta che finisco una call"** ticks "Ogni volta", as every "ogni…"
  does.

**Situations over time.**

- **The capture sends `core` an observation at each change** (time,
  situation, value), as it does for contexts; at start, the state of each.
- **A change counts once it has lasted 5 s**, like a context
  ([ADR-0019](0019-five-second-debounce.md)): a microphone that stops for 2 s
  does not end the call. A stretch starts when the value arrives and ends when
  it leaves, not 5 s later, as `context_since` does. `core` counts the 5 s, so
  the replay gives the same stretches.
- **5 s is a starting number** (assumed): real calls tell whether it is
  enough. It is shorter than the return pause on purpose: a false end gives a
  wrong alert, which shows, and the true end still rings, being another unit
  (unless the wrong alert is answered Done); waiting for the return pause
  would make the end of every call ring 2 minutes late.
- **A situation never enters the context.** A place stays app, title and
  address ([ADR-0004](0004-context-identity.md)), so Not here and Remind here
  ([ADR-0029](0029-learn-from-answers-per-place.md)) do not change.

**In the units** ([ADR-0021](0021-one-alert-per-unit.md)). A reminder still
rings at most once per unit. Situations add:

| Condition | Unit | May ring | Example |
|---|---|---|---|
| a situation that holds, no remainder | each stretch of the situation, within its time | during the stretch | "quando sono in call ricordami di…": once per call |
| a situation that holds, with a remainder | the occasion, as in 0.2: a true stretch needs the situation too, as it needs the time | | "quando sono a casa e apro Steam" |
| an end, no remainder | each end, as a moment | from the confirmed end: without "Ogni volta" until the next end, so never lost; with it, until 04:00 of its Jiffin day | "quando finisco la call" |
| an end, with a remainder | each end: it rings at the first occasion of the remainder after it, as a moment with an app | as above | "quando finisco la call e apro Outlook" |
| a duration of a situation | each stretch, once it has lasted N | from start + N to the end of the stretch | "quando sono in call da più di un'ora" |
| a duration of the thing | the occasion, once it has lasted N | from the occasion's start + N, while a true stretch goes on | "quando sono su YouTube da più di 20 minuti" |

- **With a time,** situation and time must hold together, and an end counts
  only within its time ("quando finisco la call stasera").
- **A change of situation is a deadline**, like the start or the end of a
  time: the stable context is evaluated again from the cache. So is the start
  + N of a duration.
- **A new outcome, `outside_situation`**, after `outside_time`: true and
  within its time, but its situation does not hold (absent, an end not come
  yet, a duration not reached). Every reminder is still judged in every stable
  context, outside its situation too, so its score is in the cache when the
  situation comes.
- **A reminder without a remainder** (only a time, only situations, or both)
  is not judged: its alert has no evaluation and no d, and it rings with the
  engine off or asleep. Its `due_at` is when the situation made it due (the
  start of a stretch, an end, the start + N), or the arrival of the context
  when later: the 5 s count in the delay, as a context's debounce does.
- **Not here on its alert** acts as on a reminder with only a time: it may
  ring in the next stable context, if its unit still holds.
- **After a restart of the app** the stretches start again from the state read
  at start, as occasions do: a call in progress loses its minutes (deduced; a
  known limit, as rare as a restart).
- **During the pause from the tray** ([ADR-0024](0024-hold-and-hide-alerts.md))
  the situations are read and recorded; an end that comes during the pause
  waits, like a moment.

**In the grammar** ([ADR-0020](0020-read-the-time-in-core.md)).

- `grammar.py` reads the situations besides the time, and `read` gives a
  `Reading` with `situations` next to `schedule`. Same technique: a closed
  vocabulary, labels, the remainder without these words and what they leave
  hanging, and "not understood" when something looks like a situation, an end
  or a duration but is not understood.
- `read` stays a pure function: home and office are fixed, so it needs no
  settings.
- The words live in `src/jiffin/lang/it/situations.toml` (sections `read` and
  `write`), next to `time.toml` ([ADR-0026](0026-italian-in-language-files.md));
  the rules stay code. The call apps' names are names, not Italian: they live
  in `core`, with their executable and their site.
- The words under "Quando" and in the alert ("Alla fine della call", "Da più
  di 20 minuti"…) are written by `ui/words.py` from the catalog; the owner
  picks them while building, from a list.
- A condition made of situations only ("quando finisco la call") has an empty
  remainder: it is never rewritten and never judged.

**In the judge** ([ADR-0008](0008-rewrite-conditions-english-statements.md))
**and in the cache, nothing changes:** the evidence (app, title, address), the
prompts (judge v1, rewriting v2), T = 0.97, the cache's key (context,
revision, build). The rewriting gets the condition without the words of its
time and situations: "quando sono su YouTube da più di 20 minuti" becomes
"quando sono su YouTube", with 0.2's statement. No new measure of the judge.

**In the database**, migration 0003 ([ADR-0013](0013-sqlite-storage.md)):

- `revision.situations`: the situations part, as JSON like `schedule` (its
  shape is `store`'s); empty without situations.
- **A new table, `situation`:** one row per stretch of a value (kind, value,
  from, until), like the stretches of contexts on the evaluations. The value
  is the executable of the app (call, playback), the site of the recording
  tab, `home`, `office` or no network, yes or no: never a title, a track or a
  network's name. Kept 30 days, like the evaluations
  ([ADR-0014](0014-feedback-data-retention.md)): the cleanup deletes older
  rows. `core` sends one record per stretch, like `Left`.
- `candidate.outcome` takes `outside_situation`: the table is rebuilt for its
  CHECK, as in 0002.
- `alert` does not change.
- The settings keep the networks' labels (an id → `home` or `office`).

**In the capture** (the context port of
[ADR-0012](0012-package-structure-ports.md)). The context thread, already in
the multithreaded apartment Core Audio's events need, sends the situations'
observations only at changes, and the state of each at start. Its log stays
as it is: app names, counts and error codes, never titles or network names.
To try while building ([#134](https://github.com/devfrx/jiffin/issues/134)):
playback's events, idle time in front of a video, headphones, displays, power
and network with no icon or prompt from Windows, and WinRT through `ctypes`
in the first package.

**In the harness** ([ADR-0017](0017-evaluation-harness-subpackage.md)).

- `snapshot` copies `situation`; `replay` puts the situations back as
  observations at their time, with the contexts. A day from before 0.3 has
  none: its reminders with situations are never in their situation, and the
  report says so.
- `label` does not change: a label says whether the remainder is true in the
  context; the code checks time and situations, as in ADR-0021.
- `report` counts the reminders without a remainder apart, right when the
  situation is read right; it gives the reason "outside its situation", and
  the delay of an alert at an end from the end.
- `statements` shows the situations understood, next to the time.

**What this amends.**

- [ADR-0001](0001-keep-data-and-inference-local.md): Jiffin reads states,
  never texts.
- [ADR-0004](0004-context-identity.md): a situation is not part of the
  context.
- [ADR-0008](0008-rewrite-conditions-english-statements.md): the rewriting
  gets the condition without the words of its situations.
- [ADR-0012](0012-package-structure-ports.md): the context port also gives
  the situations' observations.
- [ADR-0013](0013-sqlite-storage.md) and
  [ADR-0014](0014-feedback-data-retention.md): `revision.situations`, the
  table `situation` kept 30 days, the outcome `outside_situation`.
- [ADR-0017](0017-evaluation-harness-subpackage.md): what the harness copies,
  replays and reports.
- [ADR-0019](0019-five-second-debounce.md): the 5 s hold for situations too.
- [ADR-0020](0020-read-the-time-in-core.md): the grammar reads situations, and
  the remainder loses their words.
- [ADR-0021](0021-one-alert-per-unit.md): the units, the end as a moment, the
  durations, the outcome.

## Consequences

**Positive**

- The judge, its threshold and its cache stay as measured: no new measure of
  the judge.
- A change of situation never wakes the engine.
- Every phrase is a test case, and the line under "Quando" shows what was
  understood before saving.
- Only states are kept, never texts or names.

**Negative (accepted)**

- A closed vocabulary: phrases it does not know are named as not understood,
  and the reminder works without its situation.
- The end of a thing the model judges is not understood.
- The 5 s of a change and the 3 minutes of `away` are assumed until real days
  measure them.
- After a restart, a call in progress loses its minutes.
- The tab that records is read from a translated text: when it cannot be
  read, the whole browser counts, the mistake that shows.

**Follow-up**

- On real calls, from the acceptance day of 0.3
  ([ADR-0031](0031-acceptance-thresholds-v0-3.md)): that 5 s are enough with
  mute, a waiting room and a return to the call; that Discord, Zoom and Meet
  close their capture session at the end; the tab's name in Vivaldi. And that
  3 minutes without input suit "quando torno".
- While building: playback's events, and idle time in front of a video.
- Left to the owner while building: the words under "Quando" and in the
  alert; where a network takes its label.
- When this is built, `docs/design/` follows: `context.md`, `time.md` (or a
  page of its own), `pipeline.md`, `lifecycles.md`, `data-model.md`,
  `harness.md`, `creation.md` and `settings.md`.
- Chosen by the owner on [#153](https://github.com/devfrx/jiffin/issues/153)'s
  trial, on the app's preview: the ends written without a person ("Alla fine
  della call", "All'uscita di casa"), "Fuori situazione" on the card of Remind
  here, and three places for a network's label, the settings, the creation
  window and the tray list, the last two while a reminder names a place no
  network has ([situations](../design/situations.md#writing-them),
  [settings](../design/settings.md#the-network)). Built there too: "quando
  esco da casa" and "quando esco dall'ufficio" read as ends, the ends of home
  and the office now tried before what holds there; and a label goes on every
  network connected at once, so a network connected in both places, as a VPN,
  keeps the label put last.
- Found on that trial, against the first negative above: some phrases the
  list does not know go to the judge in silence, with nothing named under
  "Quando", a typo ("quando tolgo le cufie") or a word outside the list
  ("quando sono in casa", "quando sono in riunione"). The owner kept the list
  and asked that nothing go in silence:
  [#169](https://github.com/devfrx/jiffin/issues/169).
