// The icon beside a situation's line (ADR-0028), under "Quando" and in the tray list: by the
// situation and the value it holds with, as `core` names them; the stopwatch for how long the
// thing of a condition has lasted, which is no situation. The line sets its size and colour.
import QtQuick

Text {
    required property string situation
    required property string value

    text: {
        switch (situation) {
        case "call":
            return ""; // Phone
        case "away":
            return ""; // Walk
        case "power":
            return value === "plugged" ? "" : ""; // BatteryCharging9, Battery10
        case "display":
            return value === "no" ? "" : ""; // DisconnectDisplay, TVMonitor
        case "headphones":
            return ""; // Headphone
        case "network":
            return value === "home" ? "" : value === "office" ? "" : ""; // Home, Work, NetworkOffline
        default:
            return ""; // Stopwatch
        }
    }
    font.family: Typography.iconFont
}
