// A Fluent 2 scroll bar, drawn by us (ADR-0010): a thin line at the edge that widens under the
// mouse, as WinUI's, without its arrows. It shows only while there is something to scroll.
import QtQuick
import QtQuick.Templates as T

T.ScrollBar {
    id: control

    implicitWidth: 6 + leftPadding + rightPadding
    implicitHeight: implicitContentHeight + topPadding + bottomPadding
    padding: 3
    visible: size < 1
    hoverEnabled: true
    minimumSize: 0.1

    contentItem: Item {
        implicitHeight: 32

        Rectangle {
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: control.hovered || control.pressed ? 6 : 2
            radius: width / 2
            color: Colors.scrollThumb
        }
    }
}
