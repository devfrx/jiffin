# ADR-0010: Follow the Windows 11 look with our own QML components

- **Status:** Accepted; amended by [ADR-0023](0023-window-frame.md) (every window has an X, and all but the alerts drag)
- **Date:** 2026-09-30
- **Deciders:** devfrx
- **Sources:** tickets [#12](https://github.com/devfrx/jiffin/issues/12) (behaviour), [#25](https://github.com/devfrx/jiffin/issues/25) (visual direction) and [#31](https://github.com/devfrx/jiffin/issues/31) (alert prototype)

## Context

The app has three surfaces: the alert, the creation window and the list opened
from the tray. Two directions were drawn on the same screens, in light and dark:

- **A — part of Windows:** Windows 11 shapes, Segoe UI Variable, the user's
  accent colour, Acrylic and Mica.
- **B — an identity of its own:** solid surfaces, laurel green, Atkinson
  Hyperlegible Next for the interface and Newsreader for the user's words.

The owner chose A. Building it in Qt Quick showed three problems:

- Qt's FluentWinUI3 style (6.11.2) is not ready: `Menu` has no background,
  because it reads `Config.controls.popup["normal"]`, which is null; `Button`
  floods the log with TypeErrors (225 in a short run) while it works.
- Windows removes Acrylic from a window when it deactivates, and the alert is
  never active.
- The Acrylic Windows gives to windows looked lighter and more transparent than
  its own menus, and not like Windows next to the Settings window.

## Decision

**Look: Windows 11 and Fluent 2**, like the system apps built with WinUI 3.

- Font: Segoe UI Variable, a system font. Body 14 px, captions 12, titles 14
  and 20 semibold.
- Accent: the user's Windows accent colour, in the shades Windows generates
  for the theme. Neutrals: the Windows ones.
- Shapes: 8 px radius for windows and cards, 4 px for controls; controls
  32 px tall.
- Light and dark follow Windows, also when they change while the app runs.

**Our own QML components**, not the FluentWinUI3 style.

**Materials.**

- Every window of Jiffin, the alert, the creation window, the tray list, the
  settings and the first-run window, uses the material chosen in the
  settings, one of four; the default is B.

  | | Material | Look |
  |---|---|---|
  | A | `DWMSBT_TRANSIENTWINDOW` (Desktop Acrylic) | light glass, blurred content behind |
  | **B** | A plus a veil, `#2C2C2C` (dark) or `#FCFCFC` (light) at 90% | like Windows menus: almost solid, a hint of glass |
  | C | `DWMSBT_MAINWINDOW` (Mica) | like the Settings window |
  | D | `DWMSBT_TABBEDWINDOW` (Mica Alt) | darker, more colour from the desktop |

  B's veil comes from WinUI's `AcrylicBackgroundFillColorDefaultBrush`: tint
  `#2C2C2C` with luminosity 0.96 in dark, `#FCFCFC` with 0.85 in light. It
  started as an approximation at about 80%; the owner set it at 90% by eye,
  next to Windows' menus ([#42](https://github.com/devfrx/jiffin/issues/42)).
- The creation window is a card like the alert, without Windows' title bar.
  The owner chose it on screen
  ([#43](https://github.com/devfrx/jiffin/issues/43)) over Mica under
  Windows' title bar, the first choice here, and over B under Windows' title
  bar, whose caption DWM draws on the bare backdrop, without B's veil.
- With Windows' transparency effects off, or in energy saver, surfaces are
  solid, and the glass comes back when they are on again.

**Glass on a window that is never active** (verified), which the creation
window uses too, so its glass stays while the user is in another app:

- `WS_CAPTION` in the style, with `WM_NCCALCSIZE` returning 0: without a frame,
  DWM ignores the backdrop.
- `WM_NCACTIVATE` always passed as TRUE to `DefWindowProcW` from the native
  event filter, never to Qt; otherwise the glass stays solid.
- The backdrop is recreated (none, then the material, then `WM_NCACTIVATE`)
  once after `ImmersiveColorSet`, `WM_THEMECHANGED` or
  `WM_DWMCOLORIZATIONCOLORCHANGED`; otherwise it stays solid until transparency
  is toggled.
- A `{65536, 0, 0, 0}` margin and a nudge of the window after the first
  `show()`, from QWindowKit (Apache-2.0); whether they are needed is unproven.

**Glass under a window with Windows' own frame** (verified on the first
creation window, [#43](https://github.com/devfrx/jiffin/issues/43); no window
keeps Windows' frame now): its client area has to be painted black on
`WM_ERASEBKGND`, from the native event filter, since DWM shows the backdrop
where a window whose frame extends into the client area is black. Otherwise
the window's GDI surface, which Qt never paints since it draws through
DirectComposition, shows white between the backdrop and the QML at every show;
a nudge clears it only until the next show.

**Windows settings** are read and followed live:

| Setting | Change notification | Where to read it |
|---|---|---|
| Light or dark | `WM_SETTINGCHANGE` "ImmersiveColorSet", Qt's `colorSchemeChanged` | Qt, or `AppsUseLightTheme` |
| Accent colour | `WM_DWMCOLORIZATIONCOLORCHANGED`, Qt's `ApplicationPaletteChange` | `QPalette::Accent` |
| Transparency effects | `WM_SETTINGCHANGE` "ImmersiveColorSet"; nothing from Qt | `EnableTransparency` in the registry |
| Animation effects | `WM_SETTINGCHANGE` with `SPI_SETCLIENTAREAANIMATION` | `SPI_GETCLIENTAREAANIMATION` |
| Taskbar light or dark, for the tray icon | `WM_SETTINGCHANGE` "ImmersiveColorSet" | `SystemUsesLightTheme` in the registry |
| Accent shade for the tray icon's dot | `WM_DWMCOLORIZATIONCOLORCHANGED` | `AccentPalette` in the registry: Light2 on a dark taskbar, Dark1 on a light one |

**Motion**, with WinUI's values: the alert enters from the top in 250 ms with
`cubic-bezier(0, 0, 0, 1)` and leaves in 167 ms with `cubic-bezier(1, 0, 1, 1)`.
With animations off, only a fade.

**Our own touch:** the alert shows the user's own "Quando…" condition, so it is
clear why it appeared, and a thin bar shows its 10 seconds passing, also with
animations off.

**Tray icon:** a monochrome glyph like the system icons, dark on a light
taskbar and white on a dark one. States: normal; a dot in the accent colour
while an alert waits or has not been seen; "!" when a browser address cannot be
read
([ADR-0005](0005-browser-address-ui-automation.md)). Its menu is Windows' own,
and stays light in dark mode unless the app asks for dark menus with uxtheme's
`SetPreferredAppMode(AllowDark)` and `FlushMenuThemes`: undocumented, exported
only by ordinal (135 and 136), called as Notepad++ does; Windows documents no
other way. Seen dark on the owner's machine
([#43](https://github.com/devfrx/jiffin/issues/43)).

**Settings window:** a card like the creation window, with the four materials
as WinUI's radio buttons; a click applies the material at once, as Windows'
Settings. The owner chose on screen
([#43](https://github.com/devfrx/jiffin/issues/43)) the plain list over the
radios in a card, as Windows' Settings, and over four tiles.

**First-run window:** a card like the creation window, with the model file's
way in three steps, each with a numbered disc that takes a check once done and
a bar while it runs. The owner chose the steps on screen
([#43](https://github.com/devfrx/jiffin/issues/43)) over a plain card and one
with the app's glyph above a large title.

**Tray list:** a card like the alert, over the tray. The owner chose on screen
([#43](https://github.com/devfrx/jiffin/issues/43)) its warnings as a line
without the box of WinUI's InfoBar, where only the icon has the severity's
colour (the yellow box stood out too much), and active reminders that complete
from a circle at their left, as in Microsoft To Do, with Elimina asking first.

## Consequences

**Positive**

- The app looks like part of Windows and follows the user's settings.
- The choice of material settled a matter of taste without forcing one answer.

**Negative (accepted)**

- Our own components to write and maintain.
- Win32 interop in the interface layer. The native event filter, written in
  Python, sees every window message; its cost is inside the 2.4% CPU measured
  ([ADR-0009](0009-qt-quick-pyside6-interface.md)).
- The contrast of text on the accent cannot be measured once and for all,
  because the user picks the accent. Windows generates contrast-optimized
  shades; check with a very light and a very dark accent.

**Follow-up**

- Port the chosen mockups into `docs/design/mockups/`.
- Qt sends a mouse enter and leave after `hide()`: ignore hover events on
  hidden windows.
- Screen-reader announcements are postponed
  ([ADR-0009](0009-qt-quick-pyside6-interface.md)).
