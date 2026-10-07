# Judging pipeline

How a context in the foreground becomes an alert, in `jiffin.core`
([ADR-0007](../adr/0007-single-stage-pipeline.md),
[ADR-0012](../adr/0012-package-structure-ports.md),
[ADR-0021](../adr/0021-one-alert-per-unit.md)). The code is
`core/reminders.py`; the debounce is `core/debounce.py`, the units and the
windows of a time `core/units.py`.

```mermaid
sequenceDiagram
    participant P as platform (context thread)
    participant W as worker thread
    participant R as core: Reminders
    participant M as model port (client, engine)
    participant U as ui (main thread)
    participant S as store

    P->>W: Observation(at, context)
    W->>R: observe(observation)
    Note over R: every change of context starts the 5 s debounce again,<br/>and a stable context that leaves ends its true stretches
    W->>R: poll(), once the clock reaches R.deadline
    R->>R: write the statements still missing (rewrite the remainder)
    R->>R: look up the cache: (context, revision, engine build)
    R->>M: judge(context, the statements missing from the cache)
    alt the engine answers
        M-->>R: d for every statement
        R->>R: an outcome for every judged reminder
    else the engine fails
        M-->>R: ModelError
        R->>R: the evaluation is recorded as failed, never as "no alert"
    end
    R->>R: ring the reminders with only a time, which are never judged
    R-->>U: on_alerts(AlertsView)
    W->>R: take_records()
    R-->>W: evaluations, cache entries, alerts, when contexts left
    W->>S: save them
```

While a context stays stable, the same steps run again, from the cache, for
the reminders whose snooze ends or whose time starts or ends: "quando apro
Claude dopo le 23", with Claude in front since 22:30, rings at 23:00.

## The outcome of a judged reminder

Every active reminder whose revision has a statement is judged in every stable
context, also out of its time, so that its score is in the cache when its time
comes. The first outcome that applies is recorded with the evaluation:

1. **below threshold**: d < `THRESHOLD` (0.97, a constant tied to the engine's
   model and prompts, kept on the acceptance day of 0.2; only the harness
   replays a day at another);
2. **outside time**: true, but its time does not hold now;
3. **silenced**: Not here was answered in this exact context;
4. **snoozed**: its snooze with a time has not ended;
5. **same occasion**: it has rung already in its unit, and no snooze has ended
   since ([lifecycles.md](lifecycles.md));
6. **alert**.

`held_back`, the once-an-hour rule of version 0.1, stays only in its rows. A
reminder with only a time rings in any stable context while its time holds,
unless silenced there, snoozed or rung in its instance: it has no evaluation
and no d, and rings while the engine is down.

An alert records when it became due: the arrival of its context, the start of
its time or the end of its snooze, whichever came last
([ADR-0022](../adr/0022-acceptance-thresholds-v0-2.md)).

## Driving `Reminders`

- **Worker thread.** One event at a time: `observe()` for every observation;
  `poll()` when the clock reaches `deadline`, the earliest of the debounce, the
  snooze ends and, while a context is stable, the next start or end of each
  reminder's time; the user's commands. Between events it waits on its queue
  until `deadline`. Every call handles the deadlines already due first, so a
  late `poll()` loses nothing. When the app closes, the worker observes "no
  context", so the context in front leaves with it.
- **Store.** After every event, `take_records()` returns what changed, in
  saving order: reminders (with their current revision), deletions, silences,
  cache entries, evaluations, when a stable context left, alerts.
  `Store.save()` keeps them in one transaction: records with an id replace the
  previous record with that id, a cache entry replaces the one with the same
  context, revision and engine build, and when a context left goes on the
  evaluations of that stretch. At startup, `Reminders` starts from
  `Store.load()`, with the return pause the worker reads in the settings (2
  minutes by default); a new one from the settings is in force at once, for
  the stretches that start after it. The schema is in
  [data-model.md](data-model.md).
- **Interface.** `on_alerts` receives an `AlertsView` after every change, on
  the worker thread: the alerts on screen (at most 3), how many wait, and those
  that vanished unanswered, one per reminder. `on_reminders` receives a
  `RemindersView` after every change of a reminder or of its silences: the
  active reminders, newest first, each with how many contexts Not here
  silenced it in. The interface answers with `done`, `snooze` (with its kind),
  `not_here`, `close` (the X), `vanished` (its own 10 s timer) and `seen` (the
  tray list is open), and changes the reminders with `create`, `edit` (both
  with "Ogni volta"), `complete` and `delete`. Commands about something already
  gone do nothing. Whether Next time has a unit to wait for, and
  whether a period has ended, are pure functions of `core/units.py` it may call
  itself: `next_occasion` and `ended`.
- **Model port.** `build()` names the engine that answers, also while it
  restarts; `judge()` scores every statement it gets; `rewrite()` turns a
  remainder into its statement; any failure is a `ModelError`.
- **Harness.** A replay moves the simulated clock to the next observation or
  `deadline`, whichever comes first, so every evaluation happens at its exact
  time.
