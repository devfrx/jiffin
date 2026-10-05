# ADR-0025: Leave the pairs kept quiet as already reminded out of the missed reminders

- **Status:** Accepted
- **Date:** 2026-10-05
- **Deciders:** devfrx
- **Sources:** ticket [#104](https://github.com/devfrx/jiffin/issues/104) (the harness of 0.2), with the captured day of 2026-09-28 and the labels of [#86](https://github.com/devfrx/jiffin/issues/86); amends [ADR-0003](0003-acceptance-thresholds.md) and [ADR-0022](0022-acceptance-thresholds-v0-2.md)

## Context

[ADR-0003](0003-acceptance-thresholds.md) counts as missed every relevant
(evaluated context, reminder) pair never shown, at most 20% of the relevant
pairs, because "a missed reminder is never seen at all".
[ADR-0022](0022-acceptance-thresholds-v0-2.md) kept that count for 0.2.

In 0.2 a reminder rings once per occasion
([ADR-0021](0021-one-alert-per-unit.md)): true in two windows of the same
occasion, it rings in the first, and the pair of the second is kept quiet. By
the letter of ADR-0003 that pair is missed, though the reminder reached the
user earlier in that occasion. The once-an-hour rule of 0.1 did the same.

The captured day of 2026-09-28, converted through the `core` of 0.2 with the
default pause, with the labels of #86 (73 of the day's 621 pairs, all over
the threshold): 60 relevant pairs, 27 never shown, all 27 kept quiet by the
same occasion. 45% missed, against at most 20%, though each of those
reminders had reached the screen earlier in its occasion.

- **A — count as missed only the pairs not kept quiet as already reminded:**
  the share measures what ADR-0003 calls a missed reminder; the pairs kept
  quiet are counted apart, so they stay in view.
- **B — keep the letter:** the share would measure the rule that rings once
  per occasion, not the judge or the screen, and the acceptance day of 0.2
  would fail by design.

## Decision

**A relevant pair never shown is a missed reminder, unless it was kept quiet
as already reminded:** its reminder had rung in the same unit (the occasion,
the instance of its time, or in 0.1 the hour), or the user had answered it,
with Rimanda or with "Non qui" in that context. The owner's choice, while
#104 was built.

- Why a pair was never shown comes, as before, from the candidate that came
  closest to an alert. "Same occasion", "held back", "snoozed" and "silenced"
  keep it quiet; "waited" (its alert never reached the screen) and "below
  threshold" make it missed.
- The share keeps all relevant pairs as its base, and its threshold stays at
  most 20%. The pairs kept quiet are counted apart, by why, in the summary and
  on the report's page.
- The harness counts days of 0.1 the same way.

## Consequences

**Positive**

- The share measures the judge and the screen: on the captured day, 0 of 60
  missed instead of 27.
- The pairs kept quiet stay visible with their reason: a unit that keeps too
  much quiet still shows.

**Negative (accepted)**

- The count trusts the unit: a pair kept quiet by a long occasion is never
  missed, even if the user would have wanted the reminder again there. The
  acceptance day keeps the default pause
  ([ADR-0022](0022-acceptance-thresholds-v0-2.md)).
- A pair kept quiet by an alert that waited for a place and never reached the
  screen counts as reminded; only that alert's own pair is missed. An alert
  waits only behind three others on screen.
- The 0 of 60 says nothing of the pairs under the threshold, which #86 did
  not label: the acceptance day labels every pair (ADR-0003).

**Follow-up**

- The harness counts this way from #104, and the acceptance day of 0.2
  ([#106](https://github.com/devfrx/jiffin/issues/106)) is measured with it.
