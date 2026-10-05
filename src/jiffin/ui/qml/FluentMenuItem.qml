// An item of a Windows 11 menu (WinUI's MenuFlyoutItem), drawn by us (ADR-0010): 32 px high,
// its text at 14 px with 12 px at the sides, rounded at 4 px and filled under the mouse as a
// subtle button. It never takes the focus, like the menu it is in; the item the keyboard is on,
// `current`, shows WinUI's focus ring on its edges, as MenuFlyoutItem's system focus visual.
import QtQuick
import QtQuick.Templates as T

T.AbstractButton {
    id: control

    property bool current: false

    implicitWidth: implicitContentWidth + leftPadding + rightPadding
    implicitHeight: 32
    leftPadding: 12
    rightPadding: 12
    focusPolicy: Qt.NoFocus
    hoverEnabled: true
    Accessible.name: text

    background: Rectangle {
        radius: 4
        color: control.down ? Colors.subtleFillPressed : control.hovered ? Colors.subtleFillHover : "transparent"

        // The focus ring: 2 px outer stroke, 1 px inner.
        Rectangle {
            visible: control.current
            anchors.fill: parent
            radius: 4
            color: "transparent"
            border.width: 2
            border.color: Colors.focusStrokeOuter

            Rectangle {
                anchors.fill: parent
                anchors.margins: 2
                radius: 2
                color: "transparent"
                border.width: 1
                border.color: Colors.focusStrokeInner
            }
        }
    }
    contentItem: Text {
        text: control.text
        verticalAlignment: Text.AlignVCenter
        color: control.down ? Colors.textSecondary : Colors.textPrimary
        font.family: Typography.textFont
        font.pixelSize: Typography.body
    }
}
