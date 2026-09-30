# ADR-0005: Read the browser address with UI Automation

- **Status:** Accepted
- **Date:** 2026-09-29
- **Deciders:** devfrx
- **Sources:** tickets [#2](https://github.com/devfrx/jiffin/issues/2) (research on reading the context), [#10](https://github.com/devfrx/jiffin/issues/10) (field capture) and [#17](https://github.com/devfrx/jiffin/issues/17) (decision)

## Context

The app and the title come from Win32 without any permission:
`GetForegroundWindow`, `GetWindowThreadProcessId` and
`QueryFullProcessImageNameW`, with changes delivered by an out-of-context
`SetWinEventHook` on `EVENT_SYSTEM_FOREGROUND`, and on `EVENT_OBJECT_NAMECHANGE`
filtered to the foreground window.

The address of the browser tab is harder, and it matters: 35 of the 106
sampled contexts were web pages, and conditions that name a site need it. The
browsers on the target machine are Vivaldi (the default), Chrome and Brave, all
Chromium-based.

- **UI Automation on the address bar:** nothing to install and no warning.
  But it returns the displayed text (Chrome drops `https://` and `www.`; while
  the user types, the typed text), the control's name is localized, its
  structure is not guaranteed across versions, and Vivaldi has no stable
  identifiers. Browsers turn on their accessibility tree when a UI Automation
  client appears, at a CPU cost not yet measured.
- **MV3 extension with native messaging:** the full URL and per-tab events.
  But it must be installed in every browser (Chrome Web Store with a paid
  registration and a privacy policy, or developer mode left on), shows the
  "Read your browsing history" warning, needs explicit consent in incognito,
  and its channel to the app must be secured.
- **Chrome DevTools Protocol:** excluded; since Chrome 136 the remote
  debugging flags are ignored on the default profile.

Field results on the target machine:

- Vivaldi 8.2 and Brave 1.96 return the full address, Chrome 154 the shortened
  text. Vivaldi returns it only once the client presents itself as an
  assistive technology.
- On the working day of 2026-09-28, in 254 Vivaldi contexts the address was
  read 215 times (85%). In 19 the user was typing in the bar, where not
  reading is correct; 20 failed (13 bar not found, 2 UI Automation errors,
  5 empty values).
- The first read in Vivaldi takes 48 ms, later ones 0.8 ms.
- Private and incognito windows can be recognized without an extension in all
  three browsers.

## Decision

- The address is read with **UI Automation on the address bar**, in Vivaldi,
  Chrome and Brave, from a COM thread in the multithreaded apartment, as the
  capture prototype does.
- **Private and incognito windows are ignored entirely.**
- When the address cannot be read, the context is app and title
  ([ADR-0004](0004-context-identity.md)). When a browser's address stays
  unreadable for a long time, a signal in the tray tells the user, so that a
  breakage after a browser update does not lose reminders in silence.
- The browser extension remains the fallback, after the first version.

The extension's advantage, the full URL, buys little: conditions name sites,
and Chrome's shortened text contains the site.

## Consequences

**Positive**

- Nothing to install or approve; it already works in all three browsers.

**Negative (accepted)**

- The value is the displayed text, not a canonical URL.
- High risk of breakage when a browser changes its UI.
- A browser running as administrator cannot be read (UI Automation does not
  reach elevated UI), so its contexts fall back to app and title.
- The CPU the browsers spend on accessibility is not measured yet.

**Follow-up**

- A benchmark in `tests/integration` measures that CPU cost: the same reads the
  app does, for 5 minutes, against 5 minutes without reads
  ([ADR-0017](0017-evaluation-harness-subpackage.md)).
- The tray signal and the banner in the tray list are part of the interface
  work ([ADR-0010](0010-windows-11-look-own-components.md)).
