// A Fluent 2 button, drawn by us: standard, accent or subtle (ADR-0010). By default it never
// takes the focus, like the alert it sits in; where Tab may reach it, it shows WinUI's focus
// ring, and Enter clicks it too. Colours and edges are WinUI's (see Colors.qml).
import QtQuick
import QtQuick.Templates as T

T.AbstractButton {
    id: control

    enum Kind {
        Standard,
        Accent,
        Subtle
    }

    property int kind: FluentButton.Standard
    // A Segoe Fluent Icons glyph: the button is square when it has no text.
    property string glyph: ""
    // The glyph's colour where it says something of its own: the accent of a completed
    // reminder's full circle (ADR-0030); the text's otherwise.
    property color glyphColor: textColor
    // The chevron of a button that opens more choices.
    property bool chevron: false

    readonly property bool accent: kind === FluentButton.Accent
    readonly property bool subtle: kind === FluentButton.Subtle
    readonly property color textColor: {
        if (!enabled)
            return accent ? Colors.textOnAccentDisabled : Colors.textDisabled;
        if (accent)
            return down ? Colors.textOnAccentSecondary : Colors.textOnAccent;
        return down ? Colors.textSecondary : Colors.textPrimary;
    }

    implicitWidth: text.length > 0 ? implicitContentWidth + leftPadding + rightPadding : 32
    implicitHeight: 32
    leftPadding: text.length > 0 ? 12 : 8
    rightPadding: text.length > 0 ? (chevron ? 10 : 12) : 8
    focusPolicy: Qt.NoFocus
    hoverEnabled: true
    Accessible.name: text

    Keys.onReturnPressed: click()
    Keys.onEnterPressed: click()

    background: Rectangle {
        radius: 4
        color: {
            if (control.accent) {
                if (!control.enabled)
                    return Colors.accentDisabled;
                return control.down ? Colors.accentPressed : control.hovered ? Colors.accentHover : Colors.accent;
            }
            if (control.subtle)
                return control.down ? Colors.subtleFillPressed : control.hovered ? Colors.subtleFillHover : "transparent";
            if (!control.enabled)
                return Colors.controlFillDisabled;
            return control.down ? Colors.controlFillPressed : control.hovered ? Colors.controlFillHover : Colors.controlFill;
        }
        border.width: control.subtle || (control.accent && !control.enabled) ? 0 : 1
        border.color: control.accent ? Colors.accentStroke : Colors.controlStroke

        // The edge that makes a button look raised: one pixel, clear of the rounded corners.
        // A disabled button is flat.
        Rectangle {
            visible: !control.subtle && control.enabled
            x: 4
            y: control.accent || Colors.controlEdgeAtBottom ? parent.height - 1 : 0
            width: parent.width - 8
            height: 1
            color: control.accent ? Colors.accentStrokeEdge : Colors.controlStrokeEdge
        }

        // The focus ring, 3 px outside the button: 2 px outer stroke, 1 px inner.
        Rectangle {
            visible: control.visualFocus
            anchors.fill: parent
            anchors.margins: -3
            radius: 7
            color: "transparent"
            border.width: 2
            border.color: Colors.focusStrokeOuter

            Rectangle {
                anchors.fill: parent
                anchors.margins: 2
                radius: 5
                color: "transparent"
                border.width: 1
                border.color: Colors.focusStrokeInner
            }
        }
    }

    contentItem: Row {
        spacing: 6

        Text {
            anchors.verticalCenter: parent.verticalCenter
            visible: control.glyph.length > 0
            text: control.glyph
            color: control.glyphColor
            font.family: Typography.iconFont
            font.pixelSize: Typography.icon
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            visible: control.text.length > 0
            text: control.text
            color: control.textColor
            font.family: Typography.textFont
            font.pixelSize: Typography.body
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            visible: control.chevron
            text: "" // ChevronDown
            color: control.textColor
            font.family: Typography.iconFont
            font.pixelSize: Typography.chevron
        }
    }
}
