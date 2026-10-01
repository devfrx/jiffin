pragma Singleton

import QtQml

// Windows 11's type ramp (ADR-0010): Segoe UI Variable for text, Segoe Fluent Icons for icons,
// both system fonts. Sizes and line heights in pixels.
QtObject {
    readonly property string textFont: "Segoe UI Variable Text"
    readonly property string captionFont: "Segoe UI Variable Small"
    readonly property string iconFont: "Segoe Fluent Icons"
    readonly property int body: 14
    readonly property int bodyLine: 20
    readonly property int caption: 12
    readonly property int captionLine: 16
    readonly property int icon: 16
    readonly property int chevron: 12
}
