# Lifecycles of reminders and alerts

The states a reminder and an alert go through, in `jiffin.core`. The code is
`core/reminders.py` and `core/alerts.py`; the rules come from decision tickets
[#12](https://github.com/devfrx/jiffin/issues/12) and
[#6](https://github.com/devfrx/jiffin/issues/6), and from
[ADR-0014](../adr/0014-feedback-data-retention.md).

## Reminder

```mermaid
stateDiagram-v2
    [*] --> Active : create
    state Active {
        [*] --> Ready
        Ready --> Snoozed : Rimanda
        Snoozed --> Returning : the snooze ends
        Returning --> Ready : it alerts
        Returning --> Snoozed : Rimanda on an older alert
    }
    Active --> Completed : Fatto, or Completa in the tray list
    Active --> [*] : Elimina
    Completed --> [*] : Elimina
```

- **Ready**: in a context judged true it alerts, at most once an hour.
- **Snoozed**: it is judged, and keeps quiet. Rimanda lasts 15 minutes, an
  hour, or until "domani": 08:00 of the next day, local time, or of the same day
  when snoozed before 04:00.
- **Returning**: the once-an-hour rule does not apply. If the context is stable
  when the snooze ends, it is judged there at once; otherwise the next context
  judged true brings the alert back.
- **Editing** the text, in any active state, makes a new revision: the
  silences of "Non qui" go, and the reminder is not judged until the engine has
  written the new statement.
- **Non qui** silences one context and changes no state.
- **Completed** reminders are no longer judged, and their open alerts go.
  **Elimina** removes the reminder and everything about it.

## Alert

```mermaid
stateDiagram-v2
    [*] --> Waiting : a reminder alerts
    Waiting --> Visible : a place on screen is free, at most 3
    Visible --> Unseen : 10 s without an answer
    Unseen --> Unseen : seen in the tray list
    Visible --> Answered : Fatto, Utile, Non qui, Rimanda
    Unseen --> Answered : an answer from the tray list
    Answered --> [*]
    Waiting --> [*] : its reminder is completed or deleted
    Visible --> [*] : its reminder is completed or deleted
    Unseen --> [*] : its reminder is completed or deleted
```

- An alert waits only when three are already on screen; the tray dot shows
  while one waits, or while one vanished unanswered and the tray list has not
  shown it yet.
- Unseen alerts sit on top of the tray list, newest first.
- The record keeps when the alert appeared, vanished, was seen and answered,
  and the answer: `fatto`, `utile`, `rimanda` or `non_qui`.
