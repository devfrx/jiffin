// A Fluent 2 radio button, drawn by us (ADR-0010): WinUI's 20 px circle, its label, and a
// caption under the label when it has one. Sizes, colours and motion are WinUI's
// RadioButton_themeresources.xaml (microsoft-ui-xaml at 8463f45162): the dot is 12 px, 14 under
// the mouse and 10 pressed. Tab reaches the checked one of a group, and the arrows move the check.
import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import Jiffin

T.RadioButton {
    id: control

    property string description: ""

    implicitWidth: leftPadding + implicitContentWidth + rightPadding
    implicitHeight: Math.max(32, topPadding + implicitContentHeight + bottomPadding)
    // The label starts 8 px after the circle and 6 px down, level with it.
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
        radius: 10
        color: {
            if (control.checked)
                return control.down ? Colors.accentPressed : control.hovered ? Colors.accentHover : Colors.accent;
            return control.down ? Colors.controlAltFillPressed : control.hovered ? Colors.controlAltFillHover : Colors.controlAltFill;
        }
        border.width: control.checked ? 0 : 1
        border.color: control.down ? Colors.controlStrongStrokeDisabled : Colors.controlStrongStroke

        // The dot: there when checked, and while an unchecked one is pressed.
        Rectangle {
            property real size: control.down ? 10 : control.checked ? (control.hovered ? 14 : 12) : 0

            anchors.centerIn: parent
            width: size
            height: size
            radius: size / 2
            color: Colors.textOnAccent

            Behavior on size {
                enabled: Look.animations

                NumberAnimation {
                    duration: 167
                    easing.type: Easing.BezierSpline
                    easing.bezierCurve: [0, 0, 0, 1, 1, 1]
                }
            }
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
