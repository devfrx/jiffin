// The first-run window (#43, ADR-0015): the model file on its way, in three steps, the download,
// the check and ready; a problem with Retry, and the file by hand when offline; at the end, how
// to start. A card like the creation window, on the alerts' material, with an X on its title's
// line (ADR-0010, ADR-0023). The owner chose the steps on screen. It takes the focus; Tab moves
// on, and Esc, the X, Close or Start closes it. It drags from any point no control takes.
pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import Jiffin

Window {
    id: window

    required property FirstRun firstRun

    readonly property bool ready: firstRun.stage === FirstRun.READY
    // The steps to get the file by hand: open on demand, offline or with the wrong file.
    property bool byHand: false

    width: 440
    height: content.implicitHeight + 40
    color: "transparent"
    title: ready ? Texts.isReady : Texts.welcome
    // No button in the taskbar, as Windows' own panels: Details, in the tray list, brings it back.
    flags: Qt.Tool | Qt.FramelessWindowHint

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

    // Any point no control takes moves the window, as a title bar does (ADR-0023).
    Item {
        anchors.fill: parent

        DragHandler {
            target: null
            // Never from a control: Qt's default would take a drag over from the item that
            // got the press, a button too.
            grabPermissions: PointerHandler.CanTakeOverFromHandlersOfDifferentType | PointerHandler.ApprovesTakeOverByAnything
            onActiveChanged: {
                if (active)
                    window.startSystemMove();
            }
        }
    }

    ColumnLayout {
        id: content

        x: 24
        y: 20
        width: window.width - 48
        spacing: 12

        Text {
            id: title

            Layout.fillWidth: true
            // Clear of the X.
            Layout.rightMargin: 32
            text: window.title
            color: Colors.textPrimary
            font.family: Typography.textFont
            font.pixelSize: Typography.body
            font.weight: Font.DemiBold
            lineHeight: Typography.bodyLine
            lineHeightMode: Text.FixedHeight
        }

        // On its way: the steps.
        ColumnLayout {
            Layout.fillWidth: true
            visible: !window.ready
            spacing: 10

            BodyText {
                text: Texts.onlyHere
            }
            Step {
                number: 1
                label: Texts.stepDownload
                bar: window.firstRun.step === 1
                value: window.firstRun.total > 0 ? window.firstRun.done / window.firstRun.total : 0
                detail: window.firstRun.step !== 1 ? "" : window.firstRun.problem ? Texts.stopped(window.firstRun.done, window.firstRun.total) : Texts.downloaded(window.firstRun.done, window.firstRun.total, window.firstRun.minutes)
            }
            Step {
                number: 2
                label: Texts.stepCheck
                bar: window.firstRun.stage === FirstRun.CHECKING
                value: window.firstRun.total > 0 ? window.firstRun.done / window.firstRun.total : 0
                detail: ""
            }
            Step {
                number: 3
                label: Texts.stepReady
                bar: false
                value: 0
                detail: ""
            }
        }

        // A problem, with Retry; offline or with the wrong file, the way to put it by hand.
        ColumnLayout {
            Layout.fillWidth: true
            visible: window.firstRun.problem
            spacing: 8

            FluentInfoBar {
                Layout.fillWidth: true
                Layout.leftMargin: -8
                severity: FluentInfoBar.Error
                message: Texts.modelTrouble(window.firstRun.stage, window.firstRun.missing)

                FluentButton {
                    text: window.firstRun.retrying ? Texts.retrying : Texts.retry
                    enabled: !window.firstRun.retrying
                    focusPolicy: Qt.StrongFocus
                    onClicked: window.firstRun.retry()
                }
            }
            FluentButton {
                id: byHandButton

                readonly property bool offline: window.firstRun.stage === FirstRun.NETWORK

                visible: offline || window.firstRun.stage === FirstRun.MISMATCH
                kind: FluentButton.Subtle
                text: offline ? Texts.byHandOffline : Texts.byHand
                chevron: true
                focusPolicy: Qt.StrongFocus
                onClicked: window.byHand = !window.byHand
            }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 12
                visible: byHandButton.visible && window.byHand
                spacing: 6

                CaptionText {
                    text: Texts.byHandFetch
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    CaptionText {
                        text: window.firstRun.address
                        wrapMode: Text.NoWrap
                        elide: Text.ElideMiddle
                    }
                    FluentButton {
                        id: copyButton

                        // A check, for a moment, once the address is on the clipboard.
                        property bool copied: false

                        glyph: copied ? "" : "" // CheckMark, Copy
                        Accessible.name: Texts.copyAddress
                        focusPolicy: Qt.StrongFocus
                        onClicked: {
                            window.firstRun.copyAddress();
                            copied = true;
                            copiedTimer.restart();
                        }

                        Timer {
                            id: copiedTimer

                            interval: 2000
                            onTriggered: copyButton.copied = false
                        }
                    }
                }
                CaptionText {
                    text: Texts.byHandPlace(window.firstRun.fileName)
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    CaptionText {
                        text: window.firstRun.folder
                        wrapMode: Text.NoWrap
                        elide: Text.ElideMiddle
                    }
                    FluentButton {
                        glyph: "" // FolderOpen
                        Accessible.name: Texts.openFolder
                        focusPolicy: Qt.StrongFocus
                        onClicked: window.firstRun.openFolder()
                    }
                }
                CaptionText {
                    text: Texts.byHandCheck(window.firstRun.size, window.firstRun.sha256)
                }
            }
        }

        BodyText {
            visible: !window.ready && !window.firstRun.problem
            text: window.firstRun.hasShortcut ? Texts.meanwhile : Texts.meanwhileTray
        }

        // Ready: how to start.
        ColumnLayout {
            Layout.fillWidth: true
            visible: window.ready
            spacing: 8

            BodyText {
                text: window.firstRun.hasShortcut ? Texts.readyShortcut : Texts.shortcutTaken
            }
            BodyText {
                text: Texts.readyTray
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: 4

            Item {
                Layout.fillWidth: true
            }
            FluentButton {
                Layout.minimumWidth: 96
                kind: window.ready ? FluentButton.Accent : FluentButton.Standard
                text: window.ready ? Texts.start : Texts.close
                focusPolicy: Qt.StrongFocus
                onClicked: window.firstRun.close()
            }
        }
    }

    // The X, as the creation window's: on the title's line, 12 px from the edge, never reached
    // by Tab, since Esc does the same.
    FluentButton {
        x: window.width - 12 - width
        y: content.y + title.y + (title.height - height) / 2
        kind: FluentButton.Subtle
        glyph: "" // Cancel
        Accessible.name: Texts.close
        onClicked: window.firstRun.close()
    }

    Shortcut {
        sequences: [StandardKey.Cancel]
        onActivated: window.firstRun.close()
    }

    Connections {
        target: window.firstRun

        function onOpened(): void {
            window.byHand = false;
        }
    }

    // A step: its disc, with its number or, once done, a check; its name; and, while it runs, a
    // bar and a line under it.
    component Step: RowLayout {
        id: step

        required property int number
        required property string label
        required property bool bar
        required property real value
        required property string detail
        readonly property bool done: window.firstRun.step > number
        readonly property bool now: window.firstRun.step === number
        readonly property bool stuck: now && window.firstRun.problem
        readonly property color mark: stuck ? Colors.caution : now ? Colors.accent : Colors.textSecondary

        Layout.fillWidth: true
        spacing: 12

        Rectangle {
            Layout.alignment: Qt.AlignTop
            implicitWidth: 20
            implicitHeight: 20
            radius: 10
            color: step.done ? Colors.accent : "transparent"
            border.width: step.done ? 0 : 1
            border.color: step.stuck ? Colors.caution : step.now ? Colors.accent : Colors.controlStrongStroke

            Text {
                anchors.centerIn: parent
                text: step.done ? "" : String(step.number) // CheckMark
                color: step.done ? Colors.textOnAccent : step.mark
                font.family: step.done ? Typography.iconFont : Typography.captionFont
                font.pixelSize: step.done ? 10 : Typography.caption
                font.weight: Font.DemiBold
            }
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 4

            Text {
                Layout.fillWidth: true
                text: step.label
                color: step.done || step.now ? Colors.textPrimary : Colors.textSecondary
                font.family: Typography.textFont
                font.pixelSize: Typography.body
                lineHeight: Typography.bodyLine
                lineHeightMode: Text.FixedHeight
            }
            FluentProgressBar {
                Layout.fillWidth: true
                Layout.topMargin: 4
                visible: step.bar
                value: step.value
                paused: window.firstRun.problem
                Accessible.name: step.label
            }
            CaptionText {
                visible: step.detail.length > 0
                text: step.detail
            }
        }
    }

    component BodyText: Text {
        Layout.fillWidth: true
        color: Colors.textPrimary
        font.family: Typography.textFont
        font.pixelSize: Typography.body
        lineHeight: Typography.bodyLine
        lineHeightMode: Text.FixedHeight
        wrapMode: Text.Wrap
    }

    component CaptionText: Text {
        Layout.fillWidth: true
        color: Colors.textSecondary
        font.family: Typography.captionFont
        font.pixelSize: Typography.caption
        lineHeight: Typography.captionLine
        lineHeightMode: Text.FixedHeight
        wrapMode: Text.Wrap
    }
}
