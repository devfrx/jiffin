// The creation window (#12, #43): "Quando" and "Ricordami di", the sentence they make, Annulla
// and Salva. A card like the alerts, on their material, with its title as its first line
// (ADR-0010). It takes the focus: Enter saves, or goes to the box still empty; Esc cancels; Tab
// moves on.
import QtQuick
import QtQuick.Layouts
import Jiffin

Window {
    id: window

    required property Creation creation

    function submit(): void {
        if (window.creation.ready)
            window.creation.save();
        else if (window.creation.conditionSentence.length === 0)
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

    ColumnLayout {
        id: content

        x: 24
        y: 20
        width: window.width - 48
        spacing: 16

        Text {
            Layout.fillWidth: true
            text: window.title
            color: Colors.textPrimary
            font.family: Typography.textFont
            font.pixelSize: Typography.body
            font.weight: Font.DemiBold
            lineHeight: Typography.bodyLine
            lineHeightMode: Text.FixedHeight
        }
        FluentTextBox {
            id: whenBox

            Layout.fillWidth: true
            header: Texts.when
            description: Texts.whenHint
            placeholderText: Texts.whenExample
            onTextChanged: window.creation.setCondition(text)
            onAccepted: window.submit()
        }
        FluentTextBox {
            id: whatBox

            Layout.fillWidth: true
            header: Texts.remindMe
            placeholderText: Texts.remindMeExample
            onTextChanged: window.creation.setAction(text)
            onAccepted: window.submit()
        }
        Text {
            Layout.fillWidth: true
            text: Texts.preview(window.creation.conditionSentence, window.creation.actionWords)
            color: Colors.textSecondary
            font.family: Typography.textFont
            font.pixelSize: Typography.body
            lineHeight: Typography.bodyLine
            lineHeightMode: Text.FixedHeight
            wrapMode: Text.Wrap
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
                enabled: window.creation.ready
                focusPolicy: Qt.StrongFocus
                onClicked: window.creation.save()
            }
        }
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
