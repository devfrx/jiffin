// The creation window (#12, #43, #101): "Quando" and "Ricordami di", "Ogni volta", the sentence
// they make, Annulla and Salva. A card like the alerts, on their material, with its title as its
// first line and an X on it (ADR-0010, ADR-0023). Under "Quando", in place of its hint, the time
// Jiffin understood beside a clock, or the words it did not understand; a time already over turns
// Salva off and says why under the sentence (#84, #90). It takes the focus: Enter saves, or goes to
// the box to write or mend; Esc cancels, as the X does; Tab moves on. It drags from any point no
// control takes.
import QtQuick
import QtQuick.Layouts
import Jiffin

Window {
    id: window

    required property Creation creation
    readonly property bool understood: creation.whenLine.length > 0
    readonly property bool unclear: creation.unclearWords.length > 0

    function submit(): void {
        if (window.creation.ready && !window.creation.past)
            window.creation.save();
        else if (window.creation.conditionSentence.length === 0 || window.creation.past)
            whenBox.forceActiveFocus();
        else
            whatBox.forceActiveFocus();
    }

    width: 460
    height: content.implicitHeight + 44
    color: "transparent"
    title: creation.editing ? Texts.editReminder : Texts.newReminder
    // No button in the taskbar, as Windows' own panels: the shortcut brings it back.
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
        spacing: 16

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
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 6

            FluentTextBox {
                id: whenBox

                Layout.fillWidth: true
                header: Texts.when
                description: window.understood || window.unclear ? "" : Texts.whenHint
                placeholderText: Texts.whenExample
                onTextChanged: window.creation.setCondition(text)
                onAccepted: window.submit()
            }
            // What Jiffin made of the time, read at every key; the clock takes the colour of a
            // warning for a time over or words not understood.
            RowLayout {
                Layout.fillWidth: true
                visible: window.understood || window.unclear
                spacing: 8

                Text {
                    Layout.alignment: Qt.AlignTop
                    Layout.topMargin: 2
                    text: "" // Clock
                    color: window.creation.past || window.unclear ? Colors.caution : Colors.textSecondary
                    font.family: Typography.iconFont
                    font.pixelSize: Typography.icon
                }
                Text {
                    Layout.fillWidth: true
                    text: window.unclear ? Texts.notUnderstood(window.creation.unclearWords) : window.creation.whenLine
                    color: Colors.textPrimary
                    font.family: Typography.textFont
                    font.pixelSize: Typography.body
                    lineHeight: Typography.bodyLine
                    lineHeightMode: Text.FixedHeight
                    wrapMode: Text.Wrap
                }
            }
        }
        FluentTextBox {
            id: whatBox

            Layout.fillWidth: true
            header: Texts.remindMe
            placeholderText: Texts.remindMeExample
            onTextChanged: window.creation.setAction(text)
            onAccepted: window.submit()
        }
        // The check follows the reminder, never the click: the words of a recurrence may put it
        // too (#92).
        FluentCheckBox {
            Layout.fillWidth: true
            text: Texts.everyTime
            description: Texts.everyTimeHint
            checkable: false
            checked: window.creation.perennial
            onClicked: window.creation.togglePerennial()
        }
        Text {
            Layout.fillWidth: true
            text: Texts.preview(window.creation.conditionSentence, window.creation.actionWords, window.creation.perennial)
            color: Colors.textSecondary
            font.family: Typography.textFont
            font.pixelSize: Typography.body
            lineHeight: Typography.bodyLine
            lineHeightMode: Text.FixedHeight
            wrapMode: Text.Wrap
        }
        FluentInfoBar {
            Layout.fillWidth: true
            // Its icon level with the boxes' left edge.
            Layout.leftMargin: -8
            visible: window.creation.past
            message: Texts.past(window.creation.pastWhen)
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: 4
            spacing: 8

            Item {
                Layout.fillWidth: true
            }
            FluentButton {
                Layout.minimumWidth: 96
                text: Texts.cancel
                focusPolicy: Qt.StrongFocus
                onClicked: window.creation.cancel()
            }
            FluentButton {
                Layout.minimumWidth: 96
                kind: FluentButton.Accent
                text: Texts.save
                enabled: window.creation.ready && !window.creation.past
                focusPolicy: Qt.StrongFocus
                onClicked: window.creation.save()
            }
        }
    }

    // The X, as the notifications': on the title's line, 12 px from the edge. Esc does the same
    // from the keyboard, so Tab never stops on it, as on a title bar's.
    FluentButton {
        x: window.width - 12 - width
        y: content.y + title.y + (title.height - height) / 2
        kind: FluentButton.Subtle
        glyph: "" // Cancel
        Accessible.name: Texts.close
        onClicked: window.creation.cancel()
    }

    Shortcut {
        sequences: [StandardKey.Cancel]
        onActivated: window.creation.cancel()
    }

    Connections {
        target: window.creation

        function onOpened(condition: string, action: string): void {
            whenBox.text = condition;
            whatBox.text = action;
            whenBox.forceActiveFocus();
        }
    }
}
