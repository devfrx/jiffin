# ADR-0009: Build the interface with Qt Quick and PySide6

- **Status:** Accepted
- **Date:** 2026-09-30
- **Deciders:** devfrx
- **Sources:** tickets [#3](https://github.com/devfrx/jiffin/issues/3) (overlay frameworks), [#16](https://github.com/devfrx/jiffin/issues/16) (stack) and [#31](https://github.com/devfrx/jiffin/issues/31) (alert prototype)

## Context

The alert is an always-on-top overlay that must never take the focus while the
user types elsewhere. It must stay clickable, stay out of the taskbar and
Alt+Tab, react to the mouse hovering over it, and show Windows 11 materials
([ADR-0010](0010-windows-11-look-own-components.md)). The app also needs a
global shortcut and a tray icon. The owner reads Python, TypeScript/JavaScript
and Rust, not C#, and reviews the code. The engine and the measurement code are
in Python.

- **Qt Quick (QML) with PySide6, logic in Python.** A window with
  `Qt::WindowDoesNotAcceptFocus` gets `WS_EX_NOACTIVATE`, is shown with
  `SW_SHOWNOACTIVATE`, and Qt answers `MA_NOACTIVATE` to clicks (verified in
  the qtbase source). One language for app, engine and harness. QML has typed
  properties, TypeScript-like annotated functions
  (`function show(text: string): bool`) and a linter, `qmllint`. LGPL.
- **Tauri** (Rust and TypeScript). It exposes `focusable(false)` since 2.8,
  but since tao 0.37.1 (2026-09-26) `set_visible(true)` focuses a window
  created with `with_focused(false)` (tao changelog); tao does not answer
  `MA_NOACTIVATE`, and a click in WebView2 may activate the window. It adds
  Rust and TypeScript next to the Python engine.
- **Electron.** Handles the overlay, but carries Chromium's weight and ships a
  major version every 8 weeks.
- **WinUI 3 and WPF.** C#, and the no-focus overlay needs Win32 interop.
  WinUI's acrylic is not applied to a window with `WS_EX_NOACTIVATE`
  (microsoft-ui-xaml #10570); WPF's Fluent theme is still experimental in
  .NET 10. Avalonia also needs Win32 interop.
- **Flutter.** On Windows its `window_manager` plugin ignores
  `show(inactive: true)` and never sets `WS_EX_NOACTIVATE`: Win32 interop
  again.

## Decision

- The interface is built with **Qt Quick (QML) and PySide6 6.11.2**
  (LGPLv3); the app logic is **Python 3.13**, with the environment and the
  lockfile managed by **uv**.
- QML holds only the interface. Python view-models are exposed with
  `@QmlElement` and `@QmlSingleton`, never with `setContextProperty`, which the
  Qt 6.11 documentation discourages.
- Move to PySide6 6.12 when it is released, to read Windows' animation-effects
  setting through `motionPreference`; until then it is read with Windows APIs.

The deciding factor is the focus: Qt keeps it where it is natively, and the
whole app stays in one language.

Verified on the target machine with a throwaway prototype
(`NO_GIT\sibyl-avviso`, PySide6 6.11.2):

- In 20 rounds of showing the alert, hovering, clicking Done, Snooze or Useful
  from its menu and hiding it, while typing in another window, the foreground
  window and the text caret never moved: 160 keystrokes out of 160 arrived.
- Hovering paused the 10 s timer 20 times out of 20; three stacked alerts
  disappeared on their own without touching the focus.
- CPU 2.4% of the machine with three animated alerts, 0.03% at rest; the UI
  process uses 223 MB of working set (163 MB private), stable after 3 and after
  20 rounds; no VRAM on the NVIDIA GPU, since Qt renders on the Intel UHD.

## Consequences

**Positive**

- The hardest requirement, never taking the focus, works natively.
- One language across the whole codebase.

**Negative (accepted)**

- Qt 6.11 exposes neither the transparency nor the animation setting of
  Windows, and its FluentWinUI3 style is not ready: our own components and some
  Win32 interop ([ADR-0010](0010-windows-11-look-own-components.md)).
- QtAsyncio and QProcess limitations shape the threading model
  ([ADR-0012](0012-package-structure-ports.md)).
- PySide6 is a large part of the bundle.

**Follow-up**

- Screen-reader announcements for the alert are postponed until after the
  first version, which is for the owner's personal use. NVDA drops UI
  Automation notifications from apps without the focus, and Qt's UI Automation
  provider has no LiveRegion, so it needs a hand-written UI Automation piece.
