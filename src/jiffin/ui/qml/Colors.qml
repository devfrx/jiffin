pragma Singleton

import QtQuick
import Jiffin

// The colours of Windows 11 for the current theme (ADR-0010), from WinUI's theme resources:
// microsoft-ui-xaml at 8463f45162, Common_themeresources_any.xaml and
// AcrylicBrush_themeresources.xaml. Colours are #AARRGGBB.
QtObject {
    readonly property bool dark: Look.dark

    readonly property color textPrimary: dark ? "#FFFFFFFF" : "#E4000000"
    // The condition, and the text of a pressed button.
    readonly property color textSecondary: dark ? "#C5FFFFFF" : "#9E000000"
    readonly property color textOnAccent: dark ? "#FF000000" : "#FFFFFFFF"
    readonly property color textOnAccentSecondary: dark ? "#80000000" : "#B3FFFFFF"

    readonly property color controlFill: dark ? "#0FFFFFFF" : "#B3FFFFFF"
    readonly property color controlFillHover: dark ? "#15FFFFFF" : "#80F9F9F9"
    readonly property color controlFillPressed: dark ? "#08FFFFFF" : "#4DF9F9F9"
    readonly property color controlStroke: dark ? "#12FFFFFF" : "#0F000000"
    // A standard button's edge: lighter at the top in dark, darker at the bottom in light.
    readonly property color controlStrokeEdge: dark ? "#18FFFFFF" : "#29000000"
    readonly property bool controlEdgeAtBottom: !dark
    readonly property color subtleFillHover: dark ? "#0FFFFFFF" : "#09000000"
    readonly property color subtleFillPressed: dark ? "#0AFFFFFF" : "#06000000"

    // The user's accent, in the shade Windows makes for the theme; hover and pressed are it at
    // 90% and 80%.
    readonly property color accent: Look.accent
    readonly property color accentHover: Qt.alpha(accent, 0.9)
    readonly property color accentPressed: Qt.alpha(accent, 0.8)
    readonly property color accentStroke: "#14FFFFFF"
    // An accent button's edge, always at the bottom.
    readonly property color accentStrokeEdge: dark ? "#23000000" : "#66000000"

    // AcrylicBackgroundFillColorDefaultBrush: its fallback is the surface without glass, its
    // tint is B's veil.
    readonly property color surface: dark ? "#FF2C2C2C" : "#FFF9F9F9"
    readonly property color veil: dark ? "#FF2C2C2C" : "#FFFCFCFC"
}
