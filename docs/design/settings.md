# The settings

What the user can set, in `jiffin.ui`: the return pause of
[ADR-0021](../adr/0021-one-alert-per-unit.md), then the material of Jiffin's
windows, one of the four of
[ADR-0010](../adr/0010-windows-11-look-own-components.md).
`ui/preferences.py` holds the window's state, and `qml/PreferencesWindow.qml`
draws it with our own `FluentNumberBox`, `FluentComboBox`, `FluentRadioButton`
and `FluentButton`. What the settings hold comes from
[#6](https://github.com/devfrx/jiffin/issues/6),
[#31](https://github.com/devfrx/jiffin/issues/31) and
[#76](https://github.com/devfrx/jiffin/issues/76), the behaviour and the look
from [#43](https://github.com/devfrx/jiffin/issues/43) and
[#84](https://github.com/devfrx/jiffin/issues/84); the
[mockup](mockups/settings.html) shows it in light and dark.

## The window

- **Settings** in the tray icon's menu opens it, and so does **Change** in
  the tray list ([tray](tray.md)), at the centre of the primary screen or where
  the user left it ([ADR-0023](../adr/0023-window-frame.md)), with the focus on
  the pause, its first setting; an open one comes to the front where it is.
- Each change applies at once, as Windows' own Settings, and goes to be kept.
  The owner chose this over Save and Cancel, which cost a click every time.
- Tab moves from a control to the next; Space chooses. Esc or the X hides the
  window. The X sits on the title's line, and there is no Close, as in
  Windows' Settings ([#84](https://github.com/devfrx/jiffin/issues/84)); Tab
  passes the X by, since Esc does the same.
- The window is a card like the creation window, without Windows' title bar
  and without a taskbar button. It drags from any point no control takes. A
  centred window stays centred when the note on solid surfaces comes or goes;
  one the user moved keeps its top left corner.

## The return pause

- **The return pause** comes first, with "Se torni a una cosa dopo almeno
  questo tempo, i suoi promemoria suonano di nuovo. Da 10 secondi in su." The
  owner chose a number and its unit on screen, over a combo box of ready times
  where another can be typed.
- The number is WinUI's NumberBox with its spin buttons inline: Up (`E70E`) and
  Down (`E70D`) inside the box on the right, 32 px wide, off at the ends of
  the range; they repeat while held, and so do Up and Down on the keyboard. A
  number typed counts when the box is left or Enter is pressed; one out of the
  range comes back within it, as NumberBox does, and anything that is not a
  number gives the pause back.
- The unit is WinUI's ComboBox, with **seconds** and **minutes**. The pause
  shows in minutes when it is whole minutes, else in seconds, each time the
  window opens; the unit the user picks stays while it is open. Another unit
  converts the pause, to the nearest minute, half up, and at least one minute:
  90 s become two minutes, 20 s one; back to seconds, the pause stays as it
  is. The range is 10 s to 2 hours: 10 to 7200 seconds, 1 to 120 minutes.
- The combo box's list is a window of its own on the glass, which never takes
  the focus, as Snooze's menu: as wide as the box, with the chosen unit over
  the box, items of 32 px in slots of 36 with WinUI's pill on the chosen one.
  A press anywhere in the window closes it and does nothing else, as WinUI's
  light dismiss; so do Esc, before closing the window, Tab, and a click in
  another window. With the focus on the box, Up and Down pick the unit before
  or after, and Space, Enter, Alt+Down or F4 open the list, where Up and Down
  move with WinUI's focus ring and Space or Enter pick.

## The material

- The four materials are radio buttons, each with its name and what it looks
  like; B, "Acrilico dei menu", is the default. The owner chose the plain list on
  screen, over the radios in a card, as Windows' Settings, and over four tiles.
- A click changes the glass of every window at once, this one's too, so the
  user sees the material on it. The check follows the look, never the click.
- With Windows' transparency effects off, every surface is solid, whatever the
  material: a line under the materials says so.

## Keeping the choices

The interface does not store anything ([ADR-0012](../adr/0012-package-structure-ports.md)):
each new material goes to `keep_material`, and each new pause, in whole
seconds, to `keep_return_pause`, of the `Upkeep` the app gives `Interface`.
The app keeps them in the `setting` table ([data model](data-model.md)) and,
at the next start, before any window shows, sets them on
`Interface.look.material` and `Interface.preferences.return_pause`
([#44](https://github.com/devfrx/jiffin/issues/44)).

The return pause is one `return_pause` setting, in whole seconds from 10 to
7200. The worker reads it at the start, gives it to `core` and, in `Kept`, to
the interface; when it is missing, or of another shape, the pause is 2
minutes. A new one goes to the worker's `keep_return_pause`, which keeps it
and puts it in force at once.

The windows' places go the same way
([ADR-0023](../adr/0023-window-frame.md)). `ui/places.py` follows the creation
window, the settings and the first-run window: a place the user moved one to is
kept half a second after the window stops moving, once a drag ends, and all of
them go to `keep_places`. The app keeps them as one `places`
setting, `{"creation": [x, y], ...}`, and gives them to `Interface.places` at
the next start; an entry of another shape is left out, and that window opens at
the centre.

## Trying it

`uv run python -m jiffin.ui`, then Settings in the tray icon's menu, or
Change in its list: a new pause or material is printed, and every window on
screen takes the material. The unit tests drive the window on Qt's offscreen
platform (`tests/unit/ui/test_preferences.py`).
