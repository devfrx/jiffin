# ADR-0003: Accept the first version on a real working day, against fixed thresholds

- **Status:** Accepted; amended by [ADR-0022](0022-acceptance-thresholds-v0-2.md) (from 0.2, false alarms counted once per pair, target 10 and cap 20)
- **Date:** 2026-09-29
- **Deciders:** devfrx
- **Sources:** tickets [#9](https://github.com/devfrx/jiffin/issues/9) (thresholds) and [#18](https://github.com/devfrx/jiffin/issues/18) (estimate on a real day)

## Context

The first version is done when it is installed on the owner's machine and its
delay, missed reminders and false alarms are measured on a real working day,
within thresholds fixed in advance. Without thresholds fixed beforehand,
"good enough" would be decided after seeing the numbers.

The evidence so far comes from a sample of 106 real contexts and 9 reminders,
labelled with LLM assistance, and from one captured working day (2026-09-28,
4.6 active hours). On that day a 20 s debounce with the pair cache gave 38
evaluations (8.3 per hour). At the threshold that gives 0.2 false alarms per
evaluation on the sample, Rizzo Flow (then in Q8_0) raised 74 alerts, 15 of
them wrong: 0.39 per evaluation, twice the sample. The owner judged 30 alerts
blind and agreed with the LLM-assisted labels on 26; in the 4 disagreements the
labels said "right" and the owner "wrong".

## Decision

The first version must meet these thresholds on a real working day with at
least 4 active hours and about 20 active reminders:

| Measure | Threshold |
|---|---|
| Delay from the context change to the alert | p95 ≤ 30 s |
| Missed reminders: relevant (evaluated context, reminder) pairs never shown | ≤ 20% |
| False alarms per working day | target ≤ 5, cap 10 |
| VRAM of the whole app, as `nvidia-smi` reports it | ≤ 4.0 GiB |
| RAM of all the app's processes | ≤ 2 GB |
| CPU, average over the day, including the extra CPU browsers spend on accessibility ([ADR-0005](0005-browser-address-ui-automation.md)) | < 5% |
| Battery | measured and reported, no threshold |

**When missed reminders and false alarms conflict, missed reminders win.** The
decision threshold is set to stay under 20% missed; false alarms may go over
the target of 5, never over the cap of 10. A false alarm is seen and
dismissed; a missed reminder is never seen at all.

Only the p95 of the delay has a threshold: the median is set by the debounce
([ADR-0007](0007-single-stage-pipeline.md)).

**How it is measured.**

- The app logs every evaluated context, every score, every alert and the delay
  of each event ([ADR-0014](0014-feedback-data-retention.md)).
- After the day, every (evaluated context, reminder) pair is labelled with LLM
  assistance, not only the alerts, and the owner reviews a share of the
  labels, as on 2026-09-28. The app has no "you should have told me" button.
- VRAM, RAM and CPU (browsers included) are sampled during the day. If part of
  the day runs on battery, consumption is compared with and without the app.
- The evaluation harness does the measuring
  ([ADR-0017](0017-evaluation-harness-subpackage.md)).

If a threshold cannot be met, the decision is reopened explicitly, not relaxed
in silence.

## Consequences

**Positive**

- A definition of done fixed before the numbers exist.
- Concrete targets for the harness and for every later change of model,
  prompt or llama.cpp build.

**Negative (accepted)**

- One day is a small sample.
- LLM-assisted labels may agree with an LLM judge more than the owner would;
  the owner's review of a share of them is the check.
- The false-alarm estimate for 20 reminders, 9–11 per day, is already at the
  cap ([ADR-0007](0007-single-stage-pipeline.md)).

**Follow-up**

- The decision threshold on the model's score is fixed on this day
  ([ADR-0007](0007-single-stage-pipeline.md)), after the rewriting prompt is
  fixed ([ADR-0008](0008-rewrite-conditions-english-statements.md)).
- These thresholds excluded Rizzo Flow in Q8_0 (5.7 GiB of VRAM)
  ([ADR-0006](0006-judge-rizzo-flow-q4.md)).
