# ADR-0023: Close every window with an X, and drag every window but the alerts

- **Status:** Accepted
- **Date:** 2026-10-03
- **Deciders:** devfrx
- **Sources:** the [0.2 decision map](https://github.com/devfrx/jiffin/issues/75): tickets [#85](https://github.com/devfrx/jiffin/issues/85) (frame), [#83](https://github.com/devfrx/jiffin/issues/83) (the alert's commands) and [#84](https://github.com/devfrx/jiffin/issues/84) (tray list and settings); amends [ADR-0010](0010-windows-11-look-own-components.md)

## Context

[ADR-0010](0010-windows-11-look-own-components.md) made every window of
Jiffin a card without Windows' title bar: the alert, the creation window, the
tray list, the settings and the first-run window. None of them can be moved,
and none has an X. After a day with 0.1.0 the owner asked for both.

Three frames were tried on the owner's screen, on live windows to touch and
drag ([#85](https://github.com/devfrx/jiffin/issues/85)):

- **A — like the notifications:** no bar; a discreet X beside the title; the
  window drags from any empty point.
- **B — a bar:** 32 px with a small title and Windows' own X (46 × 32, red
  `#C42B1C` under the mouse, as in Windows Terminal); it drags from the bar
  only.
- **C — Windows' X in the corner,** without a bar.

The owner chose A. After dragging an alert in the trial, the owner also chose
that alerts do not move.

## Decision

**The X.** A Subtle `FluentButton`, 32 × 32, with the Cancel glyph (`E711`) at
16 px, coloured only under the mouse; 12 px from the right edge, centred on
the title's row.

| Window | Where the X is | What it does |
|---|---|---|
| Creation, settings, first run | right of the title | closes, as Esc still does; settings has no Chiudi button, as in Windows' Settings ([#84](https://github.com/devfrx/jiffin/issues/84)) |
| Tray list | right of Nuovo, on the title's row ([#84](https://github.com/devfrx/jiffin/issues/84)) | closes the list |
| Alert | the last of its three commands: Fatto, Rimanda, X ([#83](https://github.com/devfrx/jiffin/issues/83)) | closes without an answer, recorded as `chiuso` ([ADR-0021](0021-one-alert-per-unit.md)) |

**Dragging.** Every window but the alerts drags from any empty point, never
from its controls: a `DragHandler` that calls `QWindow.startSystemMove()`,
which in Qt 6.11.2 is a `WM_SYSCOMMAND` with `SC_DRAGMOVE`. Verified on these
frameless windows in the trial.

**Alerts stay where they are**: at the top centre of the primary screen's work
area, as in 0.1.

**A moved window opens again where it was left**, also after a restart: the
creation window, the settings and the first-run window. If that place is no
longer on a screen (a monitor unplugged), it opens at the centre. The tray list
always opens above its icon, also after it was moved: Claude's choice, told to
the owner and not contested.

## Consequences

**Positive**

- Every window closes the same way, and the cards keep the look of ADR-0010:
  no bar is added.
- Alerts stay in one predictable place, where a glance finds them.

**Negative (accepted)**

- A discreet X is less evident than Windows' red one.
- The windows' positions are saved and checked against the screens at every
  opening.

**Follow-up**

- The mockups in `docs/design/mockups/` get the X, and `docs/design/` the
  frame, when the windows are built.
