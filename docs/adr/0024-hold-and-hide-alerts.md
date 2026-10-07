# ADR-0024: Hold alerts while a window is in full screen or Jiffin is paused, and hide them from screen capture

- **Status:** Accepted; amended by [ADR-0027](0027-light-sleep-of-the-engine.md) (while nothing is in front, the engine sleeps)
- **Date:** 2026-10-03
- **Deciders:** devfrx
- **Sources:** the [0.2 decision map](https://github.com/devfrx/jiffin/issues/75): tickets [#93](https://github.com/devfrx/jiffin/issues/93) (research) and [#94](https://github.com/devfrx/jiffin/issues/94) (decision); completes [ADR-0021](0021-one-alert-per-unit.md)

## Context

With [ADR-0021](0021-one-alert-per-unit.md) a reminder with only a time rings
over any stable context, and the alert is a window always on top. It would
ring over a presentation, a video or a game in full screen, and in front of
everyone watching a screen shared in a call. In 0.1 the only way to silence
Jiffin is Esci, and it comes back only when opened again.

What Windows 11 tells an app ([#93](https://github.com/devfrx/jiffin/issues/93)):

- **Full screen.** `SHQueryUserNotificationState` says "busy" with a
  full-screen app, but sends nothing when one starts or stops, and an
  overlay of another program, transparent and as large as the screen, makes
  it say "busy" when nothing is in full screen; its presentation mode needs
  the Presentation Settings, which Windows Home lacks. An app can instead
  compare the rectangle of the window in front with its monitor, as Chromium,
  WebRTC and LightBulb do: about 14 µs, on the foreground event the capture
  already has.
- **Do Not Disturb** is readable through a documented API,
  `ToastNotificationManagerForUser.NotificationMode`, with a change event,
  from build 10.0.23504. On the owner's machine it was on while this was
  researched.
- **Screen sharing** is not reported by any documented API. An app can only
  keep its own windows out of captures:
  `SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)`, from Windows 10
  2004. The window stays on the user's monitor and disappears from every
  capture that goes through Windows (Windows.Graphics.Capture, DXGI, GDI):
  screen sharing in browsers and in Teams, Zoom or Discord, OBS, the Snipping
  Tool. A projector or monitor on a cable still shows it, and so do Microsoft
  Remote Desktop and a photo of the screen.

## Decision

The owner chose ([#94](https://github.com/devfrx/jiffin/issues/94)):

1. **In full screen or presenting, the alert waits until the user leaves**,
   then rings, with the time it was due.
2. **While the screen is shared, only the user sees the alert**: it is kept
   out of screen capture.
3. **Do Not Disturb does not stop Jiffin**, as it does not stop Windows' own
   reminders. Jiffin does not read it.
4. **A pause from the tray**: "Sospendi per un'ora" and "Sospendi fino a
   domani" in the right-click menu. Alerts wait and ring after.

Claude's choices, told before the questions and not contested: alerts held
back ring as after being away
([#82](https://github.com/devfrx/jiffin/issues/82), ADR-0021); full screen is
recognised on the monitor of the window in front only.

**A full-screen window in front is not a context**, like a locked screen
([ADR-0021](0021-one-alert-per-unit.md)): while it is in front nothing is
judged and nothing rings, and `core` sees the user as away. Leaving full
screen is a return: occasions start again as after any absence, and reminders
with only a time ring at the first stable context. The capture recognises it
by the rectangle of the window in front against its monitor, filtering
styles, the desktop and the shell's windows as Chromium and WebRTC do, and
checks again when the window in front moves or resizes (F11 changes the
rectangle, not the window). `SHQueryUserNotificationState` is not used.

**The pause** is away too, for `core`, until it ends: an hour later, or at
the same 08:00 as Rimanda's "Domani", the next Jiffin day's
([#83](https://github.com/devfrx/jiffin/issues/83)): paused at 01:00, before
the day turns at 04:00, it ends at 08:00 of that same morning.
While paused, the tray menu has "Riprendi", and the tray list says so at the
top ("In pausa fino alle 15:30"). The pause is saved with the settings and
survives a restart of the app. How the tray icon shows it is chosen on live
variants when it is built.

**Hidden from capture: the windows that come uninvited**, the alert and
Rimanda's menu. The creation window, the tray list and the settings are
opened by the user, and stay visible. The affinity is set when the alert
shows and cleared when it leaves, so that nothing is excluded while no alert
is on screen. A refusal from Windows leaves the alert visible, the mistake
that shows, and its error code goes to the log.

## Consequences

**Positive**

- No alert over a presentation, a film or a game, and none in front of an
  audience watching a shared screen.
- A pause that ends by itself instead of Esci, which needs remembering to open
  Jiffin again.
- No new dependency: `user32` through `ctypes`, as the interface already does
  ([ADR-0010](0010-windows-11-look-own-components.md)).

**Negative (accepted)**

- A long film or game delays a reminder until it ends; the alert then says
  when it was due.
- A full-screen window on a second monitor is not seen, and a projector on a
  cable shows alerts: the pause covers both.
- The owner's own screenshots and recordings do not show alerts. Third-party
  reports say NVIDIA's Instant Replay turns off while a window is excluded
  from capture; with the affinity set only while an alert shows, this is
  limited to those seconds, unverified.
- Any program can read that a window of Jiffin is excluded from capture
  (`GetWindowDisplayAffinity`).

**Follow-up**

- Verify on the owner's machine, while building: the exclusion on the Qt
  Quick alert window with its glass, also after hiding and showing it again,
  sharing in Meet in a browser and with the Snipping Tool; full screen
  recognised with a video, F11 and PowerPoint.
- Full screen measured on the owner's machine
  ([#99](https://github.com/devfrx/jiffin/issues/99)): a video and F11 in
  Vivaldi, and a game, cover the monitor without caption and sizing frame,
  and are seen at once, in and out; maximized windows and the desktop are not
  ([context capture](../design/context.md)). PowerPoint was not tried: the
  owner has none to use.
- The exclusion verified on the owner's machine
  ([#102](https://github.com/devfrx/jiffin/issues/102)): the alerts and
  Rimanda's menu, Qt Quick windows with their glass, are missing from the
  Snipping Tool's full-screen captures, also after hiding and showing again,
  and keep their glass on the monitor; Windows refused no call. Sharing in
  Meet was not tried yet: it was left to the acceptance day
  ([#106](https://github.com/devfrx/jiffin/issues/106)), and, as the owner
  could not try it then, to [#136](https://github.com/devfrx/jiffin/issues/136).
