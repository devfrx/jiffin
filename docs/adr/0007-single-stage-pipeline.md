# ADR-0007: Judge every active reminder in one stage, without retrieval

- **Status:** Accepted; amended by [ADR-0019](0019-five-second-debounce.md) (the debounce is 5 s) and [ADR-0029](0029-learn-from-answers-per-place.md) (a threshold per reminder, between T − 0.5 and T)
- **Date:** 2026-09-29
- **Deciders:** devfrx
- **Sources:** tickets [#14](https://github.com/devfrx/jiffin/issues/14) (pipeline), [#13](https://github.com/devfrx/jiffin/issues/13), [#18](https://github.com/devfrx/jiffin/issues/18) and [#24](https://github.com/devfrx/jiffin/issues/24) (measurements), [#16](https://github.com/devfrx/jiffin/issues/16) (cost with 20 reminders)

## Context

The first design had two stages: an embedding retrieval picking the top k
reminders by similarity to the context, then a verifier on those k. The point
was to make the cost and the worst-case false alarms of an event independent of
the number of reminders. Its known risk: the top k can drop relevant reminders
in silence, an error nobody sees.

With the chosen judge ([ADR-0006](0006-judge-rizzo-flow-q4.md)), share of
relevant pairs taken with at most 0.1, 0.13 and 0.2 false alarms per evaluated
context:

| Retrieval | ≤ 0.1 | ≤ 0.13 | ≤ 0.2 |
|---|---|---|---|
| harrier-oss-v1-270m, top 5 | 0.75 | 0.80 | 0.82 |
| harrier-oss-v1-270m, top 7 | 0.80 | 0.85 | 0.89 |
| **None: all 9 reminders** | **0.81** | **0.88** | **0.91** |
| Character n-grams, top 5 | 0.59 | 0.64 | 0.65 |
| harrier + n-grams (RRF), top 5 | 0.72 | 0.78 | 0.80 |

The retrieval lost more than it filtered: outside harrier's top 5 there were
18 relevant and 406 non-relevant pairs, and at the starting threshold the judge
took 12 of the former while erring on 1 of the latter.

## Decision

**Pipeline:** context change → 5 s debounce → pair cache → the judge scores
all active reminders in one call → hand-set threshold on d → alert and
feedback.

- **No retrieval and no embedding model** in the first version.
- **Debounce: 5 s** ([ADR-0019](0019-five-second-debounce.md)). It was 20 s,
  to fit the p95 ≤ 30 s delay ([ADR-0003](0003-acceptance-thresholds.md))
  with half the evaluations (37 instead of 72 on the real day); the owner
  found the wait too long on the installed app.
- **Threshold on d, set by hand.** The starting value is d ≈ 0.97, the highest
  with recall ≥ 0.80 on the sample (0.094 false alarms per evaluated context).
  The final value is fixed on the acceptance day, after the rewriting prompt is
  fixed ([ADR-0008](0008-rewrite-conditions-english-statements.md)), with the
  rule of [ADR-0003](0003-acceptance-thresholds.md): first missed reminders
  under 20%, then false alarms under the cap. It is a constant in the code next
  to the model and prompt versions, not a user setting, and every evaluation
  records it ([ADR-0013](0013-sqlite-storage.md)).
- **No calibration.** A temperature, or any increasing transform of d, does not
  change which pairs pass a threshold; it only makes the number readable as a
  probability. Calibration comes back with learning from feedback, after the
  first version.
- **Fallback:** if the acceptance day shows too many false alarms with many
  reminders, the first stage returns: harrier-oss-v1-270m on the CPU, in fp32,
  keeping the top 5–7 candidates. It is already measured.

**Estimated costs.**

- Delay: about 28 ms per extra reminder. With 20 reminders one evaluation
  takes about 0.5 s (498 / 508 ms p50 / p95, measured with the engine settings
  of [ADR-0011](0011-engine-child-process-json-rpc.md)).
- False alarms: with 9 reminders the starting threshold gives 0.094 per
  evaluated context on the sample. The real day doubled the sample's rate, so
  about 0.19 × 38 evaluations ≈ 7 per day. Each extra reminder adds 0.002–0.005
  per evaluated context on the sample; with the same doubling, 20 reminders
  give 9–11 per day: at the cap.
- Memory: no PyTorch and no embedding model. In fp32, harrier's weights alone
  would take about 1.1 GB of the 2 GB RAM budget.

## Consequences

**Positive**

- No silent losses from a retrieval stage.
- One model and one runtime.

**Negative (accepted)**

- Cost and false alarms grow with the number of active reminders.
- The false-alarm estimate for 20 reminders sits at the cap.
- One stage against two with 20 reminders is not measured; the sample has 9.

**Follow-up**

- The harness measures false alarms as the reminders grow
  (`replay --reminders 20,40,80`,
  [ADR-0017](0017-evaluation-harness-subpackage.md)).
- Completed reminders disappear, which keeps the active set small.
- **The threshold stays at 0.97**, the owner's choice on the acceptance day of
  0.2 ([#106](https://github.com/devfrx/jiffin/issues/106)). The day replayed
  with 20 reminders gives 11 false alarms, over the target of 10 and under the
  cap of 20 of [ADR-0022](0022-acceptance-thresholds-v0-2.md), and 6% missed;
  3 of those false alarms come from browser contexts with the address of a
  page shown before ([#135](https://github.com/devfrx/jiffin/issues/135)),
  without which they are 8. At 1.25 they would be 6, with 17% missed.
