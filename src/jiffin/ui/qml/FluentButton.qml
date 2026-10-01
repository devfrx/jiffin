// A Fluent 2 button, drawn by us: standard, accent or subtle (ADR-0010). It never takes the
// focus, like the window it sits in. Colours and edges are WinUI's (see look.py).
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
    // The chevron of a button that opens more choices.
    property bool chevron: false

    readonly property bool accent: kind === FluentButton.Accent
    readonly property bool subtle: kind === FluentButton.Subtle
    readonly property color textColor: accent ? (down ? Colors.textOnAccentSecondary : Colors.textOnAccent) : (down ? Colors.textSecondary : Colors.textPrimary)

    implicitWidth: text.length > 0 ? implicitContentWidth + leftPadding + rightPadding : 32
    implicitHeight: 32
    leftPadding: text.length > 0 ? 12 : 8
    rightPadding: text.length > 0 ? (chevron ? 10 : 12) : 8
    focusPolicy: Qt.NoFocus
    hoverEnabled: true
    Accessible.name: text

    background: Rectangle {
        radius: 4
        color: {
            if (control.accent)
                return control.down ? Colors.accentPressed : control.hovered ? Colors.accentHover : Colors.accent;
            if (control.subtle)
                return control.down ? Colors.subtleFillPressed : control.hovered ? Colors.subtleFillHover : "transparent";
            return control.down ? Colors.controlFillPressed : control.hovered ? Colors.controlFillHover : Colors.controlFill;
        }
        border.width: control.subtle ? 0 : 1
        border.color: control.accent ? Colors.accentStroke : Colors.controlStroke

        // The edge that makes a button look raised: one pixel, clear of the rounded corners.
        Rectangle {
            visible: !control.subtle
            x: 4
            y: control.accent || Colors.controlEdgeAtBottom ? parent.height - 1 : 0
            width: parent.width - 8
            height: 1
            color: control.accent ? Colors.accentStrokeEdge : Colors.controlStrokeEdge
        }
    }

    contentItem: Row {
        spacing: 6

        Text {
            anchors.verticalCenter: parent.verticalCenter
            visible: control.glyph.length > 0
            text: control.glyph
            color: control.textColor
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
