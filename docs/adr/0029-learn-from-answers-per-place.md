# ADR-0029: Learn from Not here and Remind here, per place, with a threshold per reminder that only goes down

- **Status:** Accepted
- **Date:** 2026-10-07
- **Deciders:** devfrx
- **Sources:** the [0.3 decision map](https://github.com/devfrx/jiffin/issues/119): tickets [#127](https://github.com/devfrx/jiffin/issues/127) (research), [#133](https://github.com/devfrx/jiffin/issues/133) (measured on labelled days), [#128](https://github.com/devfrx/jiffin/issues/128) (decision) and [#126](https://github.com/devfrx/jiffin/issues/126) (how the user says it); amends [ADR-0003](0003-acceptance-thresholds.md), [ADR-0007](0007-single-stage-pipeline.md), [ADR-0013](0013-sqlite-storage.md), [ADR-0014](0014-feedback-data-retention.md), [ADR-0021](0021-one-alert-per-unit.md) and [ADR-0025](0025-kept-quiet-not-missed.md)

## Context

The owner asked to tell Jiffin "qui dovevi avvisarmi" (you should have
reminded me here): Jiffin rings at once, and from then on judges that reminder
better, without retraining the model
([#119](https://github.com/devfrx/jiffin/issues/119); retraining is out of
scope). In 0.2, Not here silences a reminder in one exact context
([ADR-0004](0004-context-identity.md)) until its text changes, and a wrong Not
here goes only by editing the text or deleting the reminder; one threshold,
T = 0.97, holds for every reminder, set by hand, without calibration
([ADR-0007](0007-single-stage-pipeline.md)).
[ADR-0014](0014-feedback-data-retention.md) saved the answers for this, and
warned of its bias: answers come only on alerts that were shown, and a learner
fed with them raises the threshold, trading false alarms for missed reminders
nobody sees.

Ways for a local judge to learn without retraining
([#127](https://github.com/devfrx/jiffin/issues/127)): **A**, an exact "yes,
here" that mirrors Not here, with a threshold per reminder that moves little,
as Gmail's Priority Inbox does; **B**, d − d_cf, against a counterfactual
statement; **C**, notes in the statement; **D**, examples in the question.

Measured on labelled days ([#133](https://github.com/devfrx/jiffin/issues/133),
[#128](https://github.com/devfrx/jiffin/issues/128)): 2026-09-28 (labels
completed: 159 relevant pairs), 2026-10-05 (53) and the sample.

- **The best single threshold moves too much between days:** −1.54 on 09-28,
  0.93 on 10-05, 0.95 in the sample, chosen afterwards. One step down for every
  reminder costs: on 10-05, false alarms from 11 to 17. The gain is in single
  reminders.
- **A threshold moved both ways** rises with Not here, which comes on every
  false alarm, faster than it falls with "qui dovevi", which comes only on the
  missed reminders the user notices. On 10-05 a reminder's threshold rose in
  the first half hour and came back 4–5 hours later: missed pairs from 3 to
  5.4 with half the misses reported.
- **Per scope** (the same app; in a browser, the same host): a Not here per
  scope loses right pairs without showing it (10-05: 1); a "yes" per scope
  stretches a reminder beyond its words (10-05: 5 more wrong pairs for 1
  right).
- **B** worsens the order of the judgements everywhere: AUROC from 0.97–0.99
  to 0.86–0.95.
- **C and D:** a threshold does not carry over from one rewriting to another
  ([ADR-0008](0008-rewrite-conditions-english-statements.md)), and a small
  model improves a prompt badly; examples in the question cost seconds and
  VRAM, and risk the adapter, trained on the exact prompt.

Each day replayed with a simulated owner: Not here on every false alarm, no
Done, "qui dovevi" on a pair the judge missed with probability r; counted what
the judge did on its own; 20 seeds where a choice is random. "Chosen" is the
decision below.

| 2026-09-28 | Missed pairs (of 159) | Missed stretches | False alarms (pairs) | "Qui dovevi" |
|---|---|---|---|---|
| 0.2 | 42 | 193 | 11 | 0 |
| memory only, r = 0.5 | 23.6 | 63.2 | 9.1 | 30.2 |
| memory and a threshold both ways, r = 0.5 | 19.2 | 53.1 | 7.1 | 25.2 |
| **chosen, r = 1** | **14** | **34** | **9** | 34 |
| **chosen, r = 0.5** | **19.2** | **53.1** | **9.1** | 25.2 |
| **chosen, r = 0.25** | **25.4** | **74.3** | **9.5** | 18.6 |

| 2026-10-05 | Missed pairs (of 53) | Missed stretches | False alarms (pairs) | "Qui dovevi" |
|---|---|---|---|---|
| 0.2 | 3 | 3 | 16 | 0 |
| memory and a threshold both ways, r = 0.5 | 5.4 | 8.4 | 12 | 3.8 |
| **chosen, r = 0.5** | **2.8** | **2.8** | **16** | 1 |

The chosen way never misses more than memory alone, and adds no false alarm:
its alerts under T, for a "yes" or a lowered threshold, were 8, 6.3 and 5.4 on
09-28 with r = 1, 0.5 and 0.25, all right; none on 10-05.

## Decision

**Jiffin learns from the answers, not from the model.** For each reminder it
remembers where the user said Not here and where Remind here ("qui dovevi
avvisarmi"); when the "qui dovevi" near the cut repeat, it lowers that
reminder's threshold a little. Never above T: learning may add alerts, which
show, never missed reminders, which would not
([ADR-0003](0003-acceptance-thresholds.md): missed reminders win). Way A, with
one rule more: the threshold only goes down. A technical choice, delegated by
the owner; what the user sees and the new names are the owner's.

**The rules.**

1. **One answer per place.** For each reminder and exact context (app, title,
   address: [ADR-0004](0004-context-identity.md)), Not here says no and Remind
   here says yes; the last one counts. It holds until the reminder's text
   changes, as Not here does in 0.2.
2. **No** is 0.2's Not here: the reminder is silent in that context, and its
   alert does not count in the unit ([ADR-0021](0021-one-alert-per-unit.md)).
3. **Yes:** in that context the reminder counts as true, also under its
   threshold. Its time, Snooze, the occasion and Done still hold.
4. **A reminder's threshold** is T plus an offset between −0.5 and 0: −0.25
   for every two "qui dovevi" near the cut (T − 1 ≤ d < T). Those farther away
   teach only their context: they say the judge errs there, not where to cut.
   The offset is never stored: it is computed again from the answers, counting
   only those given with the engine build in use, since T belongs to the model
   and the prompts and is measured again when they change. After an update
   that changes the build, offsets start again from 0; the answers per place
   stay.
5. **Remind here rings at once**, if that context is still in front: also when
   the reminder already rang in that occasion, was snoozed or out of its time,
   because it is a request. If the context is gone, the yes holds from the next
   time the user is there. The alert is marked as requested: it counts in the
   unit, and it is never the judge's. On a reminder with only a time it just
   rings: there is nothing to learn there.
6. **A wrong step is taken back** with the opposite answer in the same place
   (in 0.2 a wrong Not here could go only with the text or the reminder); from
   the tray list, one place at a time or everything the reminder learned; or by
   changing the text, as in 0.2. The offset is computed again, so each
   withdrawal puts the threshold back exactly as it was. An Undo right after an
   answer is [ADR-0030](0030-undo-and-reopen.md)'s.
7. **What the user sees** (the owner's choice): the alert right after Remind
   here; a few more alerts for a reminder whose threshold went down; and in the
   tray list where it must remind and whether it is more attentive than usual,
   with the way to withdraw them. Never numbers: neither d nor thresholds.
8. **Names in the code** (confirmed by the owner): the command `remind_here`,
   next to `not_here`; the answers per place, `context_answer`; the mark on a
   requested alert, `requested`.

**How the user says it** ([#126](https://github.com/devfrx/jiffin/issues/126);
the look, the key and the words are the owner's choices, from descriptions;
the live trial stays outside the repository).

- **From anywhere, Win+Shift+Q** ("Q" as "qui"), free on the owner's PC on
  2026-10-06; or the row "Qui dovevi avvisarmi" at the top of the tray list,
  under the title and above the state rows: the bell (`EA8F`, Ringer), the
  words, the place under them, the arrow on the right. Two ways to one card,
  like New and Win+Shift+N. If another app holds the key, the row stays.
- **"Here" is the last place Jiffin judged:** the last context stable for 5 s
  ([ADR-0019](0019-five-second-debounce.md)). Jiffin's windows are not places,
  so from the tray list "here" is the window before. The card writes it at the
  top (the window's title; in a browser the site too): a wrong "here" shows.
  With no place yet (Jiffin just started, or only private or full-screen
  windows), it says so and lists nothing.
- **The card (variant A)** opens at the top centre, where alerts come, wide
  and drawn like an alert: the bell in place of its icon, the place in a small
  line, "Qui dovevi avvisarmi di…" in bold, the X. Alerts already on screen
  move down under it, as when a new one comes, and back up when it closes.
- **Under it, the active reminders**, one row each: the action, then the
  condition without its time (or the time, for a reminder with only a time),
  and after a dot what else kept it quiet there: "Taciuto qui", "Già suonato",
  "Rimandato", "Fuori orario", "Periodo finito". First the judged ones, the
  closest to ringing in that place first; then those with only a time, the
  newest first. Never numbers. It grows up to the work area, then scrolls.
- **It takes the focus**, unlike alerts, since the user asked for it: Up and
  Down move, Enter or Space choose, Esc, the X or a click outside close it.
  Closed, Windows gives the focus back to the app before.
- **A click on a reminder** is Remind here: the card closes, the alert comes
  at once at the top like any other, marked as requested, and Jiffin learns. A
  mistake is withdrawn with Not here on that alert, or from the tray list.
- **In the tray list**, under each active reminder that learned something, a
  line after the others: "Taciuto in 2 posti" (replacing 0.2's state line),
  "Chiesto in 2 posti" and "Più attento" when its threshold went down,
  separated by a dot, with the arrow down. A click opens the places inside the
  row, as Delete's question does: each with its icon (the bell for "Chiesto",
  the struck bell `E7ED` for "Taciuto"), its title and an X that forgets it;
  then "Dimentica tutto". A forgotten place is as if never answered: the
  threshold is computed again.
- `core` gives, for a place, the active reminders with their last outcome
  there and their order; for a reminder, the places of its answers and whether
  its threshold went down.
- Rejected variants: B, at the centre like "Nuovo promemoria", with a Cancel
  button; C, at the bottom right like the tray list.

**Data**, in migration 0003 ([ADR-0013](0013-sqlite-storage.md)):

- **The table `context_answer` takes the place of `silence`**, with a row for
  every answer and every withdrawal: reminder, context, which, d, build, when.
  A change of text is a withdrawal of everything, as in 0.2. The last row of
  each pair counts; the earlier ones serve the replay, which in 0.2 derived the
  Not here from the final state and would lose the withdrawals.
- The rows of `silence` become Not here, with the d, the build and the time of
  their alert.
- `alert` takes `requested`.
- Kept as Not here is in 0.2: until the reminder is deleted
  ([ADR-0014](0014-feedback-data-retention.md)).

**The harness** ([ADR-0017](0017-evaluation-harness-subpackage.md)): `replay`
puts the answers back at their time and computes the offsets as `core` does;
`replay --threshold` moves T, and the offsets stay relative to T. A requested
alert never counts as the judge's: its pair stays missed if it does not ring
by itself later. The alerts that ring later for a yes, or under T for a
lowered threshold, count as shown, and the report shows them apart, like the
pairs kept quiet of [ADR-0025](0025-kept-quiet-not-missed.md). The simulated
owner stays outside the repository.

**Rejected.**

- **A threshold that moves both ways:** it rises with Not here faster than it
  falls with "qui dovevi"; on 10-05 it missed more.
- **Per scope:** silent losses one way, reminders stretched beyond their words
  the other.
- **B:** worse ordering everywhere.
- **C and D in 0.3:** they reopen only if the acceptance of 0.3 shows misses
  of meaning, which neither come back to the same context nor sit near the cut.
- **A lower floor:** down to −1 misses a little less on 09-28 (19.2 to 18.1),
  but in the sample a reminder lowered by 1 would take 32 wrong pairs for 7
  right; by 0.5, 9 for 5.
- **Raising a lowered threshold again with Not here on alerts under T:** the
  same numbers on these days, where no alert under T was wrong, and the same
  bias inside the band. It is the correction ready if the acceptance of 0.3
  shows lowered reminders ringing wrong in always new contexts.

**What this amends.**

- [ADR-0007](0007-single-stage-pipeline.md): a threshold per reminder,
  between T − 0.5 and T; still no calibration.
- [ADR-0014](0014-feedback-data-retention.md): Remind here, the answers per
  place and their retention; the button the record left for later.
- [ADR-0021](0021-one-alert-per-unit.md): the answers, their withdrawal, and
  the requested alert.
- [ADR-0003](0003-acceptance-thresholds.md) and
  [ADR-0025](0025-kept-quiet-not-missed.md): how requested alerts and those
  under T count.
- [ADR-0013](0013-sqlite-storage.md): `context_answer` instead of `silence`,
  deleted with the reminder; `alert.requested`.

## Consequences

**Positive**

- On the labelled days, fewer missed pairs (09-28: 42 to 19.2 with half the
  misses reported) and no false alarm more.
- The model, its prompts and T are untouched, so the measures of the judge
  hold.
- Every step can be taken back exactly, from the place where it was taken or
  from the tray list.

**Negative (accepted)**

- It learns only what the user reports: misses nobody notices stay missed,
  which is why the acceptance labels every pair.
- False alarms fall only one context at a time, through Not here, as in 0.2.
- An update that changes the engine's build resets every offset.
- A second global key, which another app may already hold.

**Follow-up**

- The acceptance day of 0.3 counts requested alerts as the owner's labels
  ([ADR-0031](0031-acceptance-thresholds-v0-3.md)).
- When this is built, `docs/design/` follows: `pipeline.md` (the threshold per
  reminder), `lifecycles.md` (Remind here and withdrawals), `data-model.md`,
  `harness.md`, `overlay.md` (the card, and alerts moving down), `tray.md` (the
  row at the top and the places) and `creation.md` (the two keys).
