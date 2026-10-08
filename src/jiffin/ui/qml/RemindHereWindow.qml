// The card of Remind here, "qui dovevi avvisarmi" (ADR-0029): at the top centre, where the alerts
// come, as wide as an alert and drawn like one: the bell where the alert has its icon, the place
// over the question, the X; under them the active reminders, each with its condition and what
// else kept it quiet there, which grow down to the end of the work area and then scroll. It
// takes the focus: Up and Down move over the reminders, Enter or Space choose, and Esc, the X or
// a click elsewhere close it.
// Bound: the rows take their data as required properties, and reach the card by its id.
pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import Jiffin

Window {
    id: window

    required property RemindHere remindHere
    // The reminder the keyboard is on, from the top; -1 for none, as when the card opens.
    property int current: -1

    // To the next reminder or the one before, round from the last to the first, as in Windows'
    // menus; from none, to the first or the last. The list scrolls to it.
    function move(step: int): void {
        const count = reminders.count;
        if (count === 0)
            return;
        window.current = window.current < 0 ? (step > 0 ? 0 : count - 1) : (window.current + step + count) % count;
        const row = reminders.itemAt(window.current);
        const top = row.mapToItem(list, 0, 0).y;
        if (top < scroller.contentY)
            scroller.contentY = top;
        else if (top + row.height > scroller.contentY + scroller.height)
            scroller.contentY = top + row.height - scroller.height;
    }

    width: 540
    height: remindHere.maxHeight > 0 ? Math.min(column.implicitHeight + 24, remindHere.maxHeight) : column.implicitHeight + 24
    color: "transparent"
    title: Texts.remindHere
    // No button in the taskbar, as the alerts; it takes the focus, which they never do.
    flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint

    onActiveChanged: {
        if (!active)
            window.remindHere.close();
    }

    // As the alert: without glass, the surface is painted here; with material B, a veil goes
    // over the glass.
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

    ColumnLayout {
        id: column

        anchors.fill: parent
        anchors.leftMargin: 14
        anchors.rightMargin: 12
        anchors.topMargin: 12
        anchors.bottomMargin: 12
        spacing: 6

        RowLayout {
            Layout.fillWidth: true
            spacing: 12

            Rectangle {
                Layout.alignment: Qt.AlignTop
                Layout.preferredWidth: 32
                Layout.preferredHeight: 32
                radius: 4
                color: Colors.controlFill

                Text {
                    anchors.centerIn: parent
                    text: "" // Ringer
                    color: Colors.textSecondary
                    font.family: Typography.iconFont
                    font.pixelSize: Typography.icon
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2

                // The place: the window's title, with the site in a browser.
                Text {
                    Layout.fillWidth: true
                    visible: window.remindHere.place.length > 0
                    text: window.remindHere.place
                    color: Colors.textSecondary
                    font.family: Typography.captionFont
                    font.pixelSize: Typography.caption
                    lineHeight: Typography.captionLine
                    lineHeightMode: Text.FixedHeight
                    elide: Text.ElideRight
                    maximumLineCount: 1
                }
                Text {
                    Layout.fillWidth: true
                    text: Texts.remindHereQuestion
                    color: Colors.textPrimary
                    font.family: Typography.textFont
                    font.pixelSize: Typography.body
                    font.weight: Font.DemiBold
                    lineHeight: Typography.bodyLine
                    lineHeightMode: Text.FixedHeight
                }
            }
            FluentButton {
                Layout.alignment: Qt.AlignTop
                kind: FluentButton.Subtle
                glyph: "" // Cancel
                Accessible.name: Texts.close
                onClicked: window.remindHere.close()
            }
        }

        // No place yet, or no reminder: it says so.
        Text {
            Layout.fillWidth: true
            Layout.leftMargin: 44
            Layout.topMargin: 4
            Layout.bottomMargin: 4
            visible: reminders.count === 0
            text: window.remindHere.place.length > 0 ? Texts.noReminders : Texts.noPlace
            color: Colors.textSecondary
            font.family: Typography.textFont
            font.pixelSize: Typography.body
            lineHeight: Typography.bodyLine
            lineHeightMode: Text.FixedHeight
            wrapMode: Text.Wrap
        }

        Flickable {
            id: scroller

            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.leftMargin: 32
            Layout.preferredHeight: list.implicitHeight
            visible: reminders.count > 0
            contentWidth: width
            contentHeight: list.implicitHeight
            boundsBehavior: Flickable.StopAtBounds
            // The mouse clicks the reminders: the wheel and the bar scroll.
            acceptedButtons: Qt.NoButton
            clip: true
            T.ScrollBar.vertical: FluentScrollBar {}

            Column {
                id: list

                width: scroller.width
                spacing: 2

                Repeater {
                    id: reminders

                    model: window.remindHere.reminders

                    delegate: Item {
                        id: row

                        required property string action
                        required property string line
                        required property int index

                        width: list.width
                        implicitHeight: button.implicitHeight

                        T.AbstractButton {
                            id: button

                            anchors.fill: parent
                            implicitHeight: implicitContentHeight + topPadding + bottomPadding
                            leftPadding: 12
                            rightPadding: 12
                            topPadding: 6
                            bottomPadding: 7
                            hoverEnabled: true
                            // The window's keys move over the rows, as over a menu's items.
                            focusPolicy: Qt.NoFocus
                            Accessible.name: row.action
                            Accessible.description: row.line
                            onClicked: window.remindHere.pick(row.index)

                            background: Rectangle {
                                radius: 4
                                color: button.down ? Colors.subtleFillPressed : button.hovered ? Colors.subtleFillHover : "transparent"

                                // The focus ring of the row the keyboard is on: 2 px outer
                                // stroke, 1 px inner, as a menu item's.
                                Rectangle {
                                    visible: window.current === row.index
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
                            contentItem: ColumnLayout {
                                spacing: 0

                                Text {
                                    Layout.fillWidth: true
                                    text: row.action
                                    color: Colors.textPrimary
                                    font.family: Typography.textFont
                                    font.pixelSize: Typography.body
                                    lineHeight: Typography.bodyLine
                                    lineHeightMode: Text.FixedHeight
                                    elide: Text.ElideRight
                                }
                                Text {
                                    Layout.fillWidth: true
                                    visible: row.line.length > 0
                                    text: row.line
                                    color: Colors.textSecondary
                                    font.family: Typography.captionFont
                                    font.pixelSize: Typography.caption
                                    lineHeight: Typography.captionLine
                                    lineHeightMode: Text.FixedHeight
                                    elide: Text.ElideRight
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    Shortcut {
        sequences: [StandardKey.Cancel]
        onActivated: window.remindHere.close()
    }
    Shortcut {
        sequences: ["Down"]
        onActivated: window.move(1)
    }
    Shortcut {
        sequences: ["Up"]
        onActivated: window.move(-1)
    }
    Shortcut {
        sequences: ["Space", "Return", "Enter"]
        enabled: window.current >= 0 && window.current < reminders.count
        onActivated: window.remindHere.pick(window.current)
    }

    Connections {
        target: window.remindHere

        function onOpened(): void {
            window.current = -1;
            scroller.contentY = 0;
        }
    }
}
