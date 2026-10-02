# The settings

What the user can set, in `jiffin.ui`: the material of Jiffin's windows, one of
the four of [ADR-0010](../adr/0010-windows-11-look-own-components.md).
`ui/preferences.py` holds the window's state, and `qml/PreferencesWindow.qml`
draws it with our own `FluentRadioButton` and `FluentButton`. What the settings
hold comes from [#6](https://github.com/devfrx/jiffin/issues/6) and
[#31](https://github.com/devfrx/jiffin/issues/31), the behaviour and the look
from [#43](https://github.com/devfrx/jiffin/issues/43); the
[mockup](mockups/settings.html) shows it in light and dark.

## The window

- **Impostazioni** in the tray icon's menu opens it, centred on the primary
  screen, with the focus on the material in use; an open one comes to the
  front.
- The four materials are radio buttons, each with its name and what it looks
  like; B, Acrilico dei menu, is the default. The owner chose the plain list on
  screen, over the radios in a card, as Windows' Settings, and over four tiles.
- **A click applies the material at once**, as Windows' own Settings: the glass
  of every window changes, this one's too, so the user sees the material on it.
  The owner chose this over Salva and Annulla, which cost a click every time.
  The check follows the look, never the click.
- Tab moves from a material to the next and on to Chiudi; Space chooses. Esc or
  Chiudi hides the window.
- With Windows' transparency effects off, every surface is solid, whatever the
  material: a line under the materials says so.
- The window is a card like the creation window, without Windows' title bar
  and without a taskbar button.

## Keeping the choice

The interface does not store anything ([ADR-0012](../adr/0012-package-structure-ports.md)):
each new choice goes to `keep_material`, of the `Upkeep` the app gives
`Interface`, and the app keeps it in the `setting` table
([data model](data-model.md)) and sets it on `Interface.look.material` at the
next start, before any window shows
([#44](https://github.com/devfrx/jiffin/issues/44)).

## Trying it

`uv run python -m jiffin.ui`, then Impostazioni in the tray icon's menu: a
click on a material prints it, and every window on screen changes. The unit
tests drive the window on Qt's offscreen platform
(`tests/unit/ui/test_preferences.py`).
