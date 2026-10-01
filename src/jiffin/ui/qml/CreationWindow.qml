// The creation window (#12, #43): "Quando" and "Ricordami di", the sentence they make, Annulla
// and Salva. Windows' own frame and title bar, with Mica under the content (ADR-0010). It takes
// the focus: Enter saves, or goes to the box still empty; Esc cancels; Tab moves on.
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
    height: content.implicitHeight + 36
    color: "transparent"
    title: creation.editing ? Texts.editReminder : Texts.newReminder
    flags: Qt.Window | Qt.CustomizeWindowHint | Qt.WindowTitleHint | Qt.WindowCloseButtonHint | Qt.MSWindowsFixedSizeDialogHint

    // Without glass, Mica's fallback is painted here.
    Rectangle {
        anchors.fill: parent
        visible: Look.solid
        color: Colors.micaFallback
    }

    ColumnLayout {
        id: content

        x: 24
        y: 12
        width: window.width - 48
        spacing: 16

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
