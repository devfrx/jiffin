// One alert: a strip at the top of the screen that never takes the focus (#12, ADR-0010).
// The user's "Quando…" over what to do, Fatto, Rimanda and "…", and a bar for the 10 s.
// Rimanda and "…" open panels in the strip itself: a menu window could take the focus.
import QtQuick
import QtQuick.Layouts
import Jiffin

Window {
    id: window

    required property AlertSlot slot
    // How long the alert waits for an answer (#12).
    property int duration: 10000
    property real progress: 1

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
                    text: "" // Document
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
                    text: window.slot.condition
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

            // As wide as the widest panel, so the text keeps its width when a panel opens.
            Item {
                Layout.preferredWidth: Math.max(buttons.implicitWidth, snooze.implicitWidth, more.implicitWidth)
                Layout.preferredHeight: 32

                Row {
                    id: buttons

                    anchors.right: parent.right
                    spacing: 8
                    visible: window.slot.panel === AlertSlot.BUTTONS

                    FluentButton {
                        kind: FluentButton.Accent
                        text: Texts.done
                        onClicked: window.slot.done()
                    }
                    FluentButton {
                        text: Texts.snooze
                        chevron: true
                        onClicked: window.slot.openSnooze()
                    }
                    FluentButton {
                        kind: FluentButton.Subtle
                        glyph: "" // More
                        Accessible.name: Texts.more
                        onClicked: window.slot.openMore()
                    }
                }
                Row {
                    id: snooze

                    anchors.right: parent.right
                    spacing: 8
                    visible: window.slot.panel === AlertSlot.SNOOZE

                    FluentButton {
                        kind: FluentButton.Subtle
                        glyph: "" // Back
                        Accessible.name: Texts.back
                        onClicked: window.slot.back()
                    }
                    FluentButton {
                        text: Texts.quarterHour
                        onClicked: window.slot.snoozeQuarterHour()
                    }
                    FluentButton {
                        text: Texts.hour
                        onClicked: window.slot.snoozeHour()
                    }
                    FluentButton {
                        text: Texts.tomorrow
                        onClicked: window.slot.snoozeTomorrow()
                    }
                }
                Row {
                    id: more

                    anchors.right: parent.right
                    spacing: 8
                    visible: window.slot.panel === AlertSlot.MORE

                    FluentButton {
                        kind: FluentButton.Subtle
                        glyph: "" // Back
                        Accessible.name: Texts.back
                        onClicked: window.slot.back()
                    }
                    FluentButton {
                        text: Texts.useful
                        onClicked: window.slot.useful()
                    }
                    FluentButton {
                        text: Texts.notHere
                        onClicked: window.slot.notHere()
                    }
                }
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
}
