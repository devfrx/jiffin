// A Fluent 2 combo box, drawn by us (ADR-0010), as WinUI's ComboBox
// (ComboBox_themeresources.xaml, microsoft-ui-xaml at 8463f45162): 32 px high, the control fill
// and edge of a standard button, the text 12 px in, ChevronDown (E70D) at 12 px, 14 px from the
// right. Its list is a window of its own on the glass that never takes the focus, as Rimanda's
// menu: as wide as the box, with the chosen item over the box; each item 32 px high in a slot of
// 36, 5 px from the sides, rounded at 3 px, and the chosen one filled and marked by WinUI's pill.
// Whoever holds the box shows the list, `list`, when it is clicked, and says it is `open`.
// With the focus, Space, Enter, Alt+Down and F4 open the list, and Up and Down pick the item
// before or after; with the list open they move over its items, with WinUI's focus ring, and
// Space or Enter picks one.
// Bound: the items take their text and index as required properties.
pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Templates as T
import Jiffin

T.AbstractButton {
    id: control

    property list<string> model
    property int currentIndex: 0
    property bool open: false
    // The item the keyboard is on while the list is open; -1 until a key moves, when the list
    // opened under the mouse.
    property int current: -1
    // The list's window, for whoever shows it: a QtObject, since PySide has no converter for the
    // Window type of QML.
    readonly property QtObject list: dropdown

    // An item picked, from the list or with Up and Down.
    signal activated(int index)
    // The focus moved on from the box, by Tab, while the list was open; its window losing the
    // focus is for whoever holds the box to hear.
    signal dismissed

    function move(step: int): void {
        const from = control.current < 0 ? control.currentIndex : control.current;
        control.current = Math.max(0, Math.min(control.model.length - 1, from + step));
    }

    implicitWidth: 120
    implicitHeight: 32
    leftPadding: 12
    rightPadding: 14 + 12 + 8
    focusPolicy: Qt.StrongFocus
    hoverEnabled: true
    text: control.model[control.currentIndex] ?? ""
    Accessible.role: Accessible.ComboBox

    onOpenChanged: {
        control.current = control.open && control.visualFocus ? control.currentIndex : -1;
        if (control.open) {
            // Placed as it opens: the window may have moved since the last time.
            const corner = control.mapToGlobal(0, 0);
            dropdown.x = Math.round(corner.x);
            dropdown.y = Math.round(corner.y) - 6 - 36 * control.currentIndex;
        }
    }
    onActiveFocusChanged: {
        if (!control.activeFocus && control.open && control.focusReason !== Qt.ActiveWindowFocusReason)
            control.dismissed();
    }

    // Before the button's own keys: Space picks the item the keyboard is on.
    Keys.priority: Keys.BeforeItem
    Keys.onPressed: event => {
        const down = event.key === Qt.Key_Down;
        const step = event.key === Qt.Key_Up || down;
        const enter = event.key === Qt.Key_Return || event.key === Qt.Key_Enter;
        if (control.open) {
            if (step)
                control.move(down ? 1 : -1);
            else if ((enter || event.key === Qt.Key_Space) && control.current >= 0)
                control.activated(control.current);
            else if (enter)
                control.click();
            else
                return;
        } else if ((down && event.modifiers & Qt.AltModifier) || event.key === Qt.Key_F4 || enter) {
            control.click();
        } else if (step) {
            const index = control.currentIndex + (down ? 1 : -1);
            if (index >= 0 && index < control.model.length)
                control.activated(index);
        } else {
            return;
        }
        event.accepted = true;
    }

    background: Rectangle {
        radius: 4
        color: control.down ? Colors.controlFillPressed : control.hovered ? Colors.controlFillHover : Colors.controlFill
        border.width: 1
        border.color: Colors.controlStroke

        // The edge that makes it look raised, as a standard button's.
        Rectangle {
            x: 4
            y: Colors.controlEdgeAtBottom ? parent.height - 1 : 0
            width: parent.width - 8
            height: 1
            color: Colors.controlStrokeEdge
        }

        // The focus ring, 3 px outside the box: 2 px outer stroke, 1 px inner.
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
    contentItem: Text {
        text: control.text
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        color: control.down ? Colors.textSecondary : Colors.textPrimary
        font.family: Typography.textFont
        font.pixelSize: Typography.body
    }

    Text {
        anchors.right: parent.right
        anchors.rightMargin: 14
        anchors.verticalCenter: parent.verticalCenter
        text: "" // ChevronDown
        color: Colors.textSecondary
        font.family: Typography.iconFont
        font.pixelSize: Typography.chevron
    }

    Window {
        id: dropdown

        width: control.width
        height: column.implicitHeight + 12
        color: "transparent"
        title: control.Accessible.name
        flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus

        // Without glass, the surface is painted here; with material B, a veil goes over the
        // glass.
        Rectangle {
            anchors.fill: parent
            visible: Look.solid
            color: Colors.surface
        }
        Rectangle {
            anchors.fill: parent
            visible: Look.veilOpacity > 0
            color: Colors.veil
            opacity: Look.veilOpacity
        }

        // 4 px above and below the items, and each item 2 px from its slot's edges.
        Column {
            id: column

            x: 5
            y: 6
            width: dropdown.width - 10
            spacing: 4

            Repeater {
                model: control.model

                delegate: T.AbstractButton {
                    id: item

                    required property int index
                    required property string modelData
                    readonly property bool chosen: index === control.currentIndex

                    width: column.width
                    implicitHeight: 32
                    leftPadding: 11
                    rightPadding: 11
                    focusPolicy: Qt.NoFocus
                    hoverEnabled: true
                    text: modelData
                    Accessible.name: modelData
                    onClicked: control.activated(index)

                    background: Rectangle {
                        radius: 3
                        color: {
                            if (item.down)
                                return item.chosen ? Colors.subtleFillHover : Colors.subtleFillPressed;
                            if (item.hovered)
                                return item.chosen ? Colors.subtleFillPressed : Colors.subtleFillHover;
                            return item.chosen ? Colors.subtleFillHover : "transparent";
                        }

                        // WinUI's pill, on the chosen item.
                        Rectangle {
                            x: 1
                            anchors.verticalCenter: parent.verticalCenter
                            width: 3
                            height: 16
                            radius: 1.5
                            visible: item.chosen
                            color: Colors.accent
                        }

                        // The focus ring, 3 px outside the item, on the one the keyboard is on.
                        Rectangle {
                            visible: item.index === control.current
                            anchors.fill: parent
                            anchors.margins: -3
                            radius: 6
                            color: "transparent"
                            border.width: 2
                            border.color: Colors.focusStrokeOuter

                            Rectangle {
                                anchors.fill: parent
                                anchors.margins: 2
                                radius: 4
                                color: "transparent"
                                border.width: 1
                                border.color: Colors.focusStrokeInner
                            }
                        }
                    }
                    contentItem: Text {
                        text: item.text
                        verticalAlignment: Text.AlignVCenter
                        color: item.down ? Colors.textSecondary : Colors.textPrimary
                        font.family: Typography.textFont
                        font.pixelSize: Typography.body
                    }
                }
            }
        }
    }
}
