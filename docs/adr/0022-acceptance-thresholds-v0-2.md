# ADR-0022: Accept version 0.2 with false alarms counted once per pair, target 10 and cap 20

- **Status:** Accepted; amended by [ADR-0025](0025-kept-quiet-not-missed.md) (pairs kept quiet as already reminded are not missed) and [ADR-0031](0031-acceptance-thresholds-v0-3.md) (the thresholds of 0.3)
- **Date:** 2026-10-03
- **Deciders:** devfrx
- **Sources:** the [0.2 decision map](https://github.com/devfrx/jiffin/issues/75): tickets [#87](https://github.com/devfrx/jiffin/issues/87) (thresholds), [#86](https://github.com/devfrx/jiffin/issues/86) (alerts measured) and [#76](https://github.com/devfrx/jiffin/issues/76) (return pause); amends [ADR-0003](0003-acceptance-thresholds.md)

## Context

[ADR-0003](0003-acceptance-thresholds.md) accepts a version on a real working
day: false alarms target ≤ 5 a day, cap 10, with a reminder ringing at most
once an hour. Version 0.2 replaces that rule: a reminder rings once per
occasion, and comes back when the user returns to the thing after at least the
return pause, 2 minutes by default
([#76](https://github.com/devfrx/jiffin/issues/76),
[ADR-0021](0021-one-alert-per-unit.md)). The same wrong pair can now ring many
times a day.

The captured day of 2026-09-28 (9 reminders, about 4.7 hours with a context in
front), replayed under each rule, with nobody answering
([#86](https://github.com/devfrx/jiffin/issues/86)):

| Rule | Alerts | Distinct pairs | False alarms, if nobody answers | False alarms, if each is answered "Non qui" |
|---|---|---|---|---|
| Once an hour (0.1) | 38 | 25 | 5 (3 doubtful) | 5 (3 doubtful) |
| Occasion, pause 10 s | 247 | 71 | 39 (29 doubtful) | 13 (7 doubtful) |
| **Occasion, pause 2 min (default)** | **103** | **43** | 18 (12 doubtful) | **10 (5 doubtful)** |
| Occasion, pause 15 min | 36 | 23 | 9 (6 doubtful) | 6 (3 doubtful) |

With the default pause the false alarms double, 5 to 10, already at the cap of
ADR-0003 with 9 reminders instead of about 20.

## Decision

**False alarms: target ≤ 10 a day, cap 20**, the owner's choice: twice
ADR-0003, as the measured doubling. ADR-0003's rule stands: when missed
reminders and false alarms conflict, missed reminders win; false alarms may go
over the target, never over the cap.

**How they are counted** (Claude's method, told to the owner before the
question and not contested):

- **A false alarm is a wrong (context, reminder) pair that gave at least one
  alert in the day.** It counts once, even if the alert comes back at every
  occasion: "Non qui" silences it, so the count measures the app, not how much
  the user answered that day. It is the last column above, so the numbers
  compare. Missed reminders are counted as in ADR-0003: relevant pairs never
  shown.
- **The day runs with the default pause, 2 minutes,** unchanged during the
  day.
- **Reminders with only a time count like the others:** an alert at the wrong
  time is a false alarm, one that never comes is a missed reminder. They do not
  reach the judge, so they are wrong only when the time is read wrong, which
  the cases of [ADR-0020](0020-read-the-time-in-core.md) measure.
- **The delay runs from when the alert became due:** the arrival of its
  context, as in ADR-0003; for a reminder with only a time, the later of its
  instance's start and the arrival of a context. A time that came while the
  user was away rings late by design
  ([#82](https://github.com/devfrx/jiffin/issues/82)), and its waiting does not
  count as delay. This last point is deduced by Claude, from the definition
  of ADR-0003.

**The other thresholds of ADR-0003 stand:** delay p95 ≤ 30 s, missed reminders
≤ 20%, VRAM ≤ 4.0 GiB, RAM ≤ 2 GB, CPU < 5%, battery measured; a day with at
least 4 active hours and about 20 active reminders.

## Consequences

**Positive**

- Thresholds fixed before the numbers, as ADR-0003 wants.
- Counted per pair, the result does not depend on how diligently the user
  answers on the day.

**Negative (accepted)**

- Twice the false alarms of 0.1 are accepted.
- With about 20 reminders the estimate is 12–16 a day, over the target and
  under the cap. It is deduced as in [ADR-0007](0007-single-stage-pipeline.md),
  not measured: 0.094 false alarms per evaluated context with 9 reminders, and
  0.002–0.005 more for each reminder.
- One day is a small sample, as in ADR-0003.

**Follow-up**

- The harness counts false alarms per pair and the delay from when an alert
  became due, with the data of [ADR-0021](0021-one-alert-per-unit.md).
- The acceptance day of 0.2 is a build issue of its own. The acceptance day of
  0.1.0 ([#47](https://github.com/devfrx/jiffin/issues/47)) is a separate
  matter, outside the 0.2 map.
