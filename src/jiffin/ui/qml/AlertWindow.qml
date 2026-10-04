// One alert: a strip at the top of the screen that never takes the focus (#12, ADR-0010). The
// user's "Quando…" and the time understood over what to do, then Fatto, Rimanda and the X (#83,
// ADR-0023), and a bar for the 10 s. Rimanda opens its menu under the button: a window of its
// own, which the alert places and the overlay shows.
import QtQuick
import QtQuick.Layouts
import Jiffin

Window {
    id: window

    required property AlertSlot slot
    // How long the alert waits for an answer (#12).
    property int duration: 10000
    property real progress: 1
    // Rimanda's menu, for the overlay to show and hide: a QtObject, since PySide has no
    // converter for the Window type of QML.
    readonly property QtObject menu: snoozeMenu
    // Where the menu opens in the window: under Rimanda, on its left edge and 4 px down, as
    // Windows' menus do. Taken at each click, in the strip, without the slide of its entrance.
    property point menuAt

    width: 540
    height: strip.implicitHeight
    color: "transparent"
    title: Texts.reminder
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

    Item {
        id: strip

        width: window.width
        height: window.height
        implicitHeight: row.implicitHeight + 24
        transform: Translate {
            id: slide
        }

        RowLayout {
            id: row

            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: 14
            anchors.rightMargin: 12
            spacing: 12

            Rectangle {
                Layout.preferredWidth: 32
                Layout.preferredHeight: 32
                radius: 4
                color: Colors.controlFill

                Text {
                    anchors.centerIn: parent
                    text: window.slot.perennial ? "" : "" // RepeatAll, Document
                    color: Colors.textSecondary
                    font.family: Typography.iconFont
                    font.pixelSize: Typography.icon
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2

                Text {
                    Layout.fillWidth: true
                    text: window.slot.line
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
                    text: window.slot.action
                    color: Colors.textPrimary
                    font.family: Typography.textFont
                    font.pixelSize: Typography.body
                    font.weight: Font.DemiBold
                    lineHeight: Typography.bodyLine
                    lineHeightMode: Text.FixedHeight
                    wrapMode: Text.Wrap
                    elide: Text.ElideRight
                    maximumLineCount: 2
                }
            }

            Row {
                spacing: 8

                FluentButton {
                    kind: FluentButton.Accent
                    text: Texts.done
                    onClicked: window.slot.done()
                }
                FluentButton {
                    id: snooze

                    text: Texts.snooze
                    chevron: true
                    onClicked: {
                        window.menuAt = snooze.mapToItem(strip, 0, snooze.height + 4);
                        window.slot.toggleMenu();
                    }
                }
            }

            // The X closes without an answer (ADR-0023), 8 px after Rimanda.
            FluentButton {
                Layout.leftMargin: -4
                kind: FluentButton.Subtle
                glyph: "" // Cancel
                Accessible.name: Texts.close
                onClicked: window.slot.close()
            }
        }
    }

    // The 10 s passing, also with animations off (ADR-0010).
    Rectangle {
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        width: window.width * window.progress
        height: 2
        color: Colors.accent
    }

    HoverHandler {
        onHoveredChanged: window.slot.hover(hovered)
    }

    NumberAnimation {
        id: countdown

        target: window
        property: "progress"
        from: 1
        to: 0
        duration: window.duration
        paused: running && window.slot.paused
        onFinished: window.slot.expire()
    }

    // WinUI's motion: in from the top in 250 ms, out in 167 ms; only a fade with animations off.
    ParallelAnimation {
        id: enter

        NumberAnimation {
            target: strip
            property: "opacity"
            from: 0
            to: 1
            duration: 250
            easing.type: Easing.BezierSpline
            easing.bezierCurve: [0, 0, 0, 1, 1, 1]
        }
        NumberAnimation {
            target: slide
            property: "y"
            from: Look.animations ? -12 : 0
            to: 0
            duration: 250
            easing.type: Easing.BezierSpline
            easing.bezierCurve: [0, 0, 0, 1, 1, 1]
        }
    }
    SequentialAnimation {
        id: leave

        ParallelAnimation {
            NumberAnimation {
                target: strip
                property: "opacity"
                to: 0
                duration: 167
                easing.type: Easing.BezierSpline
                easing.bezierCurve: [1, 0, 1, 1, 1, 1]
            }
            NumberAnimation {
                target: slide
                property: "y"
                to: Look.animations ? -12 : 0
                duration: 167
                easing.type: Easing.BezierSpline
                easing.bezierCurve: [1, 0, 1, 1, 1, 1]
            }
        }
        ScriptAction {
            script: window.slot.left()
        }
    }

    Connections {
        target: window.slot

        function onPresented(): void {
            window.progress = 1;
            countdown.restart();
            enter.restart();
        }

        function onLeaving(): void {
            countdown.stop();
            enter.stop();
            leave.restart();
        }
    }

    // It follows the alert when the alerts above leave and it moves up.
    AlertMenu {
        id: snoozeMenu

        slot: window.slot
        x: window.x + Math.round(window.menuAt.x)
        y: window.y + Math.round(window.menuAt.y)
    }
}
