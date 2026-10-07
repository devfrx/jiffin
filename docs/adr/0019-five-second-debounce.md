# ADR-0019: Evaluate a context after 5 s in the foreground

- **Status:** Accepted; amended by [ADR-0027](0027-light-sleep-of-the-engine.md) (the 5 s also hide the engine's reload) and [ADR-0028](0028-read-the-situations-in-core.md) (a change of situation counts after 5 s too)
- **Date:** 2026-10-02
- **Deciders:** devfrx
- **Sources:** the owner's first use of the installed app ([#45](https://github.com/devfrx/jiffin/issues/45)), with the captured day of 2026-09-28 replayed by the harness; amends [ADR-0007](0007-single-stage-pipeline.md)

## Context

[ADR-0007](0007-single-stage-pipeline.md) set a 20 s debounce: a context is
judged once it has stayed in the foreground for 20 s. It fits the delay
threshold of [ADR-0003](0003-acceptance-thresholds.md), p95 ≤ 30 s, and it
judges about half the contexts a 5 s debounce would.

On 2026-10-02 the owner used the installed app for the first time, with three
reminders. Each of the three alerts came 20.0–20.4 s after its window came to
the foreground, and all three were right. The capture sees a change at once,
through WinEvent hooks ([ADR-0005](0005-browser-address-ui-automation.md)),
and the judge answered in about 0.3 s: the whole wait was the debounce. The
owner found it too long.

The captured day of 2026-09-28, replayed through `core` by the harness:

| Debounce | Evaluations | Contexts evaluated |
|---|---|---|
| 20 s | 116 | 36 |
| 10 s | 165 | 48 |
| **5 s** | **234** | **69** |

The owner chose 5 s over 10 s.

## Decision

**A context is evaluated once it has been stable for 5 s.** The rest of
ADR-0007 stands: the pair cache, one judging call for all the active
reminders, the threshold on d.

## Consequences

**Positive**

- An alert comes about 5 s after the window it is about comes to the front.
- The delay threshold of ADR-0003 holds with a wide margin.

**Negative (accepted)**

- About twice the contexts are judged, windows seen for a few seconds among
  them; each judgement takes 0.3–0.5 s of GPU
  ([ADR-0007](0007-single-stage-pipeline.md)).
- False alarms may grow with the contexts judged. ADR-0007 estimated about 7 a
  day with 9 reminders and 9–11 with 20, against the cap of 10 of ADR-0003; at
  the same rate per context, 69 contexts instead of 36 would give about 13 and
  17–21.

**Follow-up**

- The acceptance day ([#47](https://github.com/devfrx/jiffin/issues/47))
  measures the false alarms with this debounce. Over the cap, the rule of
  ADR-0003 comes first (missed reminders under 20%); if the threshold cannot
  bring them back under the cap, the debounce is reopened.
- One request at a time ([ADR-0011](0011-engine-child-process-json-rpc.md))
  and one worker ([ADR-0012](0012-package-structure-ports.md)) still cost
  nothing: a context is judged after 5 s in front, and a judgement takes at
  most about 0.5 s.
