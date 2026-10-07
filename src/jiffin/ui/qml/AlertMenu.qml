// Snooze's menu, under its button, as Windows 11's menus are (#83, WinUI's MenuFlyout): 4 px
// around the items and 2 px between them, a line before Not here, as wide as the longest item and
// 32 px, 120 px at least. A window of its own that never takes the focus: the window that holds
// it, an alert or the tray list's cards (#84), places it and shows it with the glass. Where that
// window keeps the focus, as the tray list does, its keys move over the items: `current`, with
// WinUI's focus ring.
import QtQuick
import Jiffin

Window {
    id: menu

    // Whether it has Next time: the reminder has a next unit (ADR-0021).
    property bool nextTime: true
    // The item the keyboard is on, among those shown, from the top; -1 for none, as when the
    // menu opens under the mouse.
    property int current: -1

    signal snoozeNextTime
    signal snoozeQuarterHour
    signal snoozeHour
    signal snoozeTomorrow
    signal notHere

    // To the next item or the one before, round from the last to the first, as in Windows'
    // menus; from none, to the first or the last.
    function move(step: int): void {
        const count = column.shown.length;
        menu.current = menu.current < 0 ? (step > 0 ? 0 : count - 1) : (menu.current + step + count) % count;
    }

    // A click on the item the keyboard is on.
    function trigger(): void {
        column.shown[menu.current].click();
    }

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

        // The longest item shown: Next time shows only with a next unit (ADR-0021).
        readonly property real widest: Math.max(nextTimeItem.visible ? nextTimeItem.implicitWidth : 0, quarterHourItem.implicitWidth, hourItem.implicitWidth, tomorrowItem.implicitWidth, notHereItem.implicitWidth)
        // The items shown, from the top, which the keyboard moves over.
        readonly property list<FluentMenuItem> shown: [nextTimeItem, quarterHourItem, hourItem, tomorrowItem, notHereItem].filter(item => item.visible)

        x: 4
        y: 4
        width: menu.width - 8
        spacing: 2

        FluentMenuItem {
            id: nextTimeItem

            width: column.width
            visible: menu.nextTime
            current: column.shown[menu.current] === nextTimeItem
            text: Texts.nextTime
            onClicked: menu.snoozeNextTime()
        }
        FluentMenuItem {
            id: quarterHourItem

            width: column.width
            current: column.shown[menu.current] === quarterHourItem
            text: Texts.inQuarterHour
            onClicked: menu.snoozeQuarterHour()
        }
        FluentMenuItem {
            id: hourItem

            width: column.width
            current: column.shown[menu.current] === hourItem
            text: Texts.inHour
            onClicked: menu.snoozeHour()
        }
        FluentMenuItem {
            id: tomorrowItem

            width: column.width
            current: column.shown[menu.current] === tomorrowItem
            text: Texts.tomorrow
            onClicked: menu.snoozeTomorrow()
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
            id: notHereItem

            width: column.width
            current: column.shown[menu.current] === notHereItem
            text: Texts.notHere
            onClicked: menu.notHere()
        }
    }
}
