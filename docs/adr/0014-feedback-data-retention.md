# ADR-0014: Keep evaluations for 30 days and answered alerts until the reminder is deleted

- **Status:** Accepted
- **Date:** 2026-09-29
- **Deciders:** devfrx
- **Sources:** tickets [#15](https://github.com/devfrx/jiffin/issues/15) (feedback data), [#6](https://github.com/devfrx/jiffin/issues/6) (scope) and [#12](https://github.com/devfrx/jiffin/issues/12) (alert behaviour)

## Context

The first version does not learn from feedback: the threshold is set by hand,
and learning comes later. It saves the feedback so that the data exists then.

Feedback only ever arrives on alerts that were shown, never on reminders that
were missed. A learner fed only with shown alerts tends to raise the threshold:
fewer false alarms, more missed reminders, and nobody sees the latter. The log
of evaluations, meanwhile, is a record of the user's contexts: personal data.

Options considered:

- **Save only the alerts:** missed reminders could never be found again, and a
  future learner would raise the threshold blindly.
- **Keep everything for 30 days, answers included:** few examples left by the
  time learning arrives.
- **Encrypt with a key tied to the Windows account:** one more dependency, data
  lost if an administrator resets the password, and no protection against a
  program running as the user, which can use the same key.

## Decision

**Every evaluation is saved, not only the alerts.** An evaluation is what
happens when a context stays stable for the debounce. For each one:

- when the context changed and when the decision came, which give the delay;
- the normalized context ([ADR-0004](0004-context-identity.md));
- whether each score came from the cache;
- for every active reminder judged: the revision the model saw, `d`, the
  threshold in use, and the outcome — alert, below threshold, silenced by
  "not here", held back by the once-an-hour rule, snoozed;
- the engine build: model, prompts and llama.cpp versions.

The original design also stored each candidate's similarity, retrieval rank and
embedding model; those fields went away with the retrieval stage
([ADR-0007](0007-single-stage-pipeline.md)).

**For every alert:** when it appeared; if it vanished unanswered, when it was
seen in the tray list; the answer and when it came — Fatto (done), Utile
(useful), Non qui (not here), Rimanda (snooze: 15 minutes, 1 hour, tomorrow),
closed, or vanished after 10 s.

**Revisions.** Every change to a reminder's text creates a new revision, and
every event points to the revision the model saw, so a label stays tied to the
text that was judged.

**What each answer means**, for learning after the first version:

- Fatto, Utile, Rimanda: relevant. Snooze means "right, but not now": the alert
  comes back only when the context is right again.
- Non qui: not relevant in that context.
- Closed, or vanished unanswered: no label.

**Missed reminders.** No new button in the first version. They are found later
in the evaluation log, where the below-threshold reminders are recorded with
their score and the context the model saw, and labelled as on the acceptance
day ([ADR-0003](0003-acceptance-thresholds.md)).

**Retention.**

| Data | Kept |
|---|---|
| Evaluations: contexts, judged reminders, scores | 30 days |
| Cache entries | 30 days after last use |
| Alerts with an answer, context included | until the reminder is deleted, also after it is completed |
| Alerts without an answer | 30 days |
| "Not here" | until the reminder is deleted |

**Deleting a reminder deletes everything about it:** revisions, alerts,
answers, log rows, cache entries and silences. Completing it only hides it.

**Protection on disk.** The data lives under `%LOCALAPPDATA%`, which OneDrive
does not sync and roaming profiles do not carry, with the default per-user
permissions. The target machine's system disk is already encrypted by Windows
(BitLocker, verified active on C:). No extra encryption. As with all personal
data, nothing reaches the repository or the issues, and there is no telemetry
([ADR-0001](0001-keep-data-and-inference-local.md)).

A day like 2026-09-28 (37–38 evaluations in 4.6 hours) adds under a thousand
rows even with 20 reminders: space is not a concern; privacy is, and the
30 days handle it.

## Consequences

**Positive**

- Missed reminders can be found and measured.
- Labelled examples accumulate for learning later.
- Deletion is real ([ADR-0013](0013-sqlite-storage.md)).

**Negative (accepted)**

- Answered alerts keep their context for as long as the reminder exists.
- No protection beyond the Windows account and the disk encryption.

**Follow-up**

- A "Doveva avvisarmi qui" (should have alerted me here) button may come with
  learning, after the first version.
