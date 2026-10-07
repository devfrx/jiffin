# ADR-0031: Accept version 0.3 with the thresholds of 0.2, plus the engine's sleep and its late wakes

- **Status:** Accepted
- **Date:** 2026-10-07
- **Deciders:** devfrx
- **Sources:** the [0.3 decision map](https://github.com/devfrx/jiffin/issues/119): ticket [#139](https://github.com/devfrx/jiffin/issues/139) (thresholds and how they are counted), with [#121](https://github.com/devfrx/jiffin/issues/121) (the monitor) and the report of [#106](https://github.com/devfrx/jiffin/issues/106); amends [ADR-0003](0003-acceptance-thresholds.md), [ADR-0017](0017-evaluation-harness-subpackage.md) and [ADR-0022](0022-acceptance-thresholds-v0-2.md)

## Context

Each version is accepted on a real working day, against thresholds fixed
before the numbers ([ADR-0003](0003-acceptance-thresholds.md)). Version 0.2
passed with the thresholds of [ADR-0022](0022-acceptance-thresholds-v0-2.md)
and the count of [ADR-0025](0025-kept-quiet-not-missed.md)
([#106](https://github.com/devfrx/jiffin/issues/106); delay p95 5.4 s).
Version 0.3 changes three things that day measures:

- **learning from the answers** ([ADR-0029](0029-learn-from-answers-per-place.md)):
  requested alerts, and alerts under T for a lowered threshold;
- **the GPU set free** ([ADR-0027](0027-light-sleep-of-the-engine.md)): the
  engine should sleep, and wake inside the 5 s;
- **the situations** ([ADR-0028](0028-read-the-situations-in-core.md)):
  reminders without a remainder are right when the situation is read right,
  and the end of a call could not be tried
  ([#134](https://github.com/devfrx/jiffin/issues/134)).

The harness's monitor reads the VRAM through `nvidia-smi` every 5 s, which
wakes the card; Windows' performance counters, read once a second, do not
([#121](https://github.com/devfrx/jiffin/issues/121)).

## Decision

**The thresholds of 0.3.** The owner chose them: four questions, the
recommended option each time; the other thresholds of 0.2 stay.

| Measure | Threshold | From |
|---|---|---|
| Delay from when the alert was due, p95 | ≤ 30 s | ADR-0003, ADR-0022 |
| Missed: relevant pairs never shown, except those kept quiet as already reminded | ≤ 20% | ADR-0003, ADR-0025 |
| False alarms in the day, once per pair | target ≤ 10, cap 20 | ADR-0022 |
| Dedicated VRAM of the app and the engine, at peak | ≤ 4.0 GiB | ADR-0003, ADR-0027 |
| RAM of the app and the engine | ≤ 2 GB | ADR-0003 |
| Average CPU of the app and the engine | < 5% | ADR-0003 |
| Battery | measured and reported, no threshold | ADR-0003 |
| **Late wakes:** the engine ready after the 5 s of the context waiting for it | **at most 1 in the day, by at most 2 s** | new |
| **Sleep:** the engine sleeps every time the rule of ADR-0027 asks, and asleep holds at most 0.2 GiB of dedicated VRAM | **every time** | new |

- **The day stays 0.2's:** at least 4 active hours; about 20 active
  reminders, the real ones plus invented ones through the replay, as the owner
  chose for 0.2; the default return pause, 2 minutes; every pair labelled, and
  a blind share by the owner.
- **The situations have no threshold of their own:** their alerts count in
  the missed reminders and the false alarms, with the truth given by the owner
  (below).
- Missed reminders still win over false alarms, and a threshold missed
  reopens its decision instead of being widened in silence (ADR-0003).

**The owner's choices**
([#139](https://github.com/devfrx/jiffin/issues/139)):

1. **Late wakes: "at most one, by little".** A slow disk by chance does not
   fail 0.3; many slow wakes do. "None" was rejected: one slow wake, even
   because of another app, would have failed the version.
2. **The GPU set free: "with a threshold".** "Only counted" was rejected: 0.3
   would have passed with an engine that never sleeps.
3. **Calls and absences: the owner checks them at the end of the day**, in
   about 5 minutes. "Nobody" was rejected: the situations would have stayed
   unverified.
4. **Without a call, 0.3 passes all the same** on the rest, and the end of a
   call is checked at the first real one. "Wait for a call" was rejected: the
   day would have stayed open for an event that cannot be prepared
   ([#134](https://github.com/devfrx/jiffin/issues/134)).

**How they are counted** (a technical choice, told to the owner).

*Wakes and delay.*

- The engine's sleeps and wakes are recorded by the app
  ([ADR-0027](0027-light-sleep-of-the-engine.md)): when, why, and when the
  model was ready after the warm-up judgement. The harness reads them from the
  copy.
- **A wake is late** when the first evaluation waiting for it starts after
  the end of its 5 s of stable context; its delay is how long it waited
  beyond. Under ADR-0027 it should not happen: the wake starts when the context
  arrives, and ends in 2.6–4.2 s (deduced from #121's times).
- **A wake asked by a statement to write** delays no alert: it is reported
  apart (how many, and how long the window waited), without a threshold.
- **The delay of alerts** stays ADR-0022's, from when the alert was due. For a
  reminder with a situation, from when the situation made it due (the start of
  a stretch, an end, the start + N), the 5 s included, as for a context
  ([ADR-0028](0028-read-the-situations-in-core.md)).
- Reported: how many wakes, their time (min · median · max), the evaluations
  that waited.

*Sleep.*

- **The monitor reads each process's VRAM from Windows' performance counters
  (PDH)**, as #121 did, instead of `nvidia-smi`, which wakes the card. Its row
  stays every 5 s. The 4.0 GiB threshold holds on the dedicated VRAM of the app
  and the engine together; shared memory is reported apart.
- **The engine must sleep** under ADR-0027's rule: within 5 minutes and 10 s
  of `core`'s last request (a judgement or a statement), and within 10 s of
  nothing being in front (Pause, a locked screen, the PC asleep, full screen, a
  private window or one of Jiffin's). Each time it does not is an error, and
  the threshold is zero errors.
- **Asleep**, the engine holds at most 0.2 GiB of dedicated VRAM in every row
  of the monitor, after its first 10 s of sleep (measured: 101 MiB, #121).
- Reported: the time asleep over the time Jiffin was on, the wakes, the peak
  of the VRAM awake.

*Learning* ([ADR-0029](0029-learn-from-answers-per-place.md)).

- A requested alert is never the judge's, and its pair stays missed if it
  does not ring by itself later. Alerts for a yes, or under T for a lowered
  threshold, count as shown, and the report shows them apart, like the pairs
  kept quiet of ADR-0025.
- **"Qui dovevi avvisarmi" is the owner's label:** its pair is relevant. The
  harness's rule holds: where the owner labelled, that label counts
  (`docs/design/harness.md`).

*Situations* ([ADR-0028](0028-read-the-situations-in-core.md)).

- **Reminders without a remainder** (only a time, only situations, or both)
  count like the others, as ADR-0022 says for those with only a time: an alert
  on a situation read wrong is a false alarm, one that does not come on a true
  situation is a missed reminder. For them the pair is (reminder, stretch of
  the situation). The report shows them apart, as 0.2's report did for those
  with only a time.
- **The owner gives the truth.** At the end of the day a page of the report
  lists the calls (app, start, end) and the absences, with the apps in front
  before and after. The owner marks the wrong ones (they did not happen, are
  split, or start or end more than a minute from the true time) and adds the
  missing ones. The page closes with "Controllato": only then do the unmarked
  ones count as right. About 5 minutes.
- **The replay with 20 reminders** uses invented reminders with situations
  too: the file of invented reminders gets some on calls and absences, among
  the first, so they are there at 20.
- **The 5 s and the 3 minutes.** A call split by mute or a waiting room says
  5 s are not enough; an absence marked wrong while the owner was reading says
  3 minutes are too few. Each wrong stretch opens an issue for its number,
  even when the day passes.
- **Without a call in the day**, the call's line of the report says "not
  verified", and the acceptance day opens an issue that verifies it, with the
  same check, at the first real call.

*The threshold T, a rule written before the replay.*

- **As in 0.2:** T = 0.97 stays if missed reminders are ≤ 20% and false alarms
  ≤ 10; otherwise, the threshold with the fewest false alarms among those with
  missed reminders ≤ 20%. The grid is fixed before the replay. Moving T moves
  the reminders' thresholds too, which stay relative to T (ADR-0029).
- **A bug in the contexts:** pairs on contexts spoiled by a known bug are
  counted with and without them. If the two counts give different T, the
  owner decides on both, as for
  [#135](https://github.com/devfrx/jiffin/issues/135) in 0.2.
- **The replay judges the invented reminders at several thresholds at once**,
  from the stored scores: `replay --reminders` judged only at `core`'s
  threshold, and 0.2 needed a script outside the repository
  ([#106](https://github.com/devfrx/jiffin/issues/106)).

**Before the day**, the harness needs: the monitor on the performance
counters; the sleeps and wakes; the situations in `snapshot` and `replay`,
and the page of calls and absences; "qui dovevi avvisarmi" as a label; the
replay at several thresholds; the invented reminders with situations.

**What this amends.**

- [ADR-0022](0022-acceptance-thresholds-v0-2.md): the thresholds of 0.3.
- [ADR-0003](0003-acceptance-thresholds.md): the VRAM is the dedicated memory
  of each process, from Windows' performance counters, not from `nvidia-smi`.
- [ADR-0017](0017-evaluation-harness-subpackage.md): the monitor and the new
  counts. How requested alerts count belongs to
  [ADR-0029](0029-learn-from-answers-per-place.md); the situations in the
  harness to [ADR-0028](0028-read-the-situations-in-core.md).

## Consequences

**Positive**

- Thresholds fixed before the numbers, as ADR-0003 wants, for the two new
  promises of 0.3: the GPU set free, and no alert later than in 0.2.
- The monitor no longer wakes the card it measures.
- The situations are checked against the owner's truth, in minutes.

**Negative (accepted)**

- A day without a call leaves the end of a call to a later check.
- The owner spends about 5 more minutes at the end of the day.
- One day is a small sample, as in ADR-0003.

**Follow-up**

- The acceptance day of 0.3 is a build issue of its own, measured with this
  method.
- When the harness is built, `docs/design/harness.md` follows: the monitor,
  the new rows of the report, the page of calls and absences, "qui dovevi
  avvisarmi" as a label.
