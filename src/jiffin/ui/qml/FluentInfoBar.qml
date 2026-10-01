// A Fluent 2 info bar, drawn by us (ADR-0010): a warning or an error, its message, and a button
// under it when it has an action. The glyphs and the severity's colours are WinUI's InfoBar; its
// box is left out, as the owner chose on screen: a quiet line, where only the icon has colour.
import QtQuick
import QtQuick.Layouts

Item {
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

    implicitHeight: content.implicitHeight

    // The icon: a disc in the severity's colour, and its glyph on it.
    Item {
        x: 8
        y: 2
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

        x: 8 + Typography.icon + 10
        width: bar.width - x - 8
        spacing: 8

        Text {
            Layout.fillWidth: true
            text: bar.message
            color: Colors.textSecondary
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
