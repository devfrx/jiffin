// A Fluent 2 info bar, drawn by us (ADR-0010): a warning or an error, its message, and a button
// under it when it has an action. Colours, glyphs and spacing are WinUI's InfoBar, as it lays
// out on a narrow surface.
import QtQuick
import QtQuick.Layouts

Rectangle {
    id: bar

    enum Severity {
        Warning,
        Error
    }

    property int severity: FluentInfoBar.Warning
    property string message
    // The button's text: no button when empty.
    property string action
    readonly property bool error: severity === FluentInfoBar.Error

    signal triggered

    implicitHeight: content.implicitHeight + 14 + 18
    radius: 4
    color: error ? Colors.criticalBackground : Colors.cautionBackground
    border.width: 1
    border.color: Colors.cardStroke

    // The icon: a disc in the severity's colour, and its glyph on it.
    Item {
        x: 16
        y: 16
        width: Typography.icon
        height: Typography.icon

        Text {
            text: "" // StatusCircleOuter
            color: bar.error ? Colors.critical : Colors.caution
            font.family: Typography.iconFont
            font.pixelSize: Typography.icon
        }
        Text {
            text: bar.error ? "" : "" // StatusCircleErrorX, StatusCircleExclamation
            color: Colors.textInverse
            font.family: Typography.iconFont
            font.pixelSize: Typography.icon
        }
    }

    ColumnLayout {
        id: content

        x: 16 + Typography.icon + 14
        y: 14
        width: bar.width - x - 16
        spacing: 12

        Text {
            Layout.fillWidth: true
            text: bar.message
            color: Colors.textPrimary
            font.family: Typography.textFont
            font.pixelSize: Typography.body
            lineHeight: Typography.bodyLine
            lineHeightMode: Text.FixedHeight
            wrapMode: Text.Wrap
        }
        FluentButton {
            visible: bar.action.length > 0
            text: bar.action
            focusPolicy: Qt.StrongFocus
            onClicked: bar.triggered()
        }
    }
}
