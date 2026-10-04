// Rimanda's menu, under its button, as Windows 11's menus are (#83, WinUI's MenuFlyout): 4 px
// around the items and 2 px between them, a line before Non qui, as wide as the longest item and
// 32 px, 120 px at least. A window of its own that never takes the focus, like its alert: the
// alert places it, and the overlay shows it with the glass.
import QtQuick
import Jiffin

Window {
    id: menu

    required property AlertSlot slot

    width: Math.ceil(Math.max(120, column.widest + 8))
    height: column.implicitHeight + 8
    color: "transparent"
    title: Texts.snooze
    flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus

    // Without glass, the surface is painted here; with material B, a veil goes over the glass.
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

    Column {
        id: column

        // The longest item shown: Alla prossima volta shows only with a next unit (ADR-0021).
        readonly property real widest: Math.max(nextTime.visible ? nextTime.implicitWidth : 0, quarterHour.implicitWidth, hour.implicitWidth, tomorrow.implicitWidth, notHere.implicitWidth)

        x: 4
        y: 4
        width: menu.width - 8
        spacing: 2

        FluentMenuItem {
            id: nextTime

            width: column.width
            visible: menu.slot.nextTime
            text: Texts.nextTime
            onClicked: menu.slot.snoozeNextTime()
        }
        FluentMenuItem {
            id: quarterHour

            width: column.width
            text: Texts.inQuarterHour
            onClicked: menu.slot.snoozeQuarterHour()
        }
        FluentMenuItem {
            id: hour

            width: column.width
            text: Texts.inHour
            onClicked: menu.slot.snoozeHour()
        }
        FluentMenuItem {
            id: tomorrow

            width: column.width
            text: Texts.tomorrow
            onClicked: menu.slot.snoozeTomorrow()
        }
        // The line, the whole width of the menu, with 4 px above and below.
        Item {
            width: column.width
            height: 5

            Rectangle {
                x: -4
                width: menu.width
                height: 1
                anchors.verticalCenter: parent.verticalCenter
                color: Colors.controlStroke
            }
        }
        FluentMenuItem {
            id: notHere

            width: column.width
            text: Texts.notHere
            onClicked: menu.slot.notHere()
        }
    }
}
