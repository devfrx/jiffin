// A Fluent 2 check box, drawn by us (ADR-0010) like FluentRadioButton: WinUI's 20 px box with
// 4 px corners, its label 8 px after it, and a caption under the label when it has one. Sizes and
// colours are WinUI's CheckBox_themeresources.xaml (microsoft-ui-xaml at 8463f45162): unchecked,
// ControlAltFill and the strong stroke; checked, the accent, 90% under the mouse and 80% pressed,
// with the CheckMark glyph at 12 px. Space or a click toggles it.
import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import Jiffin

T.CheckBox {
    id: control

    property string description: ""

    implicitWidth: leftPadding + implicitContentWidth + rightPadding
    implicitHeight: Math.max(32, topPadding + implicitContentHeight + bottomPadding)
    // The label starts 8 px after the box and 6 px down, level with it.
    leftPadding: 20 + 8
    topPadding: 6
    bottomPadding: 6
    focusPolicy: Qt.StrongFocus
    hoverEnabled: true
    Accessible.name: text
    Accessible.description: description

    indicator: Rectangle {
        y: 6
        width: 20
        height: 20
        radius: 4
        color: {
            if (control.checked)
                return control.down ? Colors.accentPressed : control.hovered ? Colors.accentHover : Colors.accent;
            return control.down ? Colors.controlAltFillPressed : control.hovered ? Colors.controlAltFillHover : Colors.controlAltFill;
        }
        border.width: control.checked ? 0 : 1
        border.color: control.down ? Colors.controlStrongStrokeDisabled : Colors.controlStrongStroke

        Text {
            anchors.centerIn: parent
            anchors.verticalCenterOffset: 1
            visible: control.checked
            text: "" // CheckMark
            color: control.down ? Colors.textOnAccentSecondary : Colors.textOnAccent
            font.family: Typography.iconFont
            font.pixelSize: 12
        }
    }

    contentItem: ColumnLayout {
        spacing: 0

        Text {
            Layout.fillWidth: true
            text: control.text
            color: Colors.textPrimary
            font.family: Typography.textFont
            font.pixelSize: Typography.body
            lineHeight: Typography.bodyLine
            lineHeightMode: Text.FixedHeight
            wrapMode: Text.Wrap
        }
        Text {
            Layout.fillWidth: true
            visible: control.description.length > 0
            text: control.description
            color: Colors.textSecondary
            font.family: Typography.captionFont
            font.pixelSize: Typography.caption
            lineHeight: Typography.captionLine
            lineHeightMode: Text.FixedHeight
            wrapMode: Text.Wrap
        }
    }

    // WinUI's focus ring, 7 px out at the sides and 3 px above and below.
    Rectangle {
        visible: control.visualFocus
        x: -7
        y: -3
        width: control.width + 14
        height: control.height + 6
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
