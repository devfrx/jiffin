pragma Singleton

import QtQuick
import Jiffin

// The colours of Windows 11 for the current theme (ADR-0010), from WinUI's theme resources:
// microsoft-ui-xaml at 8463f45162, Common_themeresources_any.xaml and
// AcrylicBrush_themeresources.xaml; Button_ and TextBox_themeresources.xaml say which colour
// goes where. Colours are #AARRGGBB.
QtObject {
    readonly property bool dark: Look.dark

    readonly property color textPrimary: dark ? "#FFFFFFFF" : "#E4000000"
    // The condition, the text of a pressed button, a box's description and placeholder.
    readonly property color textSecondary: dark ? "#C5FFFFFF" : "#9E000000"
    readonly property color textDisabled: dark ? "#5DFFFFFF" : "#5C000000"
    readonly property color textOnAccent: dark ? "#FF000000" : "#FFFFFFFF"
    readonly property color textOnAccentSecondary: dark ? "#80000000" : "#B3FFFFFF"
    readonly property color textOnAccentDisabled: dark ? "#87FFFFFF" : "#FFFFFFFF"

    readonly property color controlFill: dark ? "#0FFFFFFF" : "#B3FFFFFF"
    readonly property color controlFillHover: dark ? "#15FFFFFF" : "#80F9F9F9"
    readonly property color controlFillPressed: dark ? "#08FFFFFF" : "#4DF9F9F9"
    readonly property color controlFillDisabled: dark ? "#0BFFFFFF" : "#4DF9F9F9"
    // A text box with the focus.
    readonly property color controlFillInputActive: dark ? "#B31E1E1E" : "#FFFFFFFF"
    readonly property color controlStroke: dark ? "#12FFFFFF" : "#0F000000"
    // A text box's bottom edge, without the focus.
    readonly property color controlStrongStroke: dark ? "#8BFFFFFF" : "#72000000"
    // A standard button's edge: lighter at the top in dark, darker at the bottom in light.
    readonly property color controlStrokeEdge: dark ? "#18FFFFFF" : "#29000000"
    readonly property bool controlEdgeAtBottom: !dark
    readonly property color subtleFillHover: dark ? "#0FFFFFFF" : "#09000000"
    readonly property color subtleFillPressed: dark ? "#0AFFFFFF" : "#06000000"
    // A radio button's circle, unchecked: at rest, under the mouse, pressed; its edge pressed.
    readonly property color controlAltFill: dark ? "#19000000" : "#06000000"
    readonly property color controlAltFillHover: dark ? "#0BFFFFFF" : "#0F000000"
    readonly property color controlAltFillPressed: dark ? "#12FFFFFF" : "#18000000"
    readonly property color controlStrongStrokeDisabled: dark ? "#28FFFFFF" : "#37000000"

    // The user's accent, in the shade Windows makes for the theme; hover and pressed are it at
    // 90% and 80%.
    readonly property color accent: Look.accent
    readonly property color accentHover: Qt.alpha(accent, 0.9)
    readonly property color accentPressed: Qt.alpha(accent, 0.8)
    readonly property color accentStroke: "#14FFFFFF"
    // An accent button's edge, always at the bottom.
    readonly property color accentStrokeEdge: dark ? "#23000000" : "#66000000"
    readonly property color accentDisabled: dark ? "#28FFFFFF" : "#37000000"

    // The keyboard focus: a ring of two strokes, outside the control.
    readonly property color focusStrokeOuter: dark ? "#FFFFFFFF" : "#E4000000"
    readonly property color focusStrokeInner: dark ? "#B3000000" : "#B3FFFFFF"

    // AcrylicBackgroundFillColorDefaultBrush: its fallback is the surface without glass, its
    // tint is B's veil.
    readonly property color surface: dark ? "#FF2C2C2C" : "#FFF9F9F9"
    readonly property color veil: dark ? "#FF2C2C2C" : "#FFFCFCFC"

    // A card inside a surface: an unseen alert in the tray list.
    readonly property color cardFill: dark ? "#0DFFFFFF" : "#B3FFFFFF"

    // An info bar's severity: its icon in the colour, and the glyph on the icon in textInverse.
    readonly property color caution: dark ? "#FFFCE100" : "#FF9D5D00"
    readonly property color critical: dark ? "#FFFF99A4" : "#FFC42B1C"
    readonly property color textInverse: dark ? "#E4000000" : "#FFFFFFFF"

    // A scroll bar's thumb: ControlStrongFillColorDefault.
    readonly property color scrollThumb: dark ? "#8BFFFFFF" : "#72000000"
}
