# Context capture

How the app sees what is in the foreground: the app, the window title and, in
the browsers, the address
([ADR-0004](../adr/0004-context-identity.md),
[ADR-0005](../adr/0005-browser-address-ui-automation.md)); and the situations
around it ([below](#the-situations)). The code is `platform/`: `capture.py` is
the context thread and its observations, `address.py` reads the address bars
and the tabs through UI Automation, `audio.py`, `media.py` and `network.py`
read Core Audio, Windows' media controls and the networks, and `win32.py`
calls Windows.

## The context thread

```mermaid
sequenceDiagram
    participant W as Windows
    participant C as context thread
    participant B as browser, through UI Automation
    participant K as worker thread

    C->>W: hook the foreground changes, anywhere
    C->>W: hook the changes of title, place and size, in the process in front only
    C->>W: ask for the notices of the session and the power
    loop every change
        W-->>C: the foreground changed, the title of the window in front, or its rectangle into or out of full screen
        W-->>C: or the screen locked or unlocked, the PC goes to sleep or woke
        C->>W: the window in front: full screen? its program and its title
        opt Vivaldi, Chrome or Brave
            C->>B: private? the address bar: in use, or its text
        end
        C->>K: Observation(at, context), when the context changed
    end
```

- **The hooks** are out of context: Windows calls them on the thread that set
  them, from its message loop. The hook on the window in front moves with the
  process in front, since a hook on every process would bring the loop every
  change of the whole system. It takes two events that are next to each other:
  a title changed, and something moved or resized. A move matters only when
  the window in front goes into or out of full screen, so a drag reads
  nothing.
- **The notices** come to a message-only window on the same thread
  ([below](#away-lock-and-sleep)).
- **The apartment** is COM's multithreaded one, as UI Automation wants. The
  main thread stays in the single-threaded apartment Qt needs: comtypes puts
  the thread that imports it there.
- **Not contexts**: nothing in front, Jiffin's own windows, a program that
  cannot be opened, a private window, a window that may be private, and a
  window in full screen ([below](#full-screen)). Nothing is in front either
  while the screen is locked or the PC asleep.
- **A title** that ends halfway through an emoji is cleaned where it is read:
  the half left over becomes U+FFFD, which UTF-8 can carry to the engine.
- **The log** gets app names, counts and error codes; never a title or an
  address.

## A browser window

A private window has the same title as any other. UI Automation tells them
apart: Chrome and Brave end the name of their root view with "(In incognito)"
or "(Privato)", and Vivaldi has a `PrivateWindowIndicator` beside its address
bar. Vivaldi draws its interface as a web page, so its bar shows up only once
the client looks like assistive technology (a focus listener) and after a hit
test. The bar and the private flag of a window are kept for as long as it
exists, and a kept bar that is gone is looked up again at once: Vivaldi builds
a new one when a page leaves full screen.

| What UI Automation sees | Context | For the tray |
|---|---|---|
| the text of the bar (an empty bar: no address) | app, title, address | read |
| the bar has the focus: the user is typing | app and title | read |
| a private window | none | read |
| not private, but no bar, or an error reading it | app and title | failure |
| whether the window is private cannot be told | none | failure |

**A window that may be private is not a context.** ADR-0004 falls back to app
and title when the address cannot be read; when the private mark cannot be
read either, the window may be private, so it is ignored as a private one
would be. That is the case of the welcome page of a fresh Vivaldi, and of a
browser running as administrator, which UI Automation does not reach
(ADR-0005 expected app and title there).

## Away: lock and sleep

`core` knows the user is away only from the observations
([ADR-0021](../adr/0021-one-alert-per-unit.md)). The capture asks Windows for
two notices: the session's (`WTSRegisterSessionNotification`: locked,
unlocked) and the power's (`RegisterSuspendResumeNotification`: about to
sleep, awake). From a lock or a sleep it sends "no context"; it sends the
context in front again once the screen is unlocked and the PC awake, both. A
PC that does not lock when it sleeps is back as soon as it wakes: Windows says
so at every wake.

Measured on the owner's laptop on 2026-10-03
([#99](https://github.com/devfrx/jiffin/issues/99)). It sleeps in Modern
Standby, where `PBT_APMSUSPEND` is said not to come; it came, to a window
registered for it.

| What the owner did | Windows' notices | The capture of 0.1 |
|---|---|---|
| Win+L | locked, at once; unlocked, at the unlock | "no context" 2.1 s late, then the lock screen (`LockApp.exe`) and `explorer.exe` as contexts |
| Start, Sleep | about to sleep 0.1 s after the display went off, and locked | nothing: the Start menu stayed in front for the 37 s of sleep |
| closing the lid | about to sleep and locked, within 0.1 s | nothing |
| waking it | awake at once; unlocked at the unlock | the lock screen as a context until then |

The display going off and the user's presence are notified too, at the same
moments, but not used: ADR-0021 speaks of lock and sleep. A screen that turns
off by itself, without a lock or sleep, leaves the context in front.

## Full screen

A window in full screen in front is not a context
([ADR-0024](../adr/0024-hold-and-hide-alerts.md)): nothing is judged and
nothing rings over a video, a slide show or a game, and leaving it is a
return. The capture compares the rectangle of the window in front with its
monitor's at every foreground change, and again when the window in front moves
or resizes: F11 changes the rectangle, not the window. The window is in full
screen when it covers its whole monitor and has no caption, no sizing frame
and no tool window's style, as Chromium tells it, and is not one of the
desktop's or the shell's windows, as LightBulb lists them.
`SHQueryUserNotificationState` is not used. A check takes about 6 µs.

| On the owner's screen | Rectangle | Styles | Full screen |
|---|---|---|---|
| a video, or F11, in Vivaldi | the monitor | no caption, no sizing frame | yes, at once, in and out |
| a game (Unity) | the monitor | a popup | yes |
| a maximized window (Claude, Steam) | over the monitor's edges, but not the taskbar | caption and sizing frame | no |
| the desktop (Win+D) | the monitor | a tool window | no |

A maximized window overhangs its monitor by its frame, also over a taskbar that
hides itself: its styles tell it apart. PowerPoint was not tried, since the
owner has none to use. A window in full screen on another monitor is not seen.
The coordinates are physical pixels on both sides: Qt makes the process aware
of each monitor's scale.

## The unreadable signal

A browser update can break the reading. A browser's address is unreadable once
its bar has failed 5 times over at least 10 minutes, with no read in between:
long enough to pass over a failure now and then, and short enough to notice a
broken update within a working hour. A window in full screen, which hides the
bar, is not read at all. One read clears it. Only tab
windows count, those whose title ends with the browser's suffix: a dialog, an
installed web app or DevTools has no bar. The tray gets the set of unreadable
browsers whenever it changes.

## The situations

The same thread reads the situations of
[ADR-0028](../adr/0028-read-the-situations-in-core.md), in `Situations`: each
goes out at start, all at one time, and then only when its values changed.
`core` counts the 5 s a change must last ([situations.md](situations.md#over-time)).

```mermaid
sequenceDiagram
    participant W as Windows
    participant C as context thread
    participant K as worker thread

    C->>W: start Core Audio, the media controls and the Network List Manager
    C->>K: SituationObservation of each situation, at one time
    par a change of a source with events
        W-->>C: Core Audio or the networks changed: one message wakes the loop
        C->>W: read that source again
    and every second
        C->>W: the time since the last input, what plays, the power, the displays
    and the context in front changed, or a notice came
        C->>W: in a browser that captures, the name of its tab in front
    end
    C->>K: SituationObservation(at, situation, values), for each that changed
```

| Situation | Where it comes from | Read | A read |
|---|---|---|---|
| `call` | Core Audio's capture sessions: the processes whose stream from a microphone runs, never the system's sounds nor Jiffin, by their program in lower case | at Core Audio's events | 2.7 ms; the first 7.4 ms |
| `headphones` | the form of the default output: headphones or a headset | at Core Audio's events | 3.9 ms |
| `network` | the Network List Manager: the ids of the networks connected, and their labels | at its events | 2 ms |
| `playback` | Windows' media controls (GSMTC, WinRT through `ctypes`): the apps whose session plays | every second | 0.06 ms |
| `power` | `GetSystemPowerStatus`: on the mains, or not | every second | 2.6 µs |
| `display` | `QueryDisplayConfig`: a display not connected as the PC's own panel | every second | 0.38 ms |
| `away` | `GetLastInputInfo`, the notices of lock and sleep, the call and what plays | every second, at a notice | 1.6 µs |

Measured on the owner's laptop on 2026-10-08. The media controls start in
47 ms, the Network List Manager in 26 ms.

- **Events where a read costs, a tick where it does not.** Core Audio and the
  Network List Manager call back on threads of their own, often many times
  for one change: each call only posts a message to the loop, and not again
  until the loop has taken it; the loop reads that source again. The time
  since the last input has no event, and the others cost less to read every
  second than to follow. Core Audio's sessions send their events only to a
  thread in the multithreaded apartment, as the context thread is, and only
  once their manager has counted them.
- **What plays comes from Windows' media controls,** not from Core Audio's
  output sessions. An app whose output runs silent, a tab's WebAudio, a game,
  Discord, would keep `playback` on with Core Audio: `away` would never come,
  and "quando torno" never ring, a mistake nobody sees. The media controls
  miss the players that do not use them, a game, some music players: `away`
  then comes in front of them and the return rings, a mistake that shows. The
  values are the ids Windows gives those apps, `spotify.exe`, `vivaldi.<id>`;
  never a title or a track.
- **Away** comes at once with a lock or a sleep, until both are over;
  otherwise after 3 minutes (`AWAY_MS`) without a key, the mouse, a call or
  anything playing. A call and something playing count as input: after a call
  listened to for 10 minutes, the 3 minutes start at its end, or its end would
  read as a return.
- **A call in a browser.** Core Audio sees the whole browser. While Chrome or
  Brave captures and its tab window is in front, the capture reads the name of
  the selected tab: Chromium adds "Microphone recording", "Camera and
  microphone recording" or "Desktop content shared" to a tab that records or
  shares the screen, translated (English and Italian are known). Then the
  call's value is the site of the context's address, its host, and it stays
  while the browser captures, in front of other tabs and windows too; a tab
  that records, in front, moves it. The tab in front is the one whose name
  bears the window's title, alone or before its marks: Chromium's strip tells
  UI Automation of no selected tab (its views answer no selection), and a
  page's own tabs are not named so. The list that holds the tabs is kept per
  window; a window whose tabs do not bear its title is searched again only
  once the title changes, and a mark that comes a moment after the capture is
  read at the next second. Vivaldi's tabs tell what plays and what is shared,
  never what records (its interface's code, 8.2): its calls count whole, as
  those of a private window, of a window in full screen or of an address not
  read do.
- **The network** is known by the id the Network List Manager keeps for each
  network joined, never by its name. Its label, home or office, comes from the
  settings ([#153](https://github.com/devfrx/jiffin/issues/153)); until then a
  network gives no value, and `offline` comes when none is connected.
- **A device built again is no failure.** A Bluetooth headset that connects
  builds its microphone again, and the session manager kept from before then
  refuses every call (`AUDCLNT_E_DEVICE_INVALIDATED`): the reader makes a new
  one and follows the sessions again; a microphone that goes away while it is
  read is passed over until its next change, and an output built again while
  it is read is read once more. Seen on the owner's laptop on 2026-10-08,
  where it left Core Audio unread for a minute before.
- **A source that fails,** to start or to read, gives its situations no value
  (None): the log says it once, by the error's code, and the source starts
  again a minute later (`RETRY_MS`); a state read every second reads again at
  the next. Otherwise away, power, display and headphones always have a
  value: the harness takes the end of one of them, with nothing after it, for
  the app's close ([#155](https://github.com/devfrx/jiffin/issues/155)). At the
  close, the worker observes every situation as not read, all at the time of
  the context's last None.
- **The log** gets each change: programs and labels by name, a call's sites
  only by their count, never a network's id.

## Measured

Browsers turn on their accessibility tree when a UI Automation client appears,
and that CPU counts in the budget of
[ADR-0003](../adr/0003-acceptance-thresholds.md). The benchmark
(`uv run pytest -m benchmark -s`) keeps a fresh Vivaldi in front, on a page
whose title changes every second: 5 minutes without the capture, then 5 with
it, which reads the address at every change. On the owner's machine, 28
logical cores, on 2026-09-30:

| CPU | % of one core | % of the machine |
|---|---|---|
| Vivaldi, without the capture | 3.92 | 0.14 |
| Vivaldi, with the capture: 292 reads in 300 s | 4.63 | 0.17 |
| What the reads cost Vivaldi | 0.71 | 0.03 |
| The capture itself | 0.23 | 0.01 |

At one read a second, the reads cost Vivaldi under 1% of one core.
